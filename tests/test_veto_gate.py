"""tests/test_veto_gate.py — core/veto_gate.py: AI relevance veto gate.

dk-do-v2-PLAN.md DO-V2-2/§4 design law: AI may only VETO an already
hard-filtered candidate — it never manufactures relevance. Guards against the
CHS ("Capitol Hill Seattle News") false-match failure mode: coincidental
keyword/outlet-name overlap must not read as relevance. Any call/parse
failure must fail CLOSED (relevant=False) — never let an ambiguous AI
response let a bad candidate through.
"""
from __future__ import annotations

from core.models import Event, Market
from core.veto_gate import veto_check

NEWS_ITEM = {
    "id": "news-1",
    "title": "Iran-US tension escalates, Strait of Hormuz shipping disrupted",
    "headlines": ["US warns of retaliation after tanker incident"],
}

CANDIDATE = Event(
    event_id="e1",
    event_title="Will Iran close the Strait of Hormuz by August 2026?",
    markets=[Market(market_id="m1", outcome_label="Yes", url="https://x", prob_now=0.2)],
    volume_usd=50_000.0,
)


def _fake_call(response: str):
    def _call(prompt: str, model: str) -> str:
        return response
    return _call


def test_veto_check_relevant_true():
    fake = _fake_call('{"relevant": true, "reason": "same real-world event"}')
    relevant, reason = veto_check(NEWS_ITEM, CANDIDATE, call_claude=fake)
    assert relevant is True
    assert reason == "same real-world event"


def test_veto_check_relevant_false():
    fake = _fake_call('{"relevant": false, "reason": "coincidental keyword overlap only"}')
    relevant, reason = veto_check(NEWS_ITEM, CANDIDATE, call_claude=fake)
    assert relevant is False
    assert reason == "coincidental keyword overlap only"


def test_veto_check_malformed_json_fails_closed():
    fake = _fake_call("not json")
    relevant, reason = veto_check(NEWS_ITEM, CANDIDATE, call_claude=fake)
    assert relevant is False
    assert "veto call failed" in reason


def test_veto_check_exception_fails_closed():
    def _raise(prompt: str, model: str) -> str:
        raise TimeoutError("claude CLI timed out")
    relevant, reason = veto_check(NEWS_ITEM, CANDIDATE, call_claude=_raise)
    assert relevant is False
    assert "veto call failed" in reason


def test_veto_check_markdown_fenced_json():
    fake = _fake_call('```json\n{"relevant": true, "reason": "direct match"}\n```')
    relevant, reason = veto_check(NEWS_ITEM, CANDIDATE, call_claude=fake)
    assert relevant is True
    assert reason == "direct match"


def test_veto_check_missing_relevant_key_fails_closed():
    fake = _fake_call('{"reason": "no verdict field"}')
    relevant, reason = veto_check(NEWS_ITEM, CANDIDATE, call_claude=fake)
    assert relevant is False
    assert "veto call failed" in reason


def test_veto_check_non_bool_relevant_fails_closed():
    fake = _fake_call('{"relevant": "yes", "reason": "ambiguous type"}')
    relevant, reason = veto_check(NEWS_ITEM, CANDIDATE, call_claude=fake)
    assert relevant is False
    assert "veto call failed" in reason
