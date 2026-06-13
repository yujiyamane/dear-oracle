"""core/resolve.py — shared resolver used by oracle-predictor and collector.

Public API:
  resolve(tags, adapter) -> list[Event]
      Resolve a list of Tag objects to live events via the adapter.
      Deduplicates by event_id. Returns empty list on any adapter failure
      (adapter already degrades to empty + log).

  aggregate(event) -> list[Outcome]
      Aggregate an event's markets into a probability-sorted outcome list.
      Appends a "Field" entry for the remainder when named probs don't sum to 1.
      Basket total must be 1.00 ±0.01 after Field is included.
"""
from __future__ import annotations

from dataclasses import dataclass
from core.models import Event, Market, Tag


# ---------------------------------------------------------------------------
# Outcome — display-layer aggregate (not persisted)
# ---------------------------------------------------------------------------

@dataclass
class Outcome:
    label: str
    prob: float
    delta_24h_pp: float | None = None
    delta_7d_pp: float | None = None


# ---------------------------------------------------------------------------
# resolve — tag → events, deduped
# ---------------------------------------------------------------------------

def resolve(tags: list[Tag], adapter) -> list[Event]:
    """Resolve a list of tags to events using the given adapter.

    Calls events_by_tag() for each tag; deduplicates by event_id.
    Any adapter failure returns empty + is logged by the adapter itself
    (caller never sees an exception).
    """
    events: list[Event] = []
    seen: set[str] = set()

    for tag in tags:
        for event in adapter.events_by_tag(tag.tag_id):
            if event.event_id not in seen:
                events.append(event)
                seen.add(event.event_id)

    return events


# ---------------------------------------------------------------------------
# aggregate — event → sorted Outcome list with Field remainder
# ---------------------------------------------------------------------------

_FIELD_MIN_PROB = 0.005  # below this, Field is too small to show


def aggregate(event: Event) -> list[Outcome]:
    """Return outcomes sorted by prob desc with a Field remainder entry.

    For multi-outcome events (e.g. World Cup) each Market represents one
    binary choice; prob_now is the 'Yes' probability for that candidate.
    Field = 1.0 − Σ(all named probs), appended only if > _FIELD_MIN_PROB.
    """
    outcomes = [
        Outcome(
            label=m.outcome_label,
            prob=m.prob_now,
            delta_24h_pp=m.delta_24h_pp,
            delta_7d_pp=m.delta_7d_pp,
        )
        for m in event.markets
    ]

    outcomes.sort(key=lambda o: o.prob, reverse=True)

    named_sum = sum(o.prob for o in outcomes)
    field_prob = 1.0 - named_sum

    if field_prob > _FIELD_MIN_PROB:
        outcomes.append(Outcome(label="Field", prob=round(field_prob, 4)))

    return outcomes
