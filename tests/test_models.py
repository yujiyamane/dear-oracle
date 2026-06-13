"""Sprint 0 — test_models.py
Tests MUST be written before implementation. Each test here corresponds to
the TDD.md Sprint 0 spec.
"""
import json
import dataclasses
import pytest
from core.models import (
    Tag,
    PricePoint,
    Resolution,
    Market,
    Event,
    OutcomeSignal,
    SignalEvent,
    CoverageTransition,
    MarketSignals,
)


# ---------------------------------------------------------------------------
# test_dataclass_construct
# ---------------------------------------------------------------------------

def test_tag_construct():
    t = Tag(slug="world-cup", tag_id="204")
    assert t.slug == "world-cup"
    assert t.tag_id == "204"


def test_price_point_construct():
    pp = PricePoint(timestamp="2026-06-13T05:00:00+10:00", price=0.24)
    assert pp.timestamp == "2026-06-13T05:00:00+10:00"
    assert pp.price == 0.24


def test_resolution_construct():
    r = Resolution(market_id="0xabc", resolved=True, outcome_label="Yes", winning_prob=1.0)
    assert r.market_id == "0xabc"
    assert r.resolved is True
    assert r.outcome_label == "Yes"
    assert r.winning_prob == 1.0


def test_resolution_unresolved():
    r = Resolution(market_id="0xdef", resolved=False)
    assert r.resolved is False
    assert r.outcome_label is None
    assert r.winning_prob is None


def test_market_construct():
    m = Market(
        market_id="0xabc",
        outcome_label="Yes",
        url="https://polymarket.com/event/test",
        prob_now=0.24,
        prob_24h_ago=0.18,
        prob_7d_ago=None,
        delta_24h_pp=6.0,
        delta_7d_pp=None,
    )
    assert m.market_id == "0xabc"
    assert m.prob_now == 0.24
    assert m.prob_7d_ago is None
    assert m.delta_7d_pp is None


def test_event_construct():
    tag = Tag(slug="ai", tag_id="305")
    market = Market(
        market_id="0xabc",
        outcome_label="Yes",
        url="https://polymarket.com/event/agi",
        prob_now=0.24,
    )
    e = Event(
        event_id="16085",
        event_title="Will a frontier lab declare AGI by end of 2027?",
        markets=[market],
        volume_usd=450000.0,
        end_date="2027-12-31",
        tags=[tag],
    )
    assert e.event_id == "16085"
    assert len(e.markets) == 1
    assert len(e.tags) == 1


# ---------------------------------------------------------------------------
# test_nullability
# ---------------------------------------------------------------------------

def test_market_nullability_prob_7d():
    """prob_7d_ago=None is allowed; delta_7d_pp must also be None."""
    m = Market(
        market_id="0x001",
        outcome_label="Yes",
        url="https://polymarket.com/event/test",
        prob_now=0.30,
        prob_7d_ago=None,
        delta_7d_pp=None,
    )
    assert m.prob_7d_ago is None
    assert m.delta_7d_pp is None


def test_market_nullability_prob_24h():
    """prob_24h_ago=None is allowed on day 1; delta_24h_pp then None."""
    m = Market(
        market_id="0x002",
        outcome_label="Yes",
        url="https://polymarket.com/event/test",
        prob_now=0.50,
        prob_24h_ago=None,
        delta_24h_pp=None,
    )
    assert m.prob_24h_ago is None
    assert m.delta_24h_pp is None


def test_event_optional_fields():
    m = Market(market_id="0x003", outcome_label="No", url="https://x", prob_now=0.10)
    e = Event(event_id="999", event_title="Test event", markets=[m])
    assert e.volume_usd is None
    assert e.end_date is None
    assert e.tags == []


# ---------------------------------------------------------------------------
# test_signals_roundtrip
# ---------------------------------------------------------------------------

INTERFACES_EXAMPLE = {
    "schema_version": 1,
    "source": "polymarket-gamma",
    "generated_at": "2026-06-13T05:00:00+10:00",
    "coverage_transitions": [
        {"interest": "surfing", "from": "dormant", "to": "active"}
    ],
    "signals": [
        {
            "event_id": "16085",
            "event_title": "Will a frontier lab declare AGI by end of 2027?",
            "interest_tag": "ai",
            "outcomes": [
                {
                    "outcome_label": "Yes",
                    "market_id": "0xabc",
                    "url": "https://polymarket.com/event/...",
                    "prob_now": 0.24,
                    "prob_24h_ago": 0.18,
                    "prob_7d_ago": None,
                    "delta_24h_pp": 6.0,
                    "delta_7d_pp": None,
                }
            ],
            "threshold_pp": 5.0,
            "threshold_exceeded": True,
            "threshold_triggered_by": "delta_24h",
            "volume_usd": 450000,
            "end_date": "2027-12-31",
        }
    ],
}


def test_signals_roundtrip():
    """Deserialise the INTERFACES §2 example, serialise back, assert equality.
    Forward-compat: an unknown extra field in the input is silently ignored.
    """
    example_with_extra = json.loads(json.dumps(INTERFACES_EXAMPLE))
    # inject an unknown field for forward-compat check
    example_with_extra["signals"][0]["unknown_future_field"] = "ignored"
    example_with_extra["signals"][0]["outcomes"][0]["another_future_field"] = 99

    ms = MarketSignals.from_dict(example_with_extra)

    assert ms.schema_version == 1
    assert ms.source == "polymarket-gamma"
    assert len(ms.coverage_transitions) == 1
    ct = ms.coverage_transitions[0]
    assert ct.interest == "surfing"
    assert ct.from_status == "dormant"
    assert ct.to_status == "active"

    assert len(ms.signals) == 1
    sig = ms.signals[0]
    assert sig.event_id == "16085"
    assert sig.interest_tag == "ai"
    assert sig.threshold_exceeded is True
    assert sig.threshold_triggered_by == "delta_24h"

    assert len(sig.outcomes) == 1
    o = sig.outcomes[0]
    assert o.outcome_label == "Yes"
    assert o.market_id == "0xabc"
    assert o.prob_now == 0.24
    assert o.prob_24h_ago == 0.18
    assert o.prob_7d_ago is None
    assert o.delta_24h_pp == 6.0
    assert o.delta_7d_pp is None

    # round-trip serialisation
    as_dict = ms.to_dict()
    assert as_dict["schema_version"] == INTERFACES_EXAMPLE["schema_version"]
    assert as_dict["source"] == INTERFACES_EXAMPLE["source"]
    assert as_dict["coverage_transitions"][0]["from"] == "dormant"
    assert as_dict["coverage_transitions"][0]["to"] == "active"
    assert as_dict["signals"][0]["outcomes"][0]["prob_7d_ago"] is None
    assert as_dict["signals"][0]["outcomes"][0]["delta_7d_pp"] is None

    # serialised JSON should parse back cleanly
    json_str = json.dumps(as_dict)
    reloaded = json.loads(json_str)
    assert reloaded["signals"][0]["event_id"] == "16085"
