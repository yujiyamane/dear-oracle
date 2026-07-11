"""tests/test_reality_check_pipeline.py — core/reality_check_pipeline.py orchestrator.

Composes extraction -> search -> hard filters -> per-item cap -> veto gate ->
edition cap -> synthesis, per dk-do-v2-PLAN.md DO-V2-2/DO-V2-4. No real
network/subprocess calls — fake adapter + fake call_claude injected
throughout.
"""
from __future__ import annotations

import json

from core.models import Event, Market
from core.reality_check import RealityCheckConfig
from core.reality_check_pipeline import run_reality_check


def _event(event_id, volume=20_000.0, liquidity=10_000.0, end_date="2026-08-01"):
    return Event(
        event_id=event_id,
        event_title=f"Market about {event_id}",
        markets=[Market(market_id=f"m-{event_id}", outcome_label="Yes",
                         url=f"https://polymarket.com/{event_id}", prob_now=0.3,
                         delta_24h_pp=1.0, delta_7d_pp=2.0)],
        volume_usd=volume,
        liquidity_usd=liquidity,
        end_date=end_date,
        active=True,
        closed=False,
    )


class _FakeAdapter:
    """query -> list[Event] map. Records calls for inspection."""

    def __init__(self, responses: dict[str, list[Event]]):
        self._responses = responses
        self.calls: list[str] = []

    def public_search(self, query: str, limit: int = 10):
        self.calls.append(query)
        return self._responses.get(query, [])


def _extraction_response(queries: list[str]) -> str:
    return json.dumps(queries)


def _veto_response(relevant: bool, reason: str = "verdict") -> str:
    return json.dumps({"relevant": relevant, "reason": reason})


def _synthesis_response(so_what: str = "It could happen.", then_what: str = "Then this follows.") -> str:
    return json.dumps({"so_what": so_what, "then_what": then_what})


def _make_call_claude(extraction_map: dict[str, list[str]], veto_map: dict[str, tuple[bool, str]],
                       synth_response: tuple[str, str] | None = ("It could happen.", "Then this follows.")):
    """Dispatches on distinctive prompt substrings written by each module."""

    def _call(prompt: str, model: str) -> str:
        if "prediction-market search endpoint" in prompt:
            for title_fragment, queries in extraction_map.items():
                if title_fragment in prompt:
                    return _extraction_response(queries)
            return _extraction_response([])
        if "relevance gate between a news item" in prompt:
            for event_id, (relevant, reason) in veto_map.items():
                if event_id in prompt:
                    return _veto_response(relevant, reason)
            return _veto_response(False, "no match configured")
        if "two-sentence consequence chain" in prompt:
            if synth_response is None:
                return "not json"
            return _synthesis_response(*synth_response)
        return ""

    return _call


def test_run_reality_check_happy_path():
    news_items = [
        {"id": "news-1", "title": "Iran-US tension escalates", "headlines": ["h1"]},
        {"id": "news-2", "title": "China-Taiwan drills continue", "headlines": ["h2"]},
    ]
    adapter = _FakeAdapter({
        "q1": [_event("e1")],
        "q2": [_event("e2")],
    })
    extraction_map = {"Iran-US tension escalates": ["q1"], "China-Taiwan drills continue": ["q2"]}
    veto_map = {"e1": (True, "same event"), "e2": (False, "coincidental match")}
    call_claude = _make_call_claude(extraction_map, veto_map)

    result = run_reality_check(news_items, adapter=adapter, call_claude=call_claude, today="2026-07-11")

    assert result["schema_version"] == 2
    hits_v2 = result["hits_v2"]
    assert "news-1" in hits_v2
    assert len(hits_v2["news-1"]) == 1
    assert hits_v2["news-1"][0]["event_id"] == "e1"
    assert hits_v2["news-1"][0]["so_what"] == "It could happen."
    assert hits_v2["news-1"][0]["then_what"] == "Then this follows."
    # news-2's only candidate was vetoed -> hidden silently (OQ-8)
    assert "news-2" not in hits_v2


def test_run_reality_check_per_item_cap_trims():
    news_items = [{"id": "news-1", "title": "Big story", "headlines": ["h1"]}]
    adapter = _FakeAdapter({
        "q1": [_event("e1", volume=15_000.0), _event("e2", volume=50_000.0), _event("e3", volume=90_000.0)],
    })
    extraction_map = {"Big story": ["q1"]}
    veto_map = {"e1": (True, "ok"), "e2": (True, "ok"), "e3": (True, "ok")}
    call_claude = _make_call_claude(extraction_map, veto_map)

    config = RealityCheckConfig(max_markets_per_news_item=2, max_markets_per_edition=8)
    result = run_reality_check(news_items, adapter=adapter, config=config, call_claude=call_claude, today="2026-07-11")

    hits = result["hits_v2"]["news-1"]
    assert len(hits) == 2
    # highest-volume events kept (cap_markets_per_news_item ordering)
    ids = {h["event_id"] for h in hits}
    assert ids == {"e2", "e3"}


def test_run_reality_check_edition_cap_trims():
    news_items = [
        {"id": f"news-{i}", "title": f"story {i}", "headlines": []} for i in range(5)
    ]
    responses = {f"q{i}": [_event(f"e{i}")] for i in range(5)}
    adapter = _FakeAdapter(responses)
    extraction_map = {f"story {i}": [f"q{i}"] for i in range(5)}
    veto_map = {f"e{i}": (True, "ok") for i in range(5)}
    call_claude = _make_call_claude(extraction_map, veto_map)

    config = RealityCheckConfig(max_markets_per_edition=3)
    result = run_reality_check(news_items, adapter=adapter, config=config, call_claude=call_claude, today="2026-07-11")

    total_hits = sum(len(v) for v in result["hits_v2"].values())
    assert total_hits == 3


def test_run_reality_check_empty_news_items():
    adapter = _FakeAdapter({})
    call_claude = _make_call_claude({}, {})
    result = run_reality_check([], adapter=adapter, call_claude=call_claude, today="2026-07-11")
    assert result["hits_v2"] == {}


def test_run_reality_check_zero_search_results():
    news_items = [{"id": "news-1", "title": "No markets exist for this", "headlines": []}]
    adapter = _FakeAdapter({})  # every query returns []
    extraction_map = {"No markets exist for this": ["q1"]}
    call_claude = _make_call_claude(extraction_map, {})
    result = run_reality_check(news_items, adapter=adapter, call_claude=call_claude, today="2026-07-11")
    assert result["hits_v2"] == {}


def test_run_reality_check_all_candidates_vetoed_for_one_item():
    news_items = [
        {"id": "news-1", "title": "Story with markets", "headlines": []},
        {"id": "news-2", "title": "Story with all vetoed", "headlines": []},
    ]
    adapter = _FakeAdapter({
        "q1": [_event("e1")],
        "q2": [_event("e2"), _event("e3")],
    })
    extraction_map = {"Story with markets": ["q1"], "Story with all vetoed": ["q2"]}
    veto_map = {"e1": (True, "ok"), "e2": (False, "no"), "e3": (False, "no")}
    call_claude = _make_call_claude(extraction_map, veto_map)

    result = run_reality_check(news_items, adapter=adapter, call_claude=call_claude, today="2026-07-11")

    assert "news-1" in result["hits_v2"]
    assert "news-2" not in result["hits_v2"]


def test_run_reality_check_writes_output_file(tmp_path):
    news_items = [{"id": "news-1", "title": "Story", "headlines": []}]
    adapter = _FakeAdapter({"q1": [_event("e1")]})
    extraction_map = {"Story": ["q1"]}
    veto_map = {"e1": (True, "ok")}
    call_claude = _make_call_claude(extraction_map, veto_map)

    out_path = tmp_path / "do_hits_v2.json"
    result = run_reality_check(
        news_items, adapter=adapter, call_claude=call_claude, today="2026-07-11", out_path=out_path
    )
    assert out_path.exists()
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk == result
