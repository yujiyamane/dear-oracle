"""core/models.py — canonical dataclasses for Dear Oracle.

All field naming follows INTERFACES.md exactly. Serialisation methods
handle Python↔JSON impedance (e.g. from_status/to_status ↔ "from"/"to").
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Tag:
    slug: str
    tag_id: str


@dataclass
class PricePoint:
    timestamp: str
    price: float  # normalised 0.0–1.0


@dataclass
class Resolution:
    market_id: str
    resolved: bool
    outcome_label: str | None = None
    winning_prob: float | None = None  # final normalised price


@dataclass
class Market:
    """Raw market returned by the adapter (one binary outcome)."""
    market_id: str
    outcome_label: str
    url: str
    prob_now: float
    prob_24h_ago: float | None = None
    prob_7d_ago: float | None = None
    delta_24h_pp: float | None = None
    delta_7d_pp: float | None = None


@dataclass
class Event:
    """Raw event returned by the adapter (basket of Markets)."""
    event_id: str
    event_title: str
    markets: list[Market]
    volume_usd: float | None = None
    end_date: str | None = None
    tags: list[Tag] = field(default_factory=list)
    # DO v2 hard-filter fields (Gamma /public-search): active/closed/liquidity/24hr volume.
    active: bool | None = None
    closed: bool | None = None
    liquidity_usd: float | None = None
    volume_24hr_usd: float | None = None


# ---------------------------------------------------------------------------
# market_signals[] contract — INTERFACES.md §2
# ---------------------------------------------------------------------------

@dataclass
class OutcomeSignal:
    """One outcome entry inside a SignalEvent.outcomes[]."""
    outcome_label: str
    market_id: str
    url: str
    prob_now: float
    prob_24h_ago: float | None = None
    prob_7d_ago: float | None = None
    delta_24h_pp: float | None = None
    delta_7d_pp: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OutcomeSignal:
        return cls(
            outcome_label=d["outcome_label"],
            market_id=d["market_id"],
            url=d["url"],
            prob_now=d["prob_now"],
            prob_24h_ago=d.get("prob_24h_ago"),
            prob_7d_ago=d.get("prob_7d_ago"),
            delta_24h_pp=d.get("delta_24h_pp"),
            delta_7d_pp=d.get("delta_7d_pp"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_label": self.outcome_label,
            "market_id": self.market_id,
            "url": self.url,
            "prob_now": self.prob_now,
            "prob_24h_ago": self.prob_24h_ago,
            "prob_7d_ago": self.prob_7d_ago,
            "delta_24h_pp": self.delta_24h_pp,
            "delta_7d_pp": self.delta_7d_pp,
        }


@dataclass
class SignalEvent:
    """One item in market_signals[].signals[]."""
    event_id: str
    event_title: str
    interest_tag: str
    outcomes: list[OutcomeSignal]
    threshold_pp: float
    threshold_exceeded: bool
    threshold_triggered_by: str | None
    volume_usd: float
    end_date: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SignalEvent:
        return cls(
            event_id=d["event_id"],
            event_title=d["event_title"],
            interest_tag=d["interest_tag"],
            outcomes=[OutcomeSignal.from_dict(o) for o in d["outcomes"]],
            threshold_pp=d["threshold_pp"],
            threshold_exceeded=d["threshold_exceeded"],
            threshold_triggered_by=d.get("threshold_triggered_by"),
            volume_usd=d["volume_usd"],
            end_date=d["end_date"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_title": self.event_title,
            "interest_tag": self.interest_tag,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "threshold_pp": self.threshold_pp,
            "threshold_exceeded": self.threshold_exceeded,
            "threshold_triggered_by": self.threshold_triggered_by,
            "volume_usd": self.volume_usd,
            "end_date": self.end_date,
        }


@dataclass
class CoverageTransition:
    """One entry in market_signals[].coverage_transitions[].
    JSON uses "from"/"to" — reserved in Python, so stored as from_status/to_status.
    """
    interest: str
    from_status: str
    to_status: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CoverageTransition:
        return cls(
            interest=d["interest"],
            from_status=d["from"],
            to_status=d["to"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interest": self.interest,
            "from": self.from_status,
            "to": self.to_status,
        }


@dataclass
class StandingOutcome:
    """One outcome entry in standings[].top_outcomes — INTERFACES.md §2 (D41)."""
    label: str
    prob_now: float
    delta_24h_pp: float | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StandingOutcome:
        return cls(
            label=d["label"],
            prob_now=d["prob_now"],
            delta_24h_pp=d.get("delta_24h_pp"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "prob_now": self.prob_now,
            "delta_24h_pp": self.delta_24h_pp,
        }


@dataclass
class Standing:
    """One entry in standings[] — the Where-things-stand snapshot (D41)."""
    event_id: str
    event_title: str
    interest_tag: str
    is_binary: bool
    top_outcomes: list[StandingOutcome]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Standing:
        return cls(
            event_id=d["event_id"],
            event_title=d["event_title"],
            interest_tag=d["interest_tag"],
            is_binary=d["is_binary"],
            top_outcomes=[StandingOutcome.from_dict(o) for o in d.get("top_outcomes", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_title": self.event_title,
            "interest_tag": self.interest_tag,
            "is_binary": self.is_binary,
            "top_outcomes": [o.to_dict() for o in self.top_outcomes],
        }


# ---------------------------------------------------------------------------
# DO v2 — do_hits.json schema v2 (reality-check blocks, inline under DK news)
# ---------------------------------------------------------------------------

@dataclass
class RealityCheckHit:
    """One market attached to a DK news item. source_news_id is required —
    an entry without it is a bug (no orphan markets, dk-do-v2-PLAN.md §DO-V2-3).
    """
    source_news_id: str
    event_id: str
    event_title: str
    market_id: str
    outcome_label: str
    url: str
    prob_now: float
    delta_24h_pp: float | None
    delta_7d_pp: float | None
    volume_usd: float
    liquidity_usd: float
    end_date: str | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RealityCheckHit:
        return cls(
            source_news_id=d["source_news_id"],
            event_id=d["event_id"],
            event_title=d["event_title"],
            market_id=d["market_id"],
            outcome_label=d["outcome_label"],
            url=d["url"],
            prob_now=d["prob_now"],
            delta_24h_pp=d.get("delta_24h_pp"),
            delta_7d_pp=d.get("delta_7d_pp"),
            volume_usd=d["volume_usd"],
            liquidity_usd=d["liquidity_usd"],
            end_date=d.get("end_date"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_news_id": self.source_news_id,
            "event_id": self.event_id,
            "event_title": self.event_title,
            "market_id": self.market_id,
            "outcome_label": self.outcome_label,
            "url": self.url,
            "prob_now": self.prob_now,
            "delta_24h_pp": self.delta_24h_pp,
            "delta_7d_pp": self.delta_7d_pp,
            "volume_usd": self.volume_usd,
            "liquidity_usd": self.liquidity_usd,
            "end_date": self.end_date,
        }


@dataclass
class MarketSignals:
    """Top-level market_signals[] export — INTERFACES.md §2."""
    schema_version: int
    source: str
    generated_at: str
    coverage_transitions: list[CoverageTransition]
    standings: list[Standing]
    signals: list[SignalEvent]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MarketSignals:
        return cls(
            schema_version=d["schema_version"],
            source=d["source"],
            generated_at=d["generated_at"],
            coverage_transitions=[
                CoverageTransition.from_dict(ct) for ct in d.get("coverage_transitions", [])
            ],
            standings=[Standing.from_dict(s) for s in d.get("standings", [])],
            signals=[SignalEvent.from_dict(s) for s in d.get("signals", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "generated_at": self.generated_at,
            "coverage_transitions": [ct.to_dict() for ct in self.coverage_transitions],
            "standings": [s.to_dict() for s in self.standings],
            "signals": [s.to_dict() for s in self.signals],
        }
