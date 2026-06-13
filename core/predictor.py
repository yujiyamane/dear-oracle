"""core/predictor.py — oracle-predictor engine.

Public API:
  predict(query, adapter, interests_path, questions_deck_path)
      -> PredictorAnswer | ZeroResult

  resolve_deck_entries(entries, adapter) -> list[dict]
      Pre-load the rot-proof deck: each entry's tag_id is resolved to the
      current top-volume live event via events_by_tag(), not a frozen event_id.

  Format output block (used by CLI and SKILL.md):
  -> Spain     30%   +4pp 7d
  -> England   20%   --
  -> Field     35%
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from core.models import Event
from core.resolve import Outcome, aggregate

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------

@dataclass
class PredictorAnswer:
    main_event: Event
    outcomes: list[Outcome]
    also_pricing: list[Event] = field(default_factory=list)


@dataclass
class ZeroResult:
    nearest_questions: list[str]


# ---------------------------------------------------------------------------
# predict
# ---------------------------------------------------------------------------

def predict(
    query: str,
    adapter=None,
    interests_path: str | None = "config/interests.json",
    questions_deck_path: str | None = None,
) -> PredictorAnswer | ZeroResult:
    """Resolve a natural-language question to ranked probability outcomes.

    Cold mode (no interests.json): pure volume rank.
    Known-user mode (interests.json present and readable): filter to events
    whose tags overlap with the user's active interest tag_ids, then volume rank.
    Multi-match: highest-volume event is main; the rest go into also_pricing.
    Zero-result: return 3 nearest questions from the deck.
    """
    if adapter is None:
        from core.adapter_polymarket import PolymarketAdapter
        adapter = PolymarketAdapter()

    events = adapter.search(_simplify_query(query))

    # Known-user filter
    if interests_path:
        interest_tag_ids = _load_interest_tag_ids(interests_path)
        if interest_tag_ids:
            filtered = [
                e for e in events
                if any(t.tag_id in interest_tag_ids for t in e.tags)
            ]
            if filtered:
                events = filtered

    if not events:
        nearest = _nearest_questions(query, questions_deck_path)
        return ZeroResult(nearest_questions=nearest)

    # Volume-rank
    events = sorted(events, key=lambda e: e.volume_usd or 0.0, reverse=True)

    main_event = events[0]

    # Relevance gate: keep only also_pricing events whose title shares at least
    # one significant token (no stop words, no 4-digit years) with the simplified
    # query.  The main event is never gated — it already won by volume rank.
    query_tokens = _relevance_tokens(_simplify_query(query))
    also_pricing = [
        e for e in events[1:]
        if _relevance_tokens(e.event_title) & query_tokens
    ]

    return PredictorAnswer(
        main_event=main_event,
        outcomes=aggregate(main_event),
        also_pricing=also_pricing,
    )


# ---------------------------------------------------------------------------
# resolve_deck_entries — rot-proof deck loader
# ---------------------------------------------------------------------------

def resolve_deck_entries(entries: list[dict], adapter=None) -> list[dict]:
    """Resolve deck entries to live events at load time.

    Each entry must have 'tag_id' and 'label'.  The function calls
    events_by_tag(tag_id) and picks the highest-volume event so the deck
    never points to a stale/resolved event.

    Returns a list of dicts: {"label": ..., "tag_id": ..., "event": Event|None}
    """
    if adapter is None:
        from core.adapter_polymarket import PolymarketAdapter
        adapter = PolymarketAdapter()

    resolved = []
    for entry in entries:
        tag_id = entry.get("tag_id", "")
        events = adapter.events_by_tag(tag_id) if tag_id else []
        top_event = max(events, key=lambda e: e.volume_usd or 0.0) if events else None
        resolved.append({
            "label": entry.get("label", ""),
            "tag_id": tag_id,
            "query": entry.get("query", ""),
            "event": top_event,
        })
    return resolved


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    "who what when where which how will be the a an is are was were of in for "
    "at by with from on about next win wins won does do can i me my we our "
    "you your it its this that these those am has have had and or but not".split()
)


_YEAR_RE = re.compile(r'^\d{4}$')


def _relevance_tokens(text: str) -> frozenset[str]:
    """Significant tokens for title-overlap matching.

    Excludes stop words and bare 4-digit years so that shared year tokens
    (e.g. both events have "2026") don't create false positives.
    """
    return frozenset(
        t.lower()
        for t in text.split()
        if t.lower() not in _STOP_WORDS and not _YEAR_RE.match(t)
    )


def _simplify_query(question: str) -> str:
    """Strip common question words to improve API search relevance.

    'Who will win the 2026 World Cup?' -> '2026 World Cup'
    'Will AGI be declared by end of 2027?' -> 'AGI declared end 2027'
    Preserves capitalisation; keeps first 5 content words.
    """
    tokens = question.rstrip("?").split()
    content = [t for t in tokens if t.lower() not in _STOP_WORDS]
    return " ".join(content[:5]) if content else question


def _load_interest_tag_ids(path: str) -> set[str]:
    """Return the set of tag_ids for all active interests in interests.json.
    Returns empty set if the file doesn't exist or fails to parse.
    """
    try:
        p = Path(path)
        if not p.exists():
            return set()
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set()

    tag_ids: set[str] = set()
    for interest in data.get("interests", []):
        if interest.get("status") == "active":
            for tag in interest.get("resolved_tags", []):
                tid = tag.get("tag_id")
                if tid:
                    tag_ids.add(str(tid))
    return tag_ids


def _nearest_questions(query: str, deck_path: str | None) -> list[str]:
    """Return 3 nearest questions from the deck using keyword overlap scoring.
    Always returns exactly 3 strings; falls back to hardcoded stubs if no deck.
    """
    _fallback = [
        "Who will win the 2026 World Cup?",
        "Who will win the US Presidential election?",
        "Will AGI be declared by end of 2027?",
    ]

    if deck_path is None:
        deck_path = str(
            Path(__file__).parent.parent / "config" / "questions.example.json"
        )

    try:
        with open(deck_path, encoding="utf-8") as f:
            data = json.load(f)
        questions = [q["label"] for q in data.get("questions", [])]
    except Exception:
        return _fallback

    if len(questions) <= 3:
        return (questions + _fallback)[:3]

    query_words = set(query.lower().split())

    def _score(q: str) -> int:
        return len(query_words & set(q.lower().split()))

    ranked = sorted(questions, key=_score, reverse=True)
    return ranked[:3]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _format_delta(o: Outcome) -> str:
    if o.delta_7d_pp is not None and abs(o.delta_7d_pp) >= 0.5:
        sign = "+" if o.delta_7d_pp > 0 else ""
        return f"{sign}{o.delta_7d_pp:.0f}pp 7d"
    if o.delta_24h_pp is not None and abs(o.delta_24h_pp) >= 0.5:
        sign = "+" if o.delta_24h_pp > 0 else ""
        return f"{sign}{o.delta_24h_pp:.0f}pp 24h"
    return "--"


_MIN_DISPLAY_PCT = 1  # suppress outcomes that round to 0%


def _render_answer(result: PredictorAnswer) -> None:
    print(f"\n{result.main_event.event_title}")
    shown = [o for o in result.outcomes if round(o.prob * 100) >= _MIN_DISPLAY_PCT]
    hidden = len(result.outcomes) - len(shown)
    for o in shown:
        pct = round(o.prob * 100)
        delta = _format_delta(o)
        print(f"-> {o.label:<14} {pct:>3}%   {delta}")
    if hidden:
        print(f"   (+ {hidden} more below 1%)")
    if result.also_pricing:
        also = " · ".join(e.event_title for e in result.also_pricing[:3])
        if len(result.also_pricing) > 3:
            also += f" (+ {len(result.also_pricing) - 3} more)"
        print(f"\nAlso pricing: {also}")
        print("Ask about either for a full breakdown.")


def _render_zero(result: ZeroResult) -> None:
    print("The crowd hasn't priced this yet.")
    print("The closest questions they have answered:")
    for q in result.nearest_questions:
        print(f"  - {q}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m core.predictor \"<question>\"")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    answer = predict(query)

    if isinstance(answer, PredictorAnswer):
        _render_answer(answer)
    else:
        _render_zero(answer)
