"""Sprint 3 — test_collector.py (TDD-first: written BEFORE core/collector.py).

Tests per TDD.md Sprint 3:
  test_delta_24h              — two snapshots 24h apart -> correct delta_24h_pp
  test_delta_7d_null          — <7d history -> delta_7d_pp None; threshold judged on 24h
  test_horizon_guard          — market with end_date < now+30d excluded
  test_max_markets_cap        — more than max_markets -> capped, volume-sorted
  test_tag_degradation        — tag empty -> keyword fallback -> empty -> dormant + transition
  test_reactivation           — dormant gaining coverage -> active + transition
  test_dormant_rescan_trigger — days_since >= 7 triggers; < 7 does not (weekday-independent)
  test_export_schema          — exported JSON validates INTERFACES §2 (nested outcomes, pp
                                deltas, nullability, transitions, standings)
  test_standings_built        — standings[] has every watched event; multi-outcome top-3;
                                binary primary; dormant absent; reuses aggregate()
  test_backfill_flag          — backfilled rows carry backfilled=1
  test_threshold_triggered_by — larger |delta| window is named

Zero live API calls — inline _CollectorAdapter, db from conftest.py (in-memory SQLite).
"""
from __future__ import annotations

import json
import sqlite3 as _sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from core.models import Event, Market, PricePoint, Tag


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TODAY = "2026-06-13"
YESTERDAY = "2026-06-12"
SEVEN_DAYS_AGO = "2026-06-06"
SCHEMA_SQL = Path(__file__).parent.parent / "data" / "schema.sql"


def _iso(offset_days: int) -> str:
    return (date.fromisoformat(TODAY) + timedelta(days=offset_days)).isoformat()


# ---------------------------------------------------------------------------
# Minimal mock adapter — zero network calls
# ---------------------------------------------------------------------------

class _CollectorAdapter:
    """Deterministic adapter for collector tests: no Gamma/CLOB calls."""

    def __init__(
        self,
        events_by_tag: dict[str, list[Event]] | None = None,
        search_results: list[Event] | None = None,
        price_history: dict[str, list[PricePoint]] | None = None,
    ):
        self._ebt = events_by_tag or {}
        self._search = search_results or []
        self._prices = price_history or {}

    def events_by_tag(self, tag_id: str, limit: int = 20) -> list[Event]:
        return self._ebt.get(tag_id, [])[:limit]

    def search(self, query: str, limit: int = 10) -> list[Event]:
        return self._search[:limit]

    def prices_history(self, market_id: str, since: str) -> list[PricePoint]:
        return self._prices.get(market_id, [])

    def tags(self) -> list[Tag]:
        return []

    def markets_for_event(self, event_id: str) -> list[Market]:
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _market(
    market_id: str,
    outcome: str,
    prob: float,
    url: str = "",
) -> Market:
    return Market(
        market_id=market_id,
        outcome_label=outcome,
        url=url or f"https://x/{market_id}",
        prob_now=prob,
    )


def _event(
    event_id: str,
    title: str,
    markets: list[Market],
    volume: float = 1_000.0,
    end_date: str | None = None,
    tags: list[Tag] | None = None,
) -> Event:
    return Event(
        event_id=event_id,
        event_title=title,
        markets=markets,
        volume_usd=volume,
        end_date=end_date if end_date is not None else _iso(60),
        tags=tags or [],
    )


def _interest(
    name: str,
    tags: list[dict],
    status: str = "active",
    max_markets: int = 5,
    threshold_pp: float = 5.0,
    keyword_fallback: str | None = None,
) -> dict:
    return {
        "name": name,
        "status": status,
        "resolved_tags": tags,
        "focus": [],
        "keyword_fallback": keyword_fallback or name,
        "max_markets": max_markets,
        "threshold_pp": threshold_pp,
        "added_at": "2026-06-01",
    }


def _profile(interests: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "updated_at": "2026-06-13T07:00:00+10:00",
        "interests": interests,
    }


def _seed_snapshot(
    db: _sqlite3.Connection,
    snap_date: str,
    market_id: str,
    probability: float,
    event_id: str = "e1",
    interest: str = "ai",
    question: str = "Q?",
    outcome: str = "Yes",
    volume_usd: float = 1_000.0,
    end_date: str = "2027-12-31",
    backfilled: int = 0,
) -> None:
    db.execute(
        "INSERT OR IGNORE INTO snapshots "
        "(snap_date, market_id, event_id, interest, question, outcome, "
        "probability, volume_usd, end_date, backfilled) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (snap_date, market_id, event_id, interest, question, outcome,
         probability, volume_usd, end_date, backfilled),
    )
    db.commit()


def _seed_run_log(
    db: _sqlite3.Connection,
    phase: str,
    status: str,
    run_at: str,
) -> None:
    db.execute(
        "INSERT INTO run_log (run_at, phase, status) VALUES (?, ?, ?)",
        (run_at, phase, status),
    )
    db.commit()


def _fresh_db() -> _sqlite3.Connection:
    """Create a second in-memory DB for multi-scenario tests."""
    conn = _sqlite3.connect(":memory:")
    conn.row_factory = _sqlite3.Row
    conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    return conn


# ---------------------------------------------------------------------------
# Sprint 3 tests
# ---------------------------------------------------------------------------

def test_delta_24h(db):
    """Two snapshots 24h apart produce the correct delta_24h_pp."""
    from core.collector import collect

    # Pre-seed yesterday's snapshot
    _seed_snapshot(db, YESTERDAY, "m-agi", 0.18,
                   event_id="e-agi", interest="ai",
                   question="Will AGI arrive by 2028?", outcome="Yes")

    # Today's event at prob=0.24
    ev = _event(
        "e-agi", "Will AGI arrive by 2028?",
        [_market("m-agi", "Yes", 0.24, "https://p/agi")],
        volume=450_000,
        tags=[Tag(slug="artificial-intelligence", tag_id="305")],
    )
    adapter = _CollectorAdapter(events_by_tag={"305": [ev]})
    profile = _profile([_interest("ai", [{"slug": "artificial-intelligence", "tag_id": "305"}])])

    signals = collect(profile, adapter, db, TODAY)

    sig = next(s for s in signals["signals"] if s["event_id"] == "e-agi")
    outcome = next(o for o in sig["outcomes"] if o["outcome_label"] == "Yes")
    assert outcome["prob_24h_ago"] == pytest.approx(0.18, abs=0.001)
    assert outcome["delta_24h_pp"] == pytest.approx(6.0, abs=0.01)


def test_delta_7d_null(db):
    """Less than 7 days of history -> delta_7d_pp None; threshold_exceeded judged on 24h alone."""
    from core.collector import collect

    # Only a 24h snapshot (no 7d)
    _seed_snapshot(db, YESTERDAY, "m-agi", 0.18,
                   event_id="e-agi", interest="ai",
                   question="Will AGI arrive by 2028?", outcome="Yes")

    ev = _event(
        "e-agi", "Will AGI arrive by 2028?",
        [_market("m-agi", "Yes", 0.24)],
        tags=[Tag(slug="ai", tag_id="305")],
    )
    adapter = _CollectorAdapter(events_by_tag={"305": [ev]})
    profile = _profile([_interest("ai", [{"slug": "ai", "tag_id": "305"}], threshold_pp=5.0)])

    signals = collect(profile, adapter, db, TODAY)

    sig = next(s for s in signals["signals"] if s["event_id"] == "e-agi")
    outcome = next(o for o in sig["outcomes"] if o["outcome_label"] == "Yes")
    assert outcome["delta_7d_pp"] is None, "No 7d snapshot -> delta_7d_pp must be None"
    assert outcome["prob_7d_ago"] is None
    # 24h delta is 6pp >= threshold 5pp -> threshold_exceeded even without 7d
    assert sig["threshold_exceeded"] is True
    assert sig["threshold_triggered_by"] == "delta_24h"


def test_horizon_guard(db):
    """Markets with end_date < today+30 days are excluded; >=30 days are included."""
    from core.collector import collect

    tag = Tag(slug="ai", tag_id="305")
    short_event = _event(
        "e-short", "Expires soon",
        [_market("m-short", "Yes", 0.50)],
        end_date=_iso(29),  # 29 days -> EXCLUDED
        tags=[tag],
    )
    long_event = _event(
        "e-long", "Expires later",
        [_market("m-long", "Yes", 0.60)],
        end_date=_iso(31),  # 31 days -> INCLUDED
        tags=[tag],
    )

    adapter = _CollectorAdapter(events_by_tag={"305": [short_event, long_event]})
    profile = _profile([_interest("ai", [{"slug": "ai", "tag_id": "305"}])])

    collect(profile, adapter, db, TODAY)

    snap_market_ids = {
        r[0] for r in db.execute("SELECT market_id FROM snapshots").fetchall()
    }
    assert "m-long" in snap_market_ids, "31-day event must be included"
    assert "m-short" not in snap_market_ids, "29-day event must be excluded by horizon guard"


def test_max_markets_cap(db):
    """More candidates than max_markets -> only top-N by volume are written."""
    from core.collector import collect

    tag = Tag(slug="soccer", tag_id="204")
    # 5 events, volumes 1000–5000
    events = [
        _event(f"e-{i}", f"Soccer event {i}",
               [_market(f"m-{i}", "Yes", 0.50)],
               volume=float(i * 1000),
               end_date=_iso(60),
               tags=[tag])
        for i in range(1, 6)
    ]

    adapter = _CollectorAdapter(events_by_tag={"204": events})
    profile = _profile([_interest("soccer", [{"slug": "soccer", "tag_id": "204"}], max_markets=2)])

    collect(profile, adapter, db, TODAY)

    rows = db.execute(
        "SELECT DISTINCT event_id FROM snapshots WHERE interest='soccer'"
    ).fetchall()
    event_ids = {r[0] for r in rows}
    assert len(event_ids) == 2, f"Expected 2 events, got {len(event_ids)}: {event_ids}"
    assert "e-5" in event_ids, "Highest-volume event (e-5, 5000) must be included"
    assert "e-4" in event_ids, "Second-highest-volume event (e-4, 4000) must be included"
    assert "e-1" not in event_ids, "Lowest-volume event must be excluded"


def test_tag_degradation(db):
    """Stored tag returns empty -> keyword fallback -> empty -> interest auto-demoted to dormant;
    emits an active->dormant coverage transition."""
    from core.collector import collect

    # Rescan NOT triggered (scan 3 days ago)
    _seed_run_log(db, "dormant_scan", "ok", _iso(-3) + "T05:00:00")

    # Active interest with a tag that returns nothing
    profile = _profile([
        _interest("ai", [{"slug": "artificial-intelligence", "tag_id": "305"}],
                  status="active")
    ])
    # Adapter: empty for both events_by_tag and search
    adapter = _CollectorAdapter()

    signals = collect(profile, adapter, db, TODAY)

    # Interest must be demoted
    assert profile["interests"][0]["status"] == "dormant", (
        "Interest with no coverage must be auto-demoted to dormant"
    )
    # Transition active -> dormant must be emitted
    transitions = signals["coverage_transitions"]
    assert len(transitions) == 1
    assert transitions[0]["interest"] == "ai"
    assert transitions[0]["from"] == "active"
    assert transitions[0]["to"] == "dormant"
    # No events written to snapshots
    count = db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    assert count == 0


def test_reactivation(db):
    """Dormant interest gaining coverage emits a dormant->active transition."""
    from core.collector import collect

    # Rescan IS triggered (last scan 8 days ago)
    _seed_run_log(db, "dormant_scan", "ok", _iso(-8) + "T05:00:00")

    surf_event = _event(
        "e-surf", "Surfing championships",
        [_market("m-surf", "Yes", 0.60)],
        end_date=_iso(60),
        tags=[Tag(slug="surfing", tag_id="600")],
    )
    adapter = _CollectorAdapter(search_results=[surf_event])

    profile = _profile([
        _interest("surfing", [], status="dormant", keyword_fallback="surfing")
    ])

    signals = collect(profile, adapter, db, TODAY)

    assert profile["interests"][0]["status"] == "active", (
        "Dormant interest with coverage found must be promoted to active"
    )
    transitions = signals["coverage_transitions"]
    assert any(
        t["interest"] == "surfing" and t["from"] == "dormant" and t["to"] == "active"
        for t in transitions
    ), f"Expected dormant->active transition, got: {transitions}"


def test_dormant_rescan_trigger(db):
    """Dormant rescan triggers when days_since >= 7, not < 7 (weekday-independent)."""
    from core.collector import collect

    surf_event = _event(
        "e-surf", "Surfing championships",
        [_market("m-surf", "Yes", 0.60)],
        end_date=_iso(60),
    )
    adapter = _CollectorAdapter(search_results=[surf_event])

    # --- Scenario A: last scan 8 days ago -> TRIGGER -> dormant gets promoted ---
    _seed_run_log(db, "dormant_scan", "ok", _iso(-8) + "T05:00:00")
    profile_a = _profile([_interest("surfing", [], status="dormant")])

    collect(profile_a, adapter, db, TODAY)

    assert profile_a["interests"][0]["status"] == "active", (
        "Dormant interest must be promoted when days_since_last_successful_dormant_scan >= 7"
    )

    # --- Scenario B: last scan 3 days ago -> NO TRIGGER -> stays dormant ---
    conn_b = _fresh_db()
    try:
        _seed_run_log(conn_b, "dormant_scan", "ok", _iso(-3) + "T05:00:00")
        profile_b = _profile([_interest("surfing", [], status="dormant")])

        collect(profile_b, adapter, conn_b, TODAY)

        assert profile_b["interests"][0]["status"] == "dormant", (
            "Dormant interest must NOT be promoted when days_since < 7"
        )
    finally:
        conn_b.close()


def test_export_schema(db, tmp_path):
    """Exported JSON validates INTERFACES §2: nested outcomes, pp deltas, nullability,
    transitions present, standings present, file written to exports_dir."""
    from core.collector import collect

    # Pre-seed a 24h snapshot for non-null delta
    _seed_snapshot(db, YESTERDAY, "m-agi", 0.18,
                   event_id="e-agi", interest="ai",
                   question="Will AGI arrive by 2028?", outcome="Yes",
                   volume_usd=450_000, end_date="2028-12-31")

    # Active interest whose tag returns an event
    ev = _event(
        "e-agi", "Will AGI arrive by 2028?",
        [_market("m-agi", "Yes", 0.24, "https://polymarket.com/event/agi/yes")],
        volume=450_000,
        end_date="2028-12-31",
        tags=[Tag(slug="artificial-intelligence", tag_id="305")],
    )
    ai_int = _interest("ai", [{"slug": "artificial-intelligence", "tag_id": "305"}],
                        threshold_pp=5.0)

    # Dormant interest — no tag resolution, no rescan (scan 3 days ago)
    _seed_run_log(db, "dormant_scan", "ok", _iso(-3) + "T05:00:00")
    surfing_int = _interest("surfing", [], status="dormant")

    profile = _profile([ai_int, surfing_int])
    adapter = _CollectorAdapter(events_by_tag={"305": [ev]})

    signals = collect(profile, adapter, db, TODAY, exports_dir=tmp_path)

    # --- Top-level keys ---
    assert signals["schema_version"] == 1
    assert signals["source"] == "polymarket-gamma"
    assert isinstance(signals["generated_at"], str) and len(signals["generated_at"]) > 0
    assert isinstance(signals["coverage_transitions"], list)
    assert isinstance(signals["standings"], list)
    assert isinstance(signals["signals"], list)

    # --- signals[] outcome schema ---
    assert len(signals["signals"]) >= 1
    sig = next(s for s in signals["signals"] if s["event_id"] == "e-agi")
    assert sig["interest_tag"] == "ai"
    assert isinstance(sig["outcomes"], list) and len(sig["outcomes"]) >= 1
    assert isinstance(sig["threshold_pp"], float)
    assert isinstance(sig["threshold_exceeded"], bool)
    assert sig["threshold_triggered_by"] in ("delta_24h", "delta_7d", None)
    assert isinstance(sig["volume_usd"], (int, float))
    assert isinstance(sig["end_date"], str)

    outcome = next(o for o in sig["outcomes"] if o["outcome_label"] == "Yes")
    assert isinstance(outcome["market_id"], str)
    assert isinstance(outcome["url"], str)
    assert isinstance(outcome["prob_now"], float)
    assert outcome["prob_24h_ago"] == pytest.approx(0.18, abs=0.001)
    assert outcome["prob_7d_ago"] is None          # no 7d history -> None
    assert outcome["delta_24h_pp"] == pytest.approx(6.0, abs=0.01)
    assert outcome["delta_7d_pp"] is None

    # --- standings[] schema ---
    assert len(signals["standings"]) >= 1
    st = signals["standings"][0]
    assert "event_id" in st
    assert "event_title" in st
    assert "interest_tag" in st
    assert isinstance(st["is_binary"], bool)
    assert isinstance(st["top_outcomes"], list) and len(st["top_outcomes"]) >= 1
    top = st["top_outcomes"][0]
    assert "label" in top
    assert isinstance(top["prob_now"], float)
    assert "delta_24h_pp" in top   # key must exist; value may be None

    # --- File written ---
    out_file = tmp_path / f"{TODAY}.signals.json"
    assert out_file.exists(), f"Signals file not found at {out_file}"
    exported = json.loads(out_file.read_text(encoding="utf-8"))
    assert exported["schema_version"] == 1
    assert "standings" in exported
    assert "signals" in exported


def test_standings_built(db):
    """standings[] includes every watched active event; dormant absent; correct is_binary;
    top-3 for multi-outcome; primary for binary; delta_24h_pp nullable; reuses aggregate()."""
    from core.collector import collect

    today = TODAY

    # Pre-seed a 24h snapshot only for Spain (others have no history -> delta None)
    _seed_snapshot(db, YESTERDAY, "m-spain", 0.28,
                   event_id="e-wc", interest="soccer",
                   question="2026 World Cup", outcome="Spain",
                   volume_usd=5_000_000, end_date=_iso(60))

    # Soccer: multi-outcome World Cup (4 markets)
    wc_event = _event(
        "e-wc", "2026 World Cup",
        [
            _market("m-spain",    "Spain",     0.30, "https://x/spain"),
            _market("m-england",  "England",   0.20, "https://x/england"),
            _market("m-argentina","Argentina", 0.10, "https://x/argentina"),
            _market("m-france",   "France",    0.05, "https://x/france"),
        ],
        volume=5_000_000,
        end_date=_iso(60),
        tags=[Tag(slug="world-cup", tag_id="204")],
    )

    # Economy: binary (single Yes market)
    fed_event = _event(
        "e-fed", "Fed rate cut by September",
        [_market("m-fed-yes", "Yes", 0.68, "https://x/fed")],
        volume=2_000_000,
        end_date=_iso(90),
        tags=[Tag(slug="economy", tag_id="500")],
    )

    soccer_int  = _interest("soccer",  [{"slug": "world-cup", "tag_id": "204"}])
    economy_int = _interest("economy", [{"slug": "economy",   "tag_id": "500"}])
    surfing_int = _interest("surfing", [], status="dormant")

    profile  = _profile([soccer_int, economy_int, surfing_int])
    adapter  = _CollectorAdapter(events_by_tag={"204": [wc_event], "500": [fed_event]})

    # Suppress dormant rescan (recent scan)
    _seed_run_log(db, "dormant_scan", "ok", _iso(-3) + "T05:00:00")

    signals = collect(profile, adapter, db, today)
    standings = signals["standings"]

    event_ids = {s["event_id"] for s in standings}
    assert "e-wc"  in event_ids, "Soccer event must be in standings"
    assert "e-fed" in event_ids, "Economy event must be in standings"
    assert "e-surfing" not in event_ids, "Dormant interest must be absent from standings"

    # Verify no extra event_ids that aren't soccer/economy
    assert event_ids <= {"e-wc", "e-fed"}, f"Unexpected events in standings: {event_ids}"

    # Soccer: multi-outcome, top 3
    wc = next(s for s in standings if s["event_id"] == "e-wc")
    assert wc["is_binary"] is False
    assert len(wc["top_outcomes"]) == 3, f"Expected 3 top_outcomes, got {len(wc['top_outcomes'])}"
    assert wc["top_outcomes"][0]["label"] == "Spain"  # highest prob 0.30
    spain = wc["top_outcomes"][0]
    assert spain["prob_now"] == pytest.approx(0.30, abs=0.001)
    assert spain["delta_24h_pp"] == pytest.approx(2.0, abs=0.01)  # (0.30 - 0.28)*100

    england = next(o for o in wc["top_outcomes"] if o["label"] == "England")
    assert england["delta_24h_pp"] is None, "England has no 24h snapshot -> delta must be None"

    # Economy: binary, single primary
    fed = next(s for s in standings if s["event_id"] == "e-fed")
    assert fed["is_binary"] is True
    assert len(fed["top_outcomes"]) == 1
    assert fed["top_outcomes"][0]["label"] == "Yes"
    assert fed["top_outcomes"][0]["prob_now"] == pytest.approx(0.68, abs=0.001)


def test_backfill_flag(db):
    """Backfilled rows carry backfilled=1."""
    from core.collector import backfill_market

    price_history = {
        "m-agi": [
            PricePoint(timestamp="2026-06-10T05:00:00", price=0.20),
            PricePoint(timestamp="2026-06-11T05:00:00", price=0.22),
        ]
    }
    adapter = _CollectorAdapter(price_history=price_history)

    count = backfill_market(
        market_id="m-agi",
        adapter=adapter,
        db=db,
        interest="ai",
        event_id="e-agi",
        question="Will AGI arrive by 2028?",
        outcome="Yes",
        volume_usd=450_000,
        end_date="2028-12-31",
        from_date="2026-06-10",
        to_date=TODAY,
    )

    assert count == 2, f"Expected 2 rows backfilled, got {count}"

    rows = db.execute(
        "SELECT snap_date, backfilled FROM snapshots "
        "WHERE market_id='m-agi' ORDER BY snap_date"
    ).fetchall()
    assert len(rows) == 2
    assert all(r[1] == 1 for r in rows), (
        f"All backfilled rows must have backfilled=1; got: {[(r[0], r[1]) for r in rows]}"
    )


def test_threshold_triggered_by(db):
    """threshold_triggered_by is the window with the larger absolute delta."""
    from core.collector import collect

    # --- Case 1: delta_7d (18pp) > delta_24h (10pp) -> triggered_by = "delta_7d" ---
    _seed_snapshot(db, SEVEN_DAYS_AGO, "m-c1", 0.42,
                   event_id="e-c1", interest="ai", question="Q1?", outcome="Yes")
    _seed_snapshot(db, YESTERDAY, "m-c1", 0.50,
                   event_id="e-c1", interest="ai", question="Q1?", outcome="Yes")

    # --- Case 2: delta_24h (10pp) > delta_7d (3pp) -> triggered_by = "delta_24h" ---
    _seed_snapshot(db, SEVEN_DAYS_AGO, "m-c2", 0.57,
                   event_id="e-c2", interest="ai", question="Q2?", outcome="Yes")
    _seed_snapshot(db, YESTERDAY, "m-c2", 0.50,
                   event_id="e-c2", interest="ai", question="Q2?", outcome="Yes")

    ev1 = _event("e-c1", "Q1?", [_market("m-c1", "Yes", 0.60)],
                 tags=[Tag(slug="ai", tag_id="305")])
    ev2 = _event("e-c2", "Q2?", [_market("m-c2", "Yes", 0.60)],
                 tags=[Tag(slug="ai", tag_id="305")])

    adapter = _CollectorAdapter(events_by_tag={"305": [ev1, ev2]})
    profile = _profile([_interest("ai", [{"slug": "ai", "tag_id": "305"}], threshold_pp=2.0)])

    signals = collect(profile, adapter, db, TODAY)

    sig1 = next(s for s in signals["signals"] if s["event_id"] == "e-c1")
    assert sig1["threshold_triggered_by"] == "delta_7d", (
        f"delta_7d=18pp > delta_24h=10pp must trigger delta_7d, "
        f"got {sig1['threshold_triggered_by']}"
    )

    sig2 = next(s for s in signals["signals"] if s["event_id"] == "e-c2")
    assert sig2["threshold_triggered_by"] == "delta_24h", (
        f"delta_24h=10pp > delta_7d=3pp must trigger delta_24h, "
        f"got {sig2['threshold_triggered_by']}"
    )
