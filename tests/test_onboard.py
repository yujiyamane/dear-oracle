"""Sprint 2 — test_onboard.py (TDD, written before core/onboard.py).

Cases per TDD.md Sprint 2:
  test_tag_mapping          — "AI" -> candidate artificial-intelligence; both fields persisted
  test_atomic_write         — simulated crash leaves prior file intact, .tmp present
  test_mode_by_contents     — mode derived from schema_version in contents, NOT file existence
  test_ps_add_drop          — drop removes; add runs coverage_for and appends
  test_zero_coverage_dormant — zero match -> dormant, empty resolved_tags, keyword_fallback set

Zero live API calls — inline _OnboardAdapter, tmp_path for file I/O.

Function signatures (INTERFACES.md §5 + PLAN.md Sprint 2):
  coverage_for(keyword, adapter)     -> (candidates: list[{slug,tag_id}], market_count: int)
  write_interests_atomic(profile, path)
  load_interests_mode(path)          -> 'first_letter' | 'ps' | 'corrupt'
  add_interest(profile, interest)    -> new profile (pure)
  drop_interest(profile, name)       -> new profile (pure)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.models import Event, Market, Tag


# ---------------------------------------------------------------------------
# Inline mock adapter — no fixture files, no network
# ---------------------------------------------------------------------------

class _OnboardAdapter:
    def __init__(self, tags: list[dict] | None = None, events: list[Event] | None = None):
        self._tags = tags or []
        self._events: list[Event] = events or []

    def tags(self) -> list[Tag]:
        return [Tag(slug=t["slug"], tag_id=t["tag_id"]) for t in self._tags]

    def search(self, query: str, limit: int = 10) -> list[Event]:
        return self._events[:limit]

    def events_by_tag(self, tag_id: str, limit: int = 20) -> list[Event]:
        return [e for e in self._events if any(t.tag_id == tag_id for t in e.tags)][:limit]

    def markets_for_event(self, event_id: str) -> list[Market]:
        for e in self._events:
            if e.event_id == event_id:
                return list(e.markets)
        return []


# ---------------------------------------------------------------------------
# Adapter factories
# ---------------------------------------------------------------------------

def _ai_adapter() -> _OnboardAdapter:
    tag = Tag(slug="artificial-intelligence", tag_id="305")
    event = Event(
        event_id="e-ai-1",
        event_title="Will AGI arrive by 2028?",
        markets=[
            Market(market_id="m-ai-1", outcome_label="Yes",
                   url="https://polymarket.com/e/agi", prob_now=0.24)
        ],
        volume_usd=450_000,
        end_date="2028-12-31",
        tags=[tag],
    )
    return _OnboardAdapter(
        tags=[
            {"slug": "artificial-intelligence", "tag_id": "305"},
            {"slug": "finance", "tag_id": "100"},
        ],
        events=[event],
    )


def _f1_adapter() -> _OnboardAdapter:
    tag = Tag(slug="formula-1", tag_id="400")
    event = Event(
        event_id="e-f1-1",
        event_title="F1 2026 World Champion",
        markets=[
            Market(market_id="m-f1-1", outcome_label="Verstappen",
                   url="https://polymarket.com/e/f1", prob_now=0.45)
        ],
        volume_usd=1_000_000,
        end_date="2026-11-30",
        tags=[tag],
    )
    return _OnboardAdapter(
        tags=[{"slug": "formula-1", "tag_id": "400"}],
        events=[event],
    )


def _empty_adapter() -> _OnboardAdapter:
    return _OnboardAdapter()


def _profile(interests: list[dict] | None = None) -> dict:
    return {
        "schema_version": 1,
        "updated_at": "2026-06-13T07:10:00+10:00",
        "interests": interests or [],
    }


# ---------------------------------------------------------------------------
# test_tag_mapping
# ---------------------------------------------------------------------------

def test_tag_mapping(tmp_path):
    """'AI' search returns event tagged artificial-intelligence.

    coverage_for surfaces that candidate; writing the profile persists both
    slug and tag_id in resolved_tags (INTERFACES.md §5).
    """
    from core.onboard import coverage_for, write_interests_atomic

    candidates, market_count = coverage_for("AI", _ai_adapter())

    slugs = [c["slug"] for c in candidates]
    assert "artificial-intelligence" in slugs, (
        f"'AI' must surface artificial-intelligence via search; got slugs={slugs}"
    )
    assert market_count > 0, "at least 1 market must be counted for artificial-intelligence"

    ai_cand = next(c for c in candidates if c["slug"] == "artificial-intelligence")

    profile = _profile([{
        "name": "AI",
        "status": "active",
        "resolved_tags": [{"slug": ai_cand["slug"], "tag_id": ai_cand["tag_id"]}],
        "focus": [],
        "keyword_fallback": "AI",
        "max_markets": 5,
        "threshold_pp": 5.0,
        "added_at": "2026-06-13",
    }])

    out = tmp_path / "interests.json"
    write_interests_atomic(profile, out)

    saved = json.loads(out.read_text(encoding="utf-8"))
    rt = saved["interests"][0]["resolved_tags"]
    assert len(rt) == 1
    assert rt[0]["slug"] == "artificial-intelligence"
    assert rt[0]["tag_id"] == "305"


# ---------------------------------------------------------------------------
# test_atomic_write
# ---------------------------------------------------------------------------

def test_atomic_write(tmp_path, monkeypatch):
    """Simulated crash between tmp-write and os.replace leaves prior file intact, .tmp present."""
    from core.onboard import write_interests_atomic
    import core.onboard as onboard_mod

    path = tmp_path / "interests.json"
    prior = _profile()
    write_interests_atomic(prior, path)

    def _crash(src: str, dst: str) -> None:
        raise OSError("simulated crash")

    monkeypatch.setattr(onboard_mod, "_os_replace", _crash)

    with pytest.raises(OSError, match="simulated crash"):
        write_interests_atomic(_profile([{"name": "new"}]), path)

    tmp_file = Path(str(path) + ".tmp")
    assert tmp_file.exists(), ".tmp must exist after mid-write crash"

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == prior, "prior interests.json must be untouched after crash"


# ---------------------------------------------------------------------------
# test_mode_by_contents
# ---------------------------------------------------------------------------

def test_mode_by_contents(tmp_path):
    """Mode is read from schema_version in contents — not from file existence.

    No file      -> 'first_letter'
    Empty        -> 'corrupt'  (NOT 'first_letter')
    Bad JSON     -> 'corrupt'
    No schema_version field -> 'corrupt'
    Valid schema_version    -> 'ps'
    """
    from core.onboard import load_interests_mode

    assert load_interests_mode(tmp_path / "missing.json") == "first_letter"

    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert load_interests_mode(empty) == "corrupt", "empty file must be corrupt, not first_letter"

    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{", encoding="utf-8")
    assert load_interests_mode(bad) == "corrupt"

    no_sv = tmp_path / "no_sv.json"
    no_sv.write_text(json.dumps({"interests": []}), encoding="utf-8")
    assert load_interests_mode(no_sv) == "corrupt"

    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps({"schema_version": 1, "interests": []}), encoding="utf-8")
    assert load_interests_mode(valid) == "ps"


# ---------------------------------------------------------------------------
# test_ps_add_drop
# ---------------------------------------------------------------------------

def test_ps_add_drop():
    """P.S. drop removes the named interest; P.S. add runs coverage_for and appends.

    Both add_interest / drop_interest are pure — they never mutate the original.
    """
    from core.onboard import add_interest, drop_interest, coverage_for

    surfing = {
        "name": "surfing", "status": "active",
        "resolved_tags": [{"slug": "surfing", "tag_id": "200"}],
        "focus": [], "keyword_fallback": "surfing",
        "max_markets": 5, "threshold_pp": 5.0, "added_at": "2026-06-13",
    }
    soccer = {
        "name": "soccer", "status": "active",
        "resolved_tags": [{"slug": "soccer", "tag_id": "100"}],
        "focus": [], "keyword_fallback": "soccer",
        "max_markets": 5, "threshold_pp": 5.0, "added_at": "2026-06-13",
    }
    original = _profile([surfing, soccer])

    after_drop = drop_interest(original, "surfing")
    assert [i["name"] for i in original["interests"]] == ["surfing", "soccer"], (
        "drop_interest must not mutate the original profile"
    )
    names = [i["name"] for i in after_drop["interests"]]
    assert "surfing" not in names
    assert "soccer" in names

    # P.S. add F1 — coverage_for must run and find formula-1
    candidates, count = coverage_for("F1", _f1_adapter())
    assert count > 0
    assert any(c["slug"] == "formula-1" for c in candidates)

    f1_interest = {
        "name": "F1",
        "status": "active" if candidates else "dormant",
        "resolved_tags": [c for c in candidates if c["slug"] == "formula-1"],
        "focus": [],
        "keyword_fallback": "F1",
        "max_markets": 5,
        "threshold_pp": 5.0,
        "added_at": "2026-06-13",
    }
    after_add = add_interest(after_drop, f1_interest)
    assert [i["name"] for i in after_drop["interests"]] == ["soccer"], (
        "add_interest must not mutate the prior profile"
    )
    final_names = [i["name"] for i in after_add["interests"]]
    assert "F1" in final_names
    assert "soccer" in final_names
    assert "surfing" not in final_names
    assert len(after_add["interests"]) == 2


# ---------------------------------------------------------------------------
# test_zero_coverage_dormant
# ---------------------------------------------------------------------------

def test_zero_coverage_dormant(tmp_path):
    """Zero coverage -> written status dormant, empty resolved_tags, keyword_fallback set."""
    from core.onboard import coverage_for, write_interests_atomic

    candidates, market_count = coverage_for("surfing", _empty_adapter())
    assert candidates == []
    assert market_count == 0

    interest = {
        "name": "surfing",
        "status": "dormant",
        "resolved_tags": candidates,   # []
        "focus": [],
        "keyword_fallback": "surfing",
        "max_markets": 5,
        "threshold_pp": 5.0,
        "added_at": "2026-06-13",
    }
    path = tmp_path / "interests.json"
    write_interests_atomic(_profile([interest]), path)

    saved = json.loads(path.read_text(encoding="utf-8"))
    surf = saved["interests"][0]
    assert surf["status"] == "dormant"
    assert surf["resolved_tags"] == []
    assert surf["keyword_fallback"] == "surfing"
