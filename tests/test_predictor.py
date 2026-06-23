"""Sprint 1 — test_predictor.py
Tests are written BEFORE implementation (TDD). All use MockAdapter from conftest.py;
zero live API calls.

Cases per TDD.md Sprint 1:
  test_aggregate_sorted_field
  test_cold_mode_volume_rank
  test_known_user_tag_filter
  test_multi_match
  test_zero_result
  test_deck_rotproof
"""
import json
from pathlib import Path

import pytest

from tests.conftest import load_fixture


# ---------------------------------------------------------------------------
# test_aggregate_sorted_field
# ---------------------------------------------------------------------------

def test_aggregate_sorted_field(worldcup_adapter):
    """outcomes sorted desc; Field remainder; basket sums to 1.00 ±0.01."""
    from core.resolve import aggregate

    events = worldcup_adapter.search("world cup")
    assert events, "worldcup fixture must have at least one event"
    event = events[0]

    outcomes = aggregate(event)

    # Named outcomes (all except Field) must be sorted by probability descending.
    # Field is always appended last regardless of its probability value —
    # it is a catch-all "rest of field", not ranked among named outcomes.
    # (PRFAQ example: Spain 30% > England 20% > … > Field 35% — Field last.)
    non_field = [o for o in outcomes if o.label != "Field"]
    non_field_probs = [o.prob for o in non_field]
    assert non_field_probs == sorted(non_field_probs, reverse=True), (
        "named outcomes must be sorted by prob desc"
    )

    # Total must sum to 1.00 ±0.01
    total = sum(o.prob for o in outcomes)
    assert abs(total - 1.0) <= 0.01, f"basket sum {total:.4f} not within 0.01 of 1.0"

    # Field must be the last entry
    assert outcomes[-1].label == "Field", "last outcome must be 'Field'"

    # Spain (0.30) should be first
    assert outcomes[0].label == "Spain"
    assert abs(outcomes[0].prob - 0.30) < 0.001

    # Verify specific outcome labels are all present
    labels = [o.label for o in outcomes]
    assert "England" in labels
    assert "Argentina" in labels
    assert "France" in labels

    # Field value = 1 - (0.30 + 0.20 + 0.10 + 0.05) = 0.35
    field = next(o for o in outcomes if o.label == "Field")
    assert abs(field.prob - 0.35) < 0.01


# ---------------------------------------------------------------------------
# test_cold_mode_volume_rank
# ---------------------------------------------------------------------------

def test_cold_mode_volume_rank(election_multi_adapter, tmp_path):
    """No interests.json present -> pure volume order; US (8M) ranks first."""
    from core.predictor import predict, PredictorAnswer

    result = predict("election", adapter=election_multi_adapter, interests_path=None)

    assert isinstance(result, PredictorAnswer)
    assert result.main_event.event_id == "us-election-2028", (
        f"top-volume event should be US election; got {result.main_event.event_id}"
    )


# ---------------------------------------------------------------------------
# test_known_user_tag_filter
# ---------------------------------------------------------------------------

def test_known_user_tag_filter(election_multi_adapter, tmp_path):
    """interests.json with australian-politics (tag_id 503) → AU event ranks first."""
    from core.predictor import predict, PredictorAnswer

    interests_file = tmp_path / "interests.json"
    interests_file.write_text(json.dumps({
        "schema_version": 1,
        "updated_at": "2026-06-13T00:00:00+10:00",
        "interests": [
            {
                "name": "australian-politics",
                "status": "active",
                "resolved_tags": [
                    {"slug": "australian-politics", "tag_id": "503"}
                ],
                "focus": ["australian federal election"],
                "keyword_fallback": "australian politics",
                "max_markets": 5,
                "threshold_pp": 5.0,
                "added_at": "2026-06-13"
            }
        ]
    }))

    result = predict(
        "election",
        adapter=election_multi_adapter,
        interests_path=str(interests_file),
    )

    assert isinstance(result, PredictorAnswer)
    assert result.main_event.event_id == "au-election-2028", (
        f"AU event should beat higher-volume US event when interest tag matches; "
        f"got {result.main_event.event_id}"
    )


# ---------------------------------------------------------------------------
# test_multi_match
# ---------------------------------------------------------------------------

def test_multi_match(election_multi_adapter):
    """3-event fixture → top-volume (US) is main; exactly the other 2 in Also pricing."""
    from core.predictor import predict, PredictorAnswer

    result = predict("election", adapter=election_multi_adapter, interests_path=None)

    assert isinstance(result, PredictorAnswer)
    assert result.main_event.event_id == "us-election-2028"

    also_ids = {e.event_id for e in result.also_pricing}
    assert len(result.also_pricing) == 2, (
        f"expected exactly 2 also_pricing events, got {len(result.also_pricing)}"
    )
    assert "uk-election-2028" in also_ids
    assert "au-election-2028" in also_ids


# ---------------------------------------------------------------------------
# test_zero_result
# ---------------------------------------------------------------------------

def test_zero_result(zero_adapter):
    """No matching events → ZeroResult with exactly 3 nearest questions, never empty."""
    from core.predictor import predict, ZeroResult

    questions_deck = str(
        Path(__file__).parent.parent / "config" / "questions.example.json"
    )

    result = predict(
        "surfing championship",
        adapter=zero_adapter,
        interests_path=None,
        questions_deck_path=questions_deck,
    )

    assert isinstance(result, ZeroResult), (
        f"expected ZeroResult for zero-match query, got {type(result)}"
    )
    assert len(result.nearest_questions) == 3, (
        f"zero-result must return exactly 3 nearest questions; "
        f"got {len(result.nearest_questions)}"
    )
    assert all(isinstance(q, str) and q for q in result.nearest_questions), (
        "nearest_questions must be non-empty strings"
    )


# ---------------------------------------------------------------------------
# test_deck_rotproof
# ---------------------------------------------------------------------------

def test_deck_rotproof(worldcup_adapter):
    """Deck entries store tag_id not frozen event_id — resolves to live event."""
    from core.predictor import resolve_deck_entries

    deck_entries = [
        {"label": "Who will win the FIFA World Cup?", "tag_id": "204", "query": "world cup winner"}
    ]

    resolved = resolve_deck_entries(deck_entries, adapter=worldcup_adapter)

    assert len(resolved) == 1
    entry = resolved[0]

    # The resolved entry must contain a live Event, not a cached/frozen ID
    assert entry["event"] is not None, "deck entry must resolve to a live Event"
    assert entry["event"].event_id == "wc-2026"
    assert entry["event"].event_title == "2026 FIFA World Cup Winner"

    # The entry label is preserved
    assert entry["label"] == "Who will win the FIFA World Cup?"


# ---------------------------------------------------------------------------
# test_also_pricing_relevance
# ---------------------------------------------------------------------------

def test_also_pricing_relevance(noisy_adapter):
    """Unrelated high-volume events must NOT appear in also_pricing.

    Fixture: WC (vol 10M, main), NBA Champion (vol 9M), US Presidential (vol 7M).
    Simplified query tokens: {'world', 'cup'}.
    Neither 'NBA Champion' nor 'Presidential Election Winner' shares a token
    with {'world', 'cup'} → also_pricing must be empty after the relevance gate.
    """
    from core.predictor import predict, PredictorAnswer

    result = predict(
        "Who will win the 2026 World Cup?",
        adapter=noisy_adapter,
        interests_path=None,
    )

    assert isinstance(result, PredictorAnswer)
    assert result.main_event.event_id == "wc-2026", (
        f"World Cup (highest-volume) must be main event; got {result.main_event.event_id}"
    )
    assert result.also_pricing == [], (
        "unrelated events (NBA, Election) share no token with 'world cup' "
        f"and must be filtered; got: {[e.event_title for e in result.also_pricing]}"
    )


# ---------------------------------------------------------------------------
# Sprint 5B item 2 — usage-driven interest suggestions
# ---------------------------------------------------------------------------

_SOCCER_INTERESTS = {
    "schema_version": 1,
    "updated_at": "2026-06-13T00:00:00+10:00",
    "interests": [{
        "name": "soccer",
        "status": "active",
        "resolved_tags": [{"slug": "world-cup", "tag_id": "204"}],
        "focus": [],
        "keyword_fallback": "soccer",
        "max_markets": 5,
        "threshold_pp": 5.0,
        "added_at": "2026-06-13",
    }],
}

_AU_POLITICS_INTERESTS = {
    "schema_version": 1,
    "updated_at": "2026-06-13T00:00:00+10:00",
    "interests": [{
        "name": "australian-politics",
        "status": "active",
        "resolved_tags": [{"slug": "australian-politics", "tag_id": "503"}],
        "focus": [],
        "keyword_fallback": "australian politics",
        "max_markets": 5,
        "threshold_pp": 5.0,
        "added_at": "2026-06-13",
    }],
}


def test_off_profile_query_logged(election_multi_adapter, tmp_path, db):
    """Off-profile query (soccer interests, election query) → row in query_log off_profile=1."""
    from core.predictor import predict, PredictorAnswer

    interests_file = tmp_path / "interests.json"
    interests_file.write_text(json.dumps(_SOCCER_INTERESTS))

    result = predict(
        "election",
        adapter=election_multi_adapter,
        interests_path=str(interests_file),
        db_conn=db,
    )

    assert isinstance(result, PredictorAnswer)
    rows = db.execute("SELECT * FROM query_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["off_profile"] == 1


def test_on_profile_query_not_logged(election_multi_adapter, tmp_path, db):
    """On-profile query (au-politics interests, election query) → no rows in query_log."""
    from core.predictor import predict

    interests_file = tmp_path / "interests.json"
    interests_file.write_text(json.dumps(_AU_POLITICS_INTERESTS))

    predict(
        "election",
        adapter=election_multi_adapter,
        interests_path=str(interests_file),
        db_conn=db,
    )

    rows = db.execute("SELECT * FROM query_log").fetchall()
    assert len(rows) == 0


def test_suggestion_fires_at_threshold(election_multi_adapter, tmp_path, db):
    """3 off-profile queries for same topic → result.suggestion is not None and mentions topic."""
    from core.predictor import predict, PredictorAnswer, _SUGGESTION_THRESHOLD

    interests_file = tmp_path / "interests.json"
    interests_file.write_text(json.dumps(_SOCCER_INTERESTS))

    result = None
    for _ in range(_SUGGESTION_THRESHOLD):
        result = predict(
            "election",
            adapter=election_multi_adapter,
            interests_path=str(interests_file),
            db_conn=db,
        )

    assert isinstance(result, PredictorAnswer)
    assert result.suggestion is not None, "suggestion must fire at threshold"
    assert "election" in result.suggestion.lower()


def test_suggestion_absent_below_threshold(election_multi_adapter, tmp_path, db):
    """2 off-profile queries (threshold-1) → result.suggestion is None."""
    from core.predictor import predict, PredictorAnswer, _SUGGESTION_THRESHOLD

    interests_file = tmp_path / "interests.json"
    interests_file.write_text(json.dumps(_SOCCER_INTERESTS))

    result = None
    for _ in range(_SUGGESTION_THRESHOLD - 1):
        result = predict(
            "election",
            adapter=election_multi_adapter,
            interests_path=str(interests_file),
            db_conn=db,
        )

    assert isinstance(result, PredictorAnswer)
    assert result.suggestion is None, "suggestion must not fire below threshold"
