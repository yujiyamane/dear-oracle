"""tests/test_synthesis.py — core/synthesis.py: Sonnet so-what/then-what prose.

dk-do-v2-PLAN.md DO-V2-2 §"So what"/"Then what" + dk_synthesis_prompt.md's
consequence-chain voice: so_what = first-order prediction ("likely"/"could"),
then_what = second-order, non-obvious knock-on. AI writes prose only — it
never chooses which markets survive (that's the caller's/code's job).
"""
from __future__ import annotations

from core.models import RealityCheckHit
from core.synthesis import synthesize_so_what_then_what

NEWS_ITEM = {
    "id": "news-1",
    "title": "Iran-US tension escalates, Strait of Hormuz shipping disrupted",
    "headlines": ["US warns of retaliation after tanker incident"],
}

HIT = RealityCheckHit(
    source_news_id="news-1", event_id="e1", event_title="Will Iran close the Strait of Hormuz?",
    market_id="m1", outcome_label="Yes", url="https://x", prob_now=0.22,
    delta_24h_pp=4.0, delta_7d_pp=9.0, volume_usd=50_000.0, liquidity_usd=5_000.0,
    end_date="2026-08-01",
)


def _fake_call(response: str):
    def _call(prompt: str, model: str) -> str:
        return response
    return _call


def test_synthesize_happy_path():
    fake = _fake_call(
        '{"so_what": "Rising Hormuz closure odds likely keep oil prices elevated.", '
        '"then_what": "Sustained oil prices could slow central bank rate cuts globally."}'
    )
    so_what, then_what = synthesize_so_what_then_what(NEWS_ITEM, HIT, call_claude=fake)
    assert so_what == "Rising Hormuz closure odds likely keep oil prices elevated."
    assert then_what == "Sustained oil prices could slow central bank rate cuts globally."


def test_synthesize_markdown_fenced_json():
    fake = _fake_call(
        '```json\n{"so_what": "Prices could rise.", "then_what": "Inflation could tick up."}\n```'
    )
    so_what, then_what = synthesize_so_what_then_what(NEWS_ITEM, HIT, call_claude=fake)
    assert so_what == "Prices could rise."
    assert then_what == "Inflation could tick up."


def test_synthesize_malformed_response_returns_empty_strings():
    fake = _fake_call("not json")
    so_what, then_what = synthesize_so_what_then_what(NEWS_ITEM, HIT, call_claude=fake)
    assert (so_what, then_what) == ("", "")


def test_synthesize_missing_keys_returns_empty_strings():
    fake = _fake_call('{"so_what": "Only one field present."}')
    so_what, then_what = synthesize_so_what_then_what(NEWS_ITEM, HIT, call_claude=fake)
    assert (so_what, then_what) == ("", "")


def test_synthesize_call_exception_returns_empty_strings():
    def _raise(prompt: str, model: str) -> str:
        raise RuntimeError("subprocess exploded")
    so_what, then_what = synthesize_so_what_then_what(NEWS_ITEM, HIT, call_claude=_raise)
    assert (so_what, then_what) == ("", "")


def test_synthesize_non_string_values_returns_empty_strings():
    fake = _fake_call('{"so_what": 123, "then_what": "fine"}')
    so_what, then_what = synthesize_so_what_then_what(NEWS_ITEM, HIT, call_claude=fake)
    assert (so_what, then_what) == ("", "")
