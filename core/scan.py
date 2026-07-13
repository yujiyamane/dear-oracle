"""core/scan.py — DK Watchlist → Polymarket scan → do_hits.json.

Reads the DK Watchlist (from Notion if NOTION_TOKEN is set, else from data/sample.json),
queries Polymarket for each active topic, and writes do_hits.json atomically to the
given output path so that DK (GAS) can blend market data into topic cards.

Production output: G:\\My Drive\\DawnPatrol\\do_hits.json
  (Drive folder 14RNcLAHrDxJ8S-frsiPJsbRXFGiUjGxr — set in config/delivery.json → do_hits_path)
  NOT data/do_hits.json (local repo copy). Always verify generated_at advanced in the Drive file.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from core.market_history import attach_history, load_prev_history
from core.market_notes import annotate_pool, build_note, classify_relevance
from core.veto_gate import veto_check

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_JSON = PROJECT_ROOT / "data" / "sample.json"

# Notion API base
_NOTION_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"

_ENV_FILE = PROJECT_ROOT / "config" / ".env"


def _load_env_file() -> None:
    """Load config/.env into os.environ if not already set (no-op if file absent)."""
    if not _ENV_FILE.exists():
        return
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = val.strip()


_load_env_file()


def _watchlist_db_id() -> str:
    return os.environ.get("DK_WATCHLIST_DB_ID", "")


# ---------------------------------------------------------------------------
# Watchlist loading
# ---------------------------------------------------------------------------

def load_watchlist(notion_token: str | None = None) -> list[dict]:
    """Return list of active topic dicts.

    If notion_token is set, fetch from the DK Watchlist DB in Notion.
    Otherwise fall back to data/sample.json. Never raises.
    """
    token = notion_token or os.environ.get("NOTION_TOKEN")
    if token:
        try:
            topics = _fetch_notion_watchlist(token)
            if topics:
                return topics
            log.warning("Notion watchlist returned 0 topics — falling back to sample.json")
        except Exception as exc:
            log.warning("Notion watchlist fetch failed (%s) — falling back to sample.json", exc)

    return _load_sample()


def _try_load_notion(token: str) -> tuple[list[dict], bool]:
    """Try Notion; return (topics, notion_failed). Does NOT fall back to sample."""
    try:
        topics = _fetch_notion_watchlist(token)
        if topics:
            return topics, False
        log.warning("Notion watchlist returned 0 topics")
        return [], False
    except Exception as exc:
        log.warning("Notion watchlist fetch failed (%s) — scan will not write", exc)
        return [], True


def _load_sample() -> list[dict]:
    data = json.loads(_SAMPLE_JSON.read_text(encoding="utf-8"))
    return data.get("topics", [])


def _fetch_notion_watchlist(token: str) -> list[dict]:
    """Fetch active topics from Notion 08a Watchlist DB."""
    db_id = _watchlist_db_id()
    if not db_id:
        raise ValueError("DK_WATCHLIST_DB_ID not set — add it to config/.env")
    url = f"{_NOTION_BASE}/databases/{db_id}/query"
    payload = json.dumps({"filter": {"property": "Active", "checkbox": {"equals": True}}}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    topics = []
    for page in data.get("results", []):
        props = page.get("properties", {})
        wl_id_num = props.get("WL_ID", {}).get("unique_id", {}).get("number")
        if wl_id_num is None:
            log.warning("Notion page %s missing WL_ID — skipped", page.get("id"))
            continue
        topic_key = f"WL-{int(wl_id_num)}"
        topic_label = _notion_text(props.get("Topic", {}))
        weight = _notion_number(props.get("Weight", {})) or 1
        keywords = _notion_text(props.get("Keywords", {}))
        keywords_ja = _notion_text(props.get("KeywordsJa", {}))
        lang_raw = _notion_multiselect(props.get("Lang", {}))
        lang = lang_raw if lang_raw else ["en-AU"]

        topics.append({
            "topic_key": topic_key,
            "topic_label": topic_label,
            "weight": weight,
            "keywords": keywords,
            "keywords_ja": keywords_ja,
            "lang": lang,
        })
    return topics


def _notion_text(prop: dict) -> str:
    if prop.get("type") == "rich_text":
        parts = prop.get("rich_text", [])
    elif prop.get("type") == "title":
        parts = prop.get("title", [])
    else:
        return ""
    return "".join(p.get("plain_text", "") for p in parts)


def _notion_number(prop: dict) -> float | None:
    return prop.get("number")


def _notion_multiselect(prop: dict) -> list[str]:
    return [o["name"] for o in prop.get("multi_select", [])]


# ---------------------------------------------------------------------------
# Polymarket query — relevance-guarded via /public-search
# ---------------------------------------------------------------------------

from core.relevance import is_relevant as _is_relevant_v2


def _query_topic(topic: dict, adapter: Any) -> list[dict]:
    """Search Polymarket for a topic via /public-search + relevance guard.

    MarketTerms-first: if topic.market_terms (semicolon-delimited) is non-empty,
    every term is queried and relevant results are merged (dedup by market_id) —
    see _query_by_market_terms. Keywords is ignored in that case.

    Otherwise falls back to Keywords: tries each semicolon-delimited keyword in
    order; stops at the first keyword that yields at least one relevant event.
    NEVER falls back to top-by-volume. Returns [] if no relevant event is found
    for any keyword.

    Relevance: acronym-match OR multi-word phrase-match OR >=2 generic tokens
    (see core.relevance). Single common-word matches are rejected.
    """
    market_terms_raw = topic.get("market_terms", "")
    market_terms = [t.strip() for t in market_terms_raw.split(";") if t.strip()]
    if market_terms:
        return _query_by_market_terms(topic, adapter, market_terms)

    keywords_raw = topic.get("keywords", "")
    keywords = [k.strip() for k in keywords_raw.split(";") if k.strip()]
    if not keywords:
        label = topic.get("topic_label", "")
        if label:
            keywords = [label]
        else:
            return []

    best_event = None

    for keyword in keywords:
        try:
            events = adapter.public_search(keyword, limit=10)
        except Exception as exc:
            log.warning("Polymarket public_search failed for '%s': %s", keyword, exc)
            continue

        relevant = [e for e in events if _is_relevant_v2(topic, getattr(e, "event_title", ""))]
        if not relevant:
            continue

        best_event = max(relevant, key=lambda e: getattr(e, "volume_usd", None) or 0.0)
        break

    if best_event is None:
        return []

    markets = []
    for m in getattr(best_event, "markets", []):
        prob_now = getattr(m, "prob_now", None)
        if prob_now is None:
            continue
        prob_7d = getattr(m, "prob_7d_ago", None)
        delta_7d = round(prob_now - prob_7d, 4) if (prob_7d is not None and prob_7d > 0.0) else None
        markets.append({
            "title": getattr(best_event, "event_title", ""),
            "url": getattr(m, "url", ""),
            "prob_now": round(prob_now, 4),
            "delta_7d": delta_7d,
            "volume_usd": getattr(best_event, "volume_usd", None),
            "outcome_label": getattr(m, "outcome_label", "") or "",
        })

    markets.sort(key=lambda x: x["prob_now"], reverse=True)
    markets = markets[:3]
    for m in markets:
        m["relevance"] = classify_relevance(m.get("title", ""))
        m["note"] = build_note(m)
    return markets


def _query_by_market_terms(topic: dict, adapter: Any, terms: list[str]) -> list[dict]:
    """Search Polymarket via MarketTerms: one query per term, OR-joined.

    Unlike the Keywords path (which stops at the first term with a relevant
    hit), every term is queried and relevant events are merged, deduped by
    market_id (first-seen wins).

    Same hard active/unresolved filter as core.reality_check.hard_filter_events
    (active is True and closed is False) is applied before a candidate is
    considered, then each surviving candidate is run through the AI veto gate
    (core.veto_gate.veto_check) — drop-only, mirrors reality_check_pipeline's
    design law. Each event contributes at most one line: its single leading
    (highest prob_now) outcome, not every outcome.
    """
    seen_ids: set = set()
    candidates: list[dict] = []

    for term in terms:
        try:
            events = adapter.public_search(term, limit=10)
        except Exception as exc:
            log.warning("Polymarket public_search failed for '%s': %s", term, exc)
            continue

        relevant = [e for e in events if _is_relevant_v2(topic, getattr(e, "event_title", ""))]
        for event in relevant:
            if getattr(event, "active", None) is not True or getattr(event, "closed", None) is not False:
                continue
            usable = [m for m in getattr(event, "markets", []) if getattr(m, "prob_now", None) is not None]
            if not usable:
                continue
            market = max(usable, key=lambda m: m.prob_now)
            market_id = getattr(market, "market_id", None)
            if market_id is not None:
                if market_id in seen_ids:
                    continue
                seen_ids.add(market_id)
            candidates.append({"event": event, "market": market})

    news_item = {
        "id": topic.get("topic_key", ""),
        "title": topic.get("topic_label", ""),
        "headlines": [topic.get("topic_label", "")],
    }

    markets: list[dict] = []
    for cand in candidates:
        event = cand["event"]
        m = cand["market"]
        try:
            is_relevant_verdict, reason = veto_check(news_item, event)
        except Exception as exc:
            log.warning("_query_by_market_terms: veto_check failed for event %s: %s",
                        getattr(event, "event_id", "?"), exc)
            is_relevant_verdict, reason = False, f"veto call failed: {exc}"
        if not is_relevant_verdict:
            log.info("_query_by_market_terms: vetoed event %s (%s)", getattr(event, "event_id", "?"), reason)
            continue

        prob_now = m.prob_now
        prob_7d = getattr(m, "prob_7d_ago", None)
        delta_7d = round(prob_now - prob_7d, 4) if (prob_7d is not None and prob_7d > 0.0) else None
        markets.append({
            "title": getattr(event, "event_title", ""),
            "url": getattr(m, "url", ""),
            "prob_now": round(prob_now, 4),
            "delta_7d": delta_7d,
            "volume_usd": getattr(event, "volume_usd", None),
            "outcome_label": getattr(m, "outcome_label", "") or "",
        })

    markets.sort(key=lambda x: x["prob_now"], reverse=True)
    markets = markets[:3]
    for m in markets:
        m["relevance"] = classify_relevance(m.get("title", ""))
        m["note"] = build_note(m)
    return markets


# ---------------------------------------------------------------------------
# Pool: top-volume Tier B candidates, enriched with 7d movers
# ---------------------------------------------------------------------------

_POOL_PREFETCH = 10   # candidates to enrich before final mover sort
MOVER_MIN = 0.0       # abs(delta_7d) floor; set to 0.03 to filter flat markets


def _fetch_7d(candidate: dict, adapter: Any) -> dict:
    """Enrich one pool candidate with delta_7d via public_search.

    Searches by slug (from URL) to get oneWeekPriceChange — same field the
    search path uses. Matches by event title AND outcome_label; a baseline
    from a different outcome must never be borrowed (it computes a delta for
    the wrong side of the market). On any failure, or if the matching outcome
    has no baseline, returns candidate unchanged so delta stays None (treated
    as 0 in the mover sort).
    """
    url = candidate.get("url", "")
    slug = url.rstrip("/").rsplit("/", 1)[-1] if url else ""
    title = candidate.get("title", "")
    outcome_label = candidate.get("outcome_label", "")
    prob_now = candidate.get("prob_now", 0.0)

    query = slug.replace("-", " ") if slug else title
    if not query:
        return candidate

    try:
        events = adapter.public_search(query, limit=5)
        for event in events:
            if event.event_title != title:
                continue
            p7d = None
            for m in event.markets:
                if m.outcome_label == outcome_label and m.prob_7d_ago is not None:
                    p7d = m.prob_7d_ago
                    break
            if p7d is not None and p7d > 0.0:
                return {**candidate, "delta_7d": round(prob_now - p7d, 4)}
    except Exception as exc:
        log.debug("_fetch_7d: public_search failed for '%s': %s", title, exc)

    return candidate


def _build_pool(
    adapter: Any,
    hits_urls: set,
    limit: int = 5,
    min_volume: float = 10_000.0,
) -> list[dict]:
    """Top-volume open markets → event dedup → 7d enrichment → mover sort."""
    try:
        events = adapter.top_by_volume(limit=50)
        if not isinstance(events, list):
            return []
    except Exception as exc:
        log.warning("_build_pool: top_by_volume failed: %s", exc)
        return []

    candidates = []
    for event in events:
        vol = getattr(event, "volume_usd", None) or 0.0
        if vol < min_volume:
            continue

        best_p: float = -1.0
        best_m = None
        for m in getattr(event, "markets", []):
            p = getattr(m, "prob_now", None)
            if p is None:
                continue
            p = float(p)
            if not (0.01 < p < 0.99):
                continue
            url = getattr(m, "url", "") or ""
            if not url:
                continue
            if url in hits_urls:
                continue
            if p > best_p:
                best_p = p
                best_m = m

        if best_m is None:
            continue

        url = getattr(best_m, "url", "")
        prob_7d = getattr(best_m, "prob_7d_ago", None)
        delta = round(best_p - float(prob_7d), 4) if (prob_7d is not None and float(prob_7d) > 0.0) else None
        candidates.append({
            "title": getattr(event, "event_title", ""),
            "url": url,
            "prob_now": round(best_p, 4),
            "delta_7d": delta,
            "volume_usd": vol,
            "outcome_label": getattr(best_m, "outcome_label", "") or "",
        })

    # Pre-sort by volume; take top-N for 7d enrichment
    candidates.sort(key=lambda x: x["volume_usd"], reverse=True)
    top_n = candidates[:_POOL_PREFETCH]
    enriched = [_fetch_7d(c, adapter) for c in top_n]

    if MOVER_MIN > 0.0:
        enriched = [c for c in enriched if abs(c.get("delta_7d") or 0.0) >= MOVER_MIN]

    enriched.sort(key=lambda x: abs(x.get("delta_7d") or 0.0), reverse=True)
    return annotate_pool(enriched[:limit])


# ---------------------------------------------------------------------------
# Top volume: top-N open markets by volume_usd, event dedup only (no
# hits_urls exclusion, no min_volume floor, no 7d re-fetch — independent of pool)
# ---------------------------------------------------------------------------

def _build_top_volume(adapter: Any, limit: int = 10) -> list[dict]:
    """Top-volume open markets → event dedup → volume desc, capped at limit.

    Independent of _build_pool: no hits_urls exclusion, no min_volume filter,
    no separate 7d-delta fetch (delta_7d comes straight from prob_7d_ago on
    the same market chosen as the event's representative).
    """
    try:
        events = adapter.top_by_volume(limit=50)
        if not isinstance(events, list):
            return []
    except Exception as exc:
        log.warning("_build_top_volume: top_by_volume failed: %s", exc)
        return []

    candidates = []
    for event in events:
        vol = getattr(event, "volume_usd", None) or 0.0

        best_p: float = -1.0
        best_m = None
        for m in getattr(event, "markets", []):
            p = getattr(m, "prob_now", None)
            if p is None:
                continue
            p = float(p)
            if not (0.01 < p < 0.99):
                continue
            url = getattr(m, "url", "") or ""
            if not url:
                continue
            if p > best_p:
                best_p = p
                best_m = m

        if best_m is None:
            continue

        url = getattr(best_m, "url", "")
        prob_7d = getattr(best_m, "prob_7d_ago", None)
        delta = round(best_p - float(prob_7d), 4) if (prob_7d is not None and float(prob_7d) > 0.0) else None
        candidates.append({
            "title": getattr(event, "event_title", ""),
            "url": url,
            "prob_now": round(best_p, 4),
            "delta_7d": delta,
            "volume_usd": vol,
            "outcome_label": getattr(best_m, "outcome_label", "") or "",
        })

    candidates.sort(key=lambda x: x["volume_usd"], reverse=True)
    return candidates[:limit]


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def scan(
    watchlist: list[dict] | None = None,
    adapter: Any | None = None,
    out_path: Path | None = None,
    notion_token: str | None = None,
) -> dict:
    """Scan watchlist topics against Polymarket; return do_hits dict.

    Args:
        watchlist: pre-loaded topic list; if None, loads from Notion or sample.json.
        adapter: Polymarket adapter; if None, instantiates PolymarketAdapter.
        out_path: if set, writes do_hits.json atomically to this path.
        notion_token: when set, Notion is authoritative; on failure returns
                      meta.status='error' + empty hits and skips the write.
    """
    if watchlist is None:
        token = notion_token or os.environ.get("NOTION_TOKEN")
        if token:
            watchlist, notion_failed = _try_load_notion(token)
            if notion_failed:
                return {
                    "meta": {
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "date_syd": datetime.now(ZoneInfo("Australia/Sydney")).strftime("%Y-%m-%d"),
                        "status": "error",
                        "topics_queried": 0,
                        "topics_with_hits": 0,
                    },
                    "hits": {},
                }
            if not watchlist:
                watchlist = _load_sample()
        else:
            watchlist = _load_sample()

    if adapter is None:
        from core.adapter_polymarket import PolymarketAdapter
        adapter = PolymarketAdapter()

    hits: dict[str, list[dict]] = {}
    errors = 0

    for topic in watchlist:
        topic_key = topic.get("topic_key", "")
        if not topic_key:
            continue
        try:
            markets = _query_topic(topic, adapter)
            if markets:
                hits[topic_key] = markets
        except Exception as exc:
            log.warning("scan: error on topic %s: %s", topic_key, exc)
            errors += 1

    hits_urls: set = {m["url"] for markets in hits.values() for m in markets if m.get("url")}
    pool = _build_pool(adapter, hits_urls)
    top_volume = _build_top_volume(adapter)

    status = "ok" if errors == 0 else "partial"
    date_syd = datetime.now(ZoneInfo("Australia/Sydney")).strftime("%Y-%m-%d")

    if out_path is not None:
        prev, prev_date = load_prev_history(Path(out_path))
        for markets in hits.values():
            attach_history(markets, prev, date_syd, prev_date)
        attach_history(pool, prev, date_syd, prev_date)

    result = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "date_syd": date_syd,
            "status": status,
            "topics_queried": len(watchlist),
            "topics_with_hits": len(hits),
        },
        "hits": hits,
        "pool": pool,
        "top_volume": top_volume,
    }

    if out_path is not None:
        write_do_hits(Path(out_path), result)

    return result


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def write_do_hits(path: Path, data: dict) -> None:
    """Write do_hits dict to path atomically via tmp + os.replace."""
    import os as _os
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _os.replace(tmp, path)
    log.info("do_hits.json written to %s (status=%s)", path, data.get("meta", {}).get("status"))
