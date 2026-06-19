"""core/scan.py — DK Watchlist → Polymarket scan → do_hits.json.

Reads the DK Watchlist (from Notion if NOTION_TOKEN is set, else from data/sample.json),
queries Polymarket for each active topic, and writes do_hits.json atomically to the
given output path so that DK (GAS) can blend market data into topic cards.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SAMPLE_JSON = PROJECT_ROOT / "data" / "sample.json"

# Notion API base
_NOTION_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"

# DK Watchlist DB page ID (no hyphens) — same constant as 02_dear_keyperson.js
DK_WATCHLIST_DB_ID = "5b71f847e9d44621b47bc71d1a7ad6e9"


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


def _load_sample() -> list[dict]:
    data = json.loads(_SAMPLE_JSON.read_text(encoding="utf-8"))
    return data.get("topics", [])


def _fetch_notion_watchlist(token: str) -> list[dict]:
    """Fetch active topics from Notion 08a Watchlist DB."""
    url = f"{_NOTION_BASE}/databases/{DK_WATCHLIST_DB_ID}/query"
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
# Polymarket query
# ---------------------------------------------------------------------------

def _build_query(topic: dict) -> str:
    keywords = topic.get("keywords", "")
    parts = [k.strip() for k in keywords.split(";") if k.strip()]
    return " OR ".join(parts[:3]) if parts else topic.get("topic_label", "")


def _query_topic(topic: dict, adapter: Any) -> list[dict]:
    """Return list of market dicts for the given topic, or [] if none found."""
    query = _build_query(topic)
    if not query:
        return []

    try:
        events = adapter.search(query, limit=5)
    except Exception as exc:
        log.warning("Polymarket search failed for topic %s: %s", topic.get("topic_key"), exc)
        return []

    markets = []
    for event in events:
        for m in getattr(event, "markets", []):
            prob_now = getattr(m, "prob_now", None)
            prob_7d = getattr(m, "prob_7d_ago", None)
            if prob_now is None:
                continue

            delta_7d = None
            if prob_7d is not None:
                delta_7d = round(prob_now - prob_7d, 4)

            markets.append({
                "title": getattr(event, "event_title", ""),
                "url": getattr(m, "url", ""),
                "prob_now": round(prob_now, 4),
                "delta_7d": delta_7d,
                "volume_usd": getattr(event, "volume_usd", None),
            })

    return markets[:3]


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
        watchlist: pre-loaded topic list; if None, calls load_watchlist().
        adapter: Polymarket adapter; if None, instantiates PolymarketAdapter.
        out_path: if set, writes do_hits.json atomically to this path.
        notion_token: passed to load_watchlist if watchlist is None.
    """
    if watchlist is None:
        watchlist = load_watchlist(notion_token)

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

    status = "ok" if errors == 0 else "partial"
    result = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "topics_queried": len(watchlist),
            "topics_with_hits": len(hits),
        },
        "hits": hits,
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
