"""tests/test_reality_check.py — DO v2 core: hard filters, caps, dedup, schema v2.

Amended design law under test: code retrieves and hard-filters candidates; AI may
only veto; code enforces all caps and maths. This file covers the code half.
"""
from __future__ import annotations

import pytest

from core.adapter_polymarket import _parse_event_public_search
from core.models import Event, Market
from core.reality_check import (
    RealityCheckConfig,
    RealityCheckHit,
    TTLCache,
    cap_markets_per_edition,
    cap_markets_per_news_item,
    dedup_events,
    hard_filter_events,
    search_query_variants,
)


# ---------------------------------------------------------------------------
# Adapter field capture (active/closed/liquidity/volume24hr) — required for
# hard filters to have anything to filter on.
# ---------------------------------------------------------------------------

def _raw_event(**overrides):
    base = {
        "id": "681382",
        "title": "US reissues Iran oil sanction relief?",
        "slug": "us-reissues-iran-oil",
        "active": True,
        "closed": False,
        "liquidity": 14405.1336,
        "volume": 1683.37,
        "volume24hr": 1408.21,
        "endDate": "2026-08-31T23:59:00Z",
        "tags": [],
        "markets": [],
    }
    base.update(overrides)
    return base


def test_parse_event_public_search_captures_active_closed_liquidity():
    ev = _parse_event_public_search(_raw_event())
    assert ev is not None
    assert ev.active is True
    assert ev.closed is False
    assert ev.liquidity_usd == pytest.approx(14405.1336)
    assert ev.volume_24hr_usd == pytest.approx(1408.21)


def test_parse_event_public_search_closed_market():
    ev = _parse_event_public_search(_raw_event(active=False, closed=True))
    assert ev.active is False
    assert ev.closed is True


# ---------------------------------------------------------------------------
# hard_filter_events — active/closed/volume/liquidity floor/endDate horizon
# ---------------------------------------------------------------------------

def _event(event_id="e1", active=True, closed=False, volume=20_000.0,
           liquidity=10_000.0, end_date="2026-08-01", markets=None):
    return Event(
        event_id=event_id,
        event_title=f"Event {event_id}",
        markets=markets or [Market(market_id=f"m-{event_id}", outcome_label="Yes",
                                    url="https://polymarket.com/x", prob_now=0.4)],
        volume_usd=volume,
        end_date=end_date,
        active=active,
        closed=closed,
        liquidity_usd=liquidity,
    )


def test_hard_filter_drops_inactive_events():
    events = [_event("e1", active=False)]
    result = hard_filter_events(events, config=RealityCheckConfig(), today="2026-07-11")
    assert result == []


def test_hard_filter_drops_closed_events():
    events = [_event("e1", closed=True)]
    result = hard_filter_events(events, config=RealityCheckConfig(), today="2026-07-11")
    assert result == []


def test_hard_filter_drops_below_volume_floor():
    events = [_event("e1", volume=100.0)]
    result = hard_filter_events(events, config=RealityCheckConfig(min_volume_usd=10_000.0), today="2026-07-11")
    assert result == []


def test_hard_filter_drops_below_liquidity_floor():
    events = [_event("e1", liquidity=50.0)]
    result = hard_filter_events(events, config=RealityCheckConfig(min_liquidity_usd=1_000.0), today="2026-07-11")
    assert result == []


def test_hard_filter_drops_beyond_horizon():
    events = [_event("e1", end_date="2027-12-31")]
    result = hard_filter_events(events, config=RealityCheckConfig(max_days_out=90), today="2026-07-11")
    assert result == []


def test_hard_filter_keeps_event_within_all_thresholds():
    events = [_event("e1", volume=20_000.0, liquidity=10_000.0, end_date="2026-08-01")]
    result = hard_filter_events(events, config=RealityCheckConfig(), today="2026-07-11")
    assert len(result) == 1
    assert result[0].event_id == "e1"


# ---------------------------------------------------------------------------
# dedup_events — dedup across query variants (same news cluster, 2-3 queries)
# ---------------------------------------------------------------------------

def test_dedup_events_across_query_variants():
    variant_a = [_event("e1"), _event("e2")]
    variant_b = [_event("e2"), _event("e3")]
    result = dedup_events([variant_a, variant_b])
    ids = sorted(e.event_id for e in result)
    assert ids == ["e1", "e2", "e3"]


def test_dedup_events_empty_input():
    assert dedup_events([]) == []


# ---------------------------------------------------------------------------
# Caps — max markets per news item, max lookups per edition
# ---------------------------------------------------------------------------

def test_cap_markets_per_news_item_default_two():
    events = [_event("e1"), _event("e2"), _event("e3")]
    result = cap_markets_per_news_item(events, config=RealityCheckConfig())
    assert len(result) == 2


def test_cap_markets_per_news_item_configurable():
    events = [_event("e1"), _event("e2"), _event("e3")]
    result = cap_markets_per_news_item(events, config=RealityCheckConfig(max_markets_per_news_item=1))
    assert len(result) == 1


def test_cap_markets_per_edition_default_eight():
    # 4 news items x 3 candidate events each = 12 raw lookups; capped to 8 total.
    per_item = [[_event(f"e{i}-{j}") for j in range(3)] for i in range(4)]
    result = cap_markets_per_edition(per_item, config=RealityCheckConfig())
    total = sum(len(r) for r in result)
    assert total == 8


# ---------------------------------------------------------------------------
# Schema v2 — RealityCheckHit MUST carry source_news_id (no orphan markets)
# ---------------------------------------------------------------------------

def test_reality_check_hit_requires_source_news_id():
    with pytest.raises(TypeError):
        RealityCheckHit(  # type: ignore[call-arg]
            event_id="e1", event_title="t", market_id="m1", outcome_label="Yes",
            url="https://x", prob_now=0.4, delta_24h_pp=None, delta_7d_pp=None,
            volume_usd=20_000.0, liquidity_usd=10_000.0, end_date="2026-08-01",
        )


# ---------------------------------------------------------------------------
# TTLCache — in-process, 30s+ TTL per plan (DO-V2-2 step 2)
# ---------------------------------------------------------------------------

def test_ttl_cache_hit_before_expiry():
    clock = {"t": 0.0}
    cache = TTLCache(ttl_seconds=30.0, clock=lambda: clock["t"])
    cache.set("iran oil", ["event-a"])
    clock["t"] = 29.9
    assert cache.get("iran oil") == ["event-a"]


def test_ttl_cache_miss_after_expiry():
    clock = {"t": 0.0}
    cache = TTLCache(ttl_seconds=30.0, clock=lambda: clock["t"])
    cache.set("iran oil", ["event-a"])
    clock["t"] = 30.1
    assert cache.get("iran oil") is None


def test_ttl_cache_miss_for_unknown_key():
    cache = TTLCache(ttl_seconds=30.0)
    assert cache.get("never set") is None


# ---------------------------------------------------------------------------
# search_query_variants — one call per query variant, cached, deduped by caller
# ---------------------------------------------------------------------------

class _FakeAdapter:
    def __init__(self, responses: dict[str, list]):
        self._responses = responses
        self.calls: list[str] = []

    def public_search(self, query: str, limit: int = 10):
        self.calls.append(query)
        return self._responses.get(query, [])


def test_search_query_variants_calls_adapter_once_per_query():
    adapter = _FakeAdapter({"Strait of Hormuz": [_event("e1")], "Iran oil": [_event("e2")]})
    cache = TTLCache(ttl_seconds=30.0)
    results = search_query_variants(adapter, ["Strait of Hormuz", "Iran oil"], cache)
    assert len(results) == 2
    assert [e.event_id for e in results[0]] == ["e1"]
    assert [e.event_id for e in results[1]] == ["e2"]
    assert adapter.calls == ["Strait of Hormuz", "Iran oil"]


def test_search_query_variants_uses_cache_on_repeat_query():
    adapter = _FakeAdapter({"Iran oil": [_event("e2")]})
    cache = TTLCache(ttl_seconds=30.0)
    search_query_variants(adapter, ["Iran oil"], cache)
    search_query_variants(adapter, ["Iran oil"], cache)
    assert adapter.calls == ["Iran oil"], "second call must be served from cache, not re-fetched"


def test_reality_check_hit_round_trip():
    hit = RealityCheckHit(
        source_news_id="news-42", event_id="e1", event_title="t", market_id="m1",
        outcome_label="Yes", url="https://x", prob_now=0.4, delta_24h_pp=1.2,
        delta_7d_pp=-3.4, volume_usd=20_000.0, liquidity_usd=10_000.0,
        end_date="2026-08-01",
    )
    d = hit.to_dict()
    assert d["source_news_id"] == "news-42"
    back = RealityCheckHit.from_dict(d)
    assert back == hit


def test_reality_check_hit_phase3_fields_round_trip():
    """so_what/then_what/vetoed/veto_reason (dk-do-v2-PLAN.md Phase 3) round-trip,
    and default to None/False when absent (backward compat with pre-Phase-3 data)."""
    hit = RealityCheckHit(
        source_news_id="news-42", event_id="e1", event_title="t", market_id="m1",
        outcome_label="Yes", url="https://x", prob_now=0.4, delta_24h_pp=1.2,
        delta_7d_pp=-3.4, volume_usd=20_000.0, liquidity_usd=10_000.0,
        end_date="2026-08-01", so_what="It could ease supply.", then_what="Rates may follow.",
        vetoed=True, veto_reason="coincidental keyword match",
    )
    d = hit.to_dict()
    assert d["so_what"] == "It could ease supply."
    assert d["then_what"] == "Rates may follow."
    assert d["vetoed"] is True
    assert d["veto_reason"] == "coincidental keyword match"
    back = RealityCheckHit.from_dict(d)
    assert back == hit

    legacy = {
        "source_news_id": "news-1", "event_id": "e1", "event_title": "t", "market_id": "m1",
        "outcome_label": "Yes", "url": "https://x", "prob_now": 0.4, "delta_24h_pp": None,
        "delta_7d_pp": None, "volume_usd": 20_000.0, "liquidity_usd": 10_000.0,
        "end_date": "2026-08-01",
    }
    back_legacy = RealityCheckHit.from_dict(legacy)
    assert back_legacy.so_what is None
    assert back_legacy.then_what is None
    assert back_legacy.vetoed is False
    assert back_legacy.veto_reason is None
