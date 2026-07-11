"""tests/test_extraction.py — core/extraction.py: Haiku query-variant extraction.

dk-do-v2-PLAN.md DO-V2-2 step 1: entity/keyword extraction from a DK news
cluster, producing 2-3 short Polymarket /public-search query strings. AI may
only produce SEARCH QUERIES here — it never adds candidate markets directly
(those still come from code-driven Polymarket search + hard filters).

No real `claude` CLI calls in this suite — call_claude is always injected.
"""
from __future__ import annotations

import os

import pytest

from core.extraction import extract_query_variants

NEWS_ITEM = {
    "id": "news-1",
    "title": "Iran-US tension escalates, Strait of Hormuz shipping disrupted",
    "headlines": [
        "US warns of retaliation after tanker incident",
        "Oil prices spike on Hormuz disruption fears",
    ],
}


def _fake_call(response: str):
    def _call(prompt: str, model: str) -> str:
        return response
    return _call


def test_extract_query_variants_happy_path():
    fake = _fake_call('["Iran US conflict", "Strait of Hormuz", "Iran oil exports"]')
    result = extract_query_variants(NEWS_ITEM, call_claude=fake)
    assert result == ["Iran US conflict", "Strait of Hormuz", "Iran oil exports"]


def test_extract_query_variants_strips_markdown_fences():
    fake = _fake_call('```json\n["Iran US conflict", "Strait of Hormuz"]\n```')
    result = extract_query_variants(NEWS_ITEM, call_claude=fake)
    assert result == ["Iran US conflict", "Strait of Hormuz"]


def test_extract_query_variants_caps_at_three():
    fake = _fake_call('["a", "b", "c", "d", "e"]')
    result = extract_query_variants(NEWS_ITEM, call_claude=fake)
    assert result == ["a", "b", "c"]


def test_extract_query_variants_malformed_json_returns_empty():
    fake = _fake_call("not json at all")
    result = extract_query_variants(NEWS_ITEM, call_claude=fake)
    assert result == []


def test_extract_query_variants_empty_response_returns_empty():
    fake = _fake_call("")
    result = extract_query_variants(NEWS_ITEM, call_claude=fake)
    assert result == []


def test_extract_query_variants_non_list_json_rejected():
    fake = _fake_call('{"queries": ["a", "b"]}')
    result = extract_query_variants(NEWS_ITEM, call_claude=fake)
    assert result == []


def test_extract_query_variants_non_string_items_rejected():
    fake = _fake_call('["a", 123, "b"]')
    result = extract_query_variants(NEWS_ITEM, call_claude=fake)
    assert result == []


def test_extract_query_variants_call_claude_exception_returns_empty():
    def _raise(prompt: str, model: str) -> str:
        raise RuntimeError("subprocess exploded")
    result = extract_query_variants(NEWS_ITEM, call_claude=_raise)
    assert result == []


def test_extract_query_variants_empty_list_json():
    fake = _fake_call("[]")
    result = extract_query_variants(NEWS_ITEM, call_claude=fake)
    assert result == []


@pytest.mark.skipif(
    os.environ.get("DO_LIVE_CLAUDE_SMOKE") != "1",
    reason="live smoke test — set DO_LIVE_CLAUDE_SMOKE=1 to run against the real claude CLI",
)
def test_extract_query_variants_live_smoke():
    """Real subprocess call to the claude CLI. Skipped by default (slow, costs
    tokens, non-deterministic) — run manually with DO_LIVE_CLAUDE_SMOKE=1."""
    result = extract_query_variants(NEWS_ITEM)
    assert isinstance(result, list)
    assert 0 <= len(result) <= 3
