"""core/reality_check_pipeline.py — DO v2 orchestrator (dk-do-v2-PLAN.md DO-V2-2/3/4).

Composes the whole reality-check chain per news item, in cost-bounded order:

    for each news_item:
        queries  = extract_query_variants(news_item)               # Haiku
        events   = search_query_variants(adapter, queries, cache)   # code, TTL-cached
        filtered = hard_filter_events(dedup_events(events), config, today)
        capped   = cap_markets_per_news_item(filtered, config)      # code
        survivors = [e for e in capped if veto_check(news_item, e)[0]]   # Haiku, bounded by per-item cap
    final = cap_markets_per_edition(per_news_item_survivors, config) # code — Sonnet-call budget gate
    for each surviving hit:
        hit.so_what, hit.then_what = synthesize_so_what_then_what(...)  # Sonnet, bounded by edition cap

Design law preserved throughout: code retrieves/hard-filters/caps; AI only
vetoes or writes prose; AI never adds a candidate. News items whose every
candidate is vetoed (or which have zero search hits) end up with zero hits —
this is expected ("hide silently", dk-do-v2-PLAN.md OQ-8), not an error.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.models import Event, RealityCheckHit
from core.reality_check import (
    RealityCheckConfig,
    TTLCache,
    cap_markets_per_edition,
    cap_markets_per_news_item,
    dedup_events,
    hard_filter_events,
    search_query_variants,
)
from core.extraction import extract_query_variants
from core.veto_gate import veto_check
from core.synthesis import synthesize_so_what_then_what

log = logging.getLogger(__name__)

__all__ = ["run_reality_check"]


def _hit_from_event(source_news_id: str, event: Event) -> RealityCheckHit | None:
    """Build a RealityCheckHit from an Event, choosing its first market as the
    representative outcome. Returns None (skip, log) if the event has no
    markets — this must never crash the pipeline."""
    if not event.markets:
        log.warning("reality_check_pipeline: event %s has no markets — skipped", event.event_id)
        return None
    market = event.markets[0]
    return RealityCheckHit(
        source_news_id=source_news_id,
        event_id=event.event_id,
        event_title=event.event_title,
        market_id=market.market_id,
        outcome_label=market.outcome_label,
        url=market.url,
        prob_now=market.prob_now,
        delta_24h_pp=market.delta_24h_pp,
        delta_7d_pp=market.delta_7d_pp,
        volume_usd=event.volume_usd or 0.0,
        liquidity_usd=event.liquidity_usd or 0.0,
        end_date=event.end_date,
    )


def run_reality_check(
    news_items: list[dict],
    adapter: Any | None = None,
    config: RealityCheckConfig | None = None,
    out_path: Path | None = None,
    call_claude: Callable[[str, str], str] | None = None,
    today: str | None = None,
) -> dict:
    """Run the full DO v2 reality-check chain over a list of DK news items.

    Args:
        news_items: [{"id": str, "title": str, "headlines": list[str]}, ...],
            in DK's edition priority order (cap_markets_per_edition trims from
            the tail, so priority order matters).
        adapter: Polymarket search adapter; defaults to PolymarketAdapter()
            (mirrors core.scan.scan's default-adapter pattern).
        config: RealityCheckConfig; defaults to RealityCheckConfig().
        out_path: if set, writes the result JSON atomically to this path.
        call_claude: injectable (prompt, model) -> str, threaded through
            extraction/veto/synthesis. Defaults to each module's real
            subprocess-based `claude` CLI call.
        today: ISO date string for horizon filtering; defaults to today (UTC).

    Returns: {"schema_version": 2, "generated_at": ..., "hits_v2": {news_id: [hit dict, ...]}}
    """
    if adapter is None:
        from core.adapter_polymarket import PolymarketAdapter
        adapter = PolymarketAdapter()
    if config is None:
        config = RealityCheckConfig()
    if today is None:
        today = date.today().isoformat()

    cache = TTLCache()

    news_ids: list[str] = []
    per_news_item_survivors: list[list[Event]] = []

    for news_item in news_items:
        news_id = news_item.get("id", "")
        news_ids.append(news_id)

        try:
            queries = extract_query_variants(news_item, call_claude=call_claude)
        except Exception as exc:
            log.warning("reality_check_pipeline: extraction failed for %s: %s", news_id, exc)
            queries = []

        if not queries:
            per_news_item_survivors.append([])
            continue

        event_lists = search_query_variants(adapter, queries, cache)
        filtered = hard_filter_events(dedup_events(event_lists), config, today)
        capped = cap_markets_per_news_item(filtered, config)

        survivors: list[Event] = []
        for event in capped:
            try:
                relevant, reason = veto_check(news_item, event, call_claude=call_claude)
            except Exception as exc:
                log.warning("reality_check_pipeline: veto_check failed for %s/%s: %s", news_id, event.event_id, exc)
                relevant, reason = False, f"veto call failed: {exc}"
            if relevant:
                survivors.append(event)
            else:
                log.info("reality_check_pipeline: vetoed %s for news %s (%s)", event.event_id, news_id, reason)

        per_news_item_survivors.append(survivors)

    final = cap_markets_per_edition(per_news_item_survivors, config)

    hits_v2: dict[str, list[dict]] = {}
    for news_item, news_id, events in zip(news_items, news_ids, final):
        if not events:
            continue
        item_hits: list[RealityCheckHit] = []
        for event in events:
            hit = _hit_from_event(news_id, event)
            if hit is None:
                continue
            try:
                so_what, then_what = synthesize_so_what_then_what(news_item, hit, call_claude=call_claude)
            except Exception as exc:
                log.warning("reality_check_pipeline: synthesis failed for %s/%s: %s", news_id, hit.event_id, exc)
                so_what, then_what = "", ""
            hit.so_what = so_what
            hit.then_what = then_what
            item_hits.append(hit)
        if item_hits:
            hits_v2[news_id] = [h.to_dict() for h in item_hits]

    result = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hits_v2": hits_v2,
    }

    if out_path is not None:
        _write_atomic(Path(out_path), result)

    return result


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    import os
    os.replace(tmp, path)
    log.info("do_hits_v2.json written to %s", path)


def _cli() -> int:
    parser = argparse.ArgumentParser(description="DO v2 reality-check pipeline")
    parser.add_argument("--input", required=True, help="Path to news_items.json (list of news item dicts)")
    parser.add_argument("--output", required=True, help="Path to write do_hits_v2.json")
    args = parser.parse_args()

    news_items = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if isinstance(news_items, dict):
        news_items = news_items.get("news_items", [])

    result = run_reality_check(news_items, out_path=Path(args.output))
    print(json.dumps({"hits_v2_count": len(result["hits_v2"])}))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
