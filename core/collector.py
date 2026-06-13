"""core/collector.py — Layer 1 data collector (Sprint 3, pure code, zero AI).

Public API:
  collect(profile, adapter, db, today, exports_dir=None) -> dict
      Run one day's collection.  Resolves each interest's tags (tag-first,
      keyword fallback, horizon guard, max_markets cap), inserts snapshots,
      computes 24h/7d deltas via SQL, detects threshold crossings, builds
      standings[] for ALL active events, detects coverage transitions, and
      exports the day's market_signals[] JSON dict.
      Modifies profile["interests"][*]["status"] in place on demotion/promotion.

  backfill_market(market_id, adapter, db, interest, event_id, question,
                  outcome, volume_usd, end_date, from_date, to_date) -> int
      Insert missed days from CLOB prices_history, marked backfilled=1.
      Returns number of rows inserted.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.models import Event, Market, Tag
from core.resolve import aggregate


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _days_since(past_date: str, today: str) -> int:
    """Calendar days between past_date and today (both YYYY-MM-DD)."""
    return (date.fromisoformat(today) - date.fromisoformat(past_date)).days


def _dormant_rescan_needed(db: sqlite3.Connection, today: str) -> bool:
    """Return True when the last successful dormant scan was >= 7 days ago (or never)."""
    row = db.execute(
        "SELECT run_at FROM run_log "
        "WHERE phase='dormant_scan' AND status='ok' "
        "ORDER BY run_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return True
    last_date = str(row[0])[:10]
    return _days_since(last_date, today) >= 7


def _horizon_ok(event: Event, today: str) -> bool:
    """Return True if event.end_date >= today + 30 days."""
    if not event.end_date:
        return False
    try:
        cutoff = date.fromisoformat(today) + timedelta(days=30)
        return date.fromisoformat(event.end_date) >= cutoff
    except ValueError:
        return False


def _resolve_via_tags(interest: dict, adapter: Any) -> list[Event]:
    """Resolve using stored tag_ids (tag-first path)."""
    events: list[Event] = []
    seen: set[str] = set()
    for tag in interest.get("resolved_tags", []):
        for ev in adapter.events_by_tag(tag["tag_id"]):
            if ev.event_id not in seen:
                events.append(ev)
                seen.add(ev.event_id)
    return events


def _resolve_via_keyword(interest: dict, adapter: Any) -> list[Event]:
    """Keyword fallback when tags return nothing."""
    kw = interest.get("keyword_fallback") or interest["name"]
    return list(adapter.search(kw))


def _insert_snapshot(
    db: sqlite3.Connection,
    snap_date: str,
    market: Market,
    event_id: str,
    interest_name: str,
    event_title: str,
    volume_usd: float | None,
    end_date: str | None,
    backfilled: int = 0,
) -> None:
    db.execute(
        "INSERT OR IGNORE INTO snapshots "
        "(snap_date, market_id, event_id, interest, question, outcome, "
        "probability, volume_usd, end_date, backfilled) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            snap_date, market.market_id, event_id, interest_name,
            event_title, market.outcome_label, market.prob_now,
            volume_usd, end_date, backfilled,
        ),
    )


def _compute_deltas(
    db: sqlite3.Connection,
    market_id: str,
    today: str,
) -> tuple[float | None, float | None]:
    """Return (prob_24h_ago, prob_7d_ago) from snapshots table.

    Both are None when the corresponding historical row is absent
    (day 1 / short history).
    """
    row = db.execute(
        """
        SELECT
            h24.probability  AS prob_24h,
            h7d.probability  AS prob_7d
        FROM snapshots s
        LEFT JOIN snapshots h24
            ON  h24.market_id = s.market_id
            AND h24.snap_date  = date(s.snap_date, '-1 day')
        LEFT JOIN snapshots h7d
            ON  h7d.market_id = s.market_id
            AND h7d.snap_date  = date(s.snap_date, '-7 day')
        WHERE s.market_id = ? AND s.snap_date = ?
        """,
        (market_id, today),
    ).fetchone()
    if row is None:
        return None, None
    return row[0], row[1]


def _pp(prob_old: float | None, prob_new: float) -> float | None:
    """(prob_new - prob_old) * 100, or None if prob_old is None."""
    if prob_old is None:
        return None
    return round((prob_new - prob_old) * 100, 4)


def _build_signal(
    ev: Event,
    interest_name: str,
    threshold_pp: float,
    db: sqlite3.Connection,
    today: str,
) -> dict:
    """Build one signals[] entry for ev, including delta computation."""
    outcomes_data: list[dict] = []

    for mkt in ev.markets:
        prob_24h, prob_7d = _compute_deltas(db, mkt.market_id, today)
        delta_24h = _pp(prob_24h, mkt.prob_now)
        delta_7d = _pp(prob_7d, mkt.prob_now)
        outcomes_data.append(
            {
                "outcome_label": mkt.outcome_label,
                "market_id":     mkt.market_id,
                "url":           mkt.url,
                "prob_now":      mkt.prob_now,
                "prob_24h_ago":  prob_24h,
                "prob_7d_ago":   prob_7d,
                "delta_24h_pp":  delta_24h,
                "delta_7d_pp":   delta_7d,
            }
        )

    # Max absolute delta across all outcomes and both windows
    abs_24h = [abs(o["delta_24h_pp"]) for o in outcomes_data if o["delta_24h_pp"] is not None]
    abs_7d  = [abs(o["delta_7d_pp"])  for o in outcomes_data if o["delta_7d_pp"]  is not None]

    max_24h: float | None = max(abs_24h) if abs_24h else None
    max_7d:  float | None = max(abs_7d)  if abs_7d  else None

    all_abs = (abs_24h + abs_7d)
    threshold_exceeded = bool(all_abs) and max(all_abs) >= threshold_pp

    # threshold_triggered_by: the window with the larger |delta|
    if max_24h is not None and max_7d is not None:
        triggered_by: str | None = "delta_24h" if max_24h >= max_7d else "delta_7d"
    elif max_24h is not None:
        triggered_by = "delta_24h"
    elif max_7d is not None:
        triggered_by = "delta_7d"
    else:
        triggered_by = None

    return {
        "event_id":            ev.event_id,
        "event_title":         ev.event_title,
        "interest_tag":        interest_name,
        "outcomes":            outcomes_data,
        "threshold_pp":        threshold_pp,
        "threshold_exceeded":  threshold_exceeded,
        "threshold_triggered_by": triggered_by,
        "volume_usd":          ev.volume_usd or 0.0,
        "end_date":            ev.end_date or "",
    }


def _build_standing(
    ev: Event,
    interest_name: str,
    db: sqlite3.Connection,
    today: str,
) -> dict:
    """Build one standings[] entry using aggregate() for sorting."""
    is_binary = len(ev.markets) == 1

    # Sort via aggregate() (prob desc, Field remainder appended)
    agg_outcomes = aggregate(ev)

    market_by_label = {m.outcome_label: m for m in ev.markets}
    top_outcomes_raw: list[dict] = []

    for agg_o in agg_outcomes:
        if agg_o.label == "Field":
            continue
        mkt = market_by_label.get(agg_o.label)
        if mkt is None:
            continue
        prob_24h, _ = _compute_deltas(db, mkt.market_id, today)
        delta_24h = _pp(prob_24h, mkt.prob_now)
        top_outcomes_raw.append(
            {
                "label":        agg_o.label,
                "prob_now":     mkt.prob_now,
                "delta_24h_pp": delta_24h,
            }
        )

    top = top_outcomes_raw[:1] if is_binary else top_outcomes_raw[:3]

    return {
        "event_id":     ev.event_id,
        "event_title":  ev.event_title,
        "interest_tag": interest_name,
        "is_binary":    is_binary,
        "top_outcomes": top,
    }


# ---------------------------------------------------------------------------
# Public: collect
# ---------------------------------------------------------------------------

def collect(
    profile: dict,
    adapter: Any,
    db: sqlite3.Connection,
    today: str,
    exports_dir: Path | str | None = None,
) -> dict:
    """Run one day's collection and return the market_signals[] dict.

    Modifies profile["interests"][*]["status"] in place when an interest is
    demoted to dormant (tag + keyword both fail) or promoted to active
    (dormant re-scan finds coverage).

    Parameters
    ----------
    profile:     interests.json loaded as a dict
    adapter:     any object satisfying the MarketAdapter protocol
    db:          open SQLite connection (in-memory or file)
    today:       "YYYY-MM-DD" reference date for all queries
    exports_dir: if not None, write <today>.signals.json here
    """
    interests: list[dict] = profile.get("interests", [])

    # Capture starting statuses for transition detection
    starting_statuses: dict[str, str] = {i["name"]: i["status"] for i in interests}

    # Determine whether dormant re-scan should run this cycle
    do_rescan = _dormant_rescan_needed(db, today)

    # active_events[interest_name] -> events written today
    active_events: dict[str, list[Event]] = {}

    for interest in interests:
        name     = interest["name"]
        status   = interest["status"]
        max_m    = interest.get("max_markets", 5)

        if status == "active":
            # 1. Tag-first resolution
            events = _resolve_via_tags(interest, adapter)
            # 2. Keyword fallback if tags empty
            if not events:
                events = _resolve_via_keyword(interest, adapter)
            # 3. Horizon guard
            events = [e for e in events if _horizon_ok(e, today)]

            if not events:
                # Degrade to dormant — no markets survive
                interest["status"] = "dormant"
                active_events[name] = []
                continue

            # 4. Cap at max_markets, volume-sorted descending
            chosen = sorted(events, key=lambda e: (e.volume_usd or 0.0), reverse=True)[:max_m]

            # 5. Insert today's snapshots
            for ev in chosen:
                for mkt in ev.markets:
                    _insert_snapshot(db, today, mkt, ev.event_id, name,
                                     ev.event_title, ev.volume_usd, ev.end_date)
            db.commit()
            active_events[name] = chosen

        elif status == "dormant" and do_rescan:
            # Dormant re-scan: try keyword path
            kw = interest.get("keyword_fallback") or name
            events = [e for e in adapter.search(kw) if _horizon_ok(e, today)]

            if events:
                # Promote to active
                interest["status"] = "active"
                chosen = sorted(events, key=lambda e: (e.volume_usd or 0.0), reverse=True)[:max_m]
                # Refresh resolved_tags from found events
                tag_map: dict[str, dict] = {}
                for ev in chosen:
                    for tag in ev.tags:
                        tag_map[tag.tag_id] = {"slug": tag.slug, "tag_id": tag.tag_id}
                interest["resolved_tags"] = list(tag_map.values())
                for ev in chosen:
                    for mkt in ev.markets:
                        _insert_snapshot(db, today, mkt, ev.event_id, name,
                                         ev.event_title, ev.volume_usd, ev.end_date)
                db.commit()
                active_events[name] = chosen
            else:
                active_events[name] = []
        else:
            active_events[name] = []

    # Log dormant scan if it ran
    if do_rescan:
        db.execute(
            "INSERT INTO run_log (run_at, phase, status) VALUES (?, 'dormant_scan', 'ok')",
            (today + "T00:00:00",),
        )
        db.commit()

    # Build signals[] for all active events
    signals_list: list[dict] = []
    for interest in interests:
        name         = interest["name"]
        threshold    = interest.get("threshold_pp", 5.0)
        events_today = active_events.get(name, [])
        for ev in events_today:
            signals_list.append(_build_signal(ev, name, threshold, db, today))

    # Build standings[] for all active events (dormant absent)
    standings_list: list[dict] = []
    for interest in interests:
        name = interest["name"]
        if interest["status"] != "active":
            continue
        for ev in active_events.get(name, []):
            standings_list.append(_build_standing(ev, name, db, today))

    # Coverage transitions (starting status vs final status)
    transitions: list[dict] = []
    for interest in interests:
        name = interest["name"]
        old  = starting_statuses.get(name)
        new  = interest["status"]
        if old != new:
            transitions.append({"interest": name, "from": old, "to": new})

    result: dict = {
        "schema_version":      1,
        "source":              "polymarket-gamma",
        "generated_at":        datetime.now().astimezone().isoformat(timespec="seconds"),
        "coverage_transitions": transitions,
        "standings":           standings_list,
        "signals":             signals_list,
    }

    # Export JSON
    if exports_dir is not None:
        out_dir = Path(exports_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{today}.signals.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return result


# ---------------------------------------------------------------------------
# Public: backfill_market
# ---------------------------------------------------------------------------

def backfill_market(
    market_id: str,
    adapter: Any,
    db: sqlite3.Connection,
    interest: str,
    event_id: str,
    question: str,
    outcome: str,
    volume_usd: float | None,
    end_date: str | None,
    from_date: str,
    to_date: str,
) -> int:
    """Insert missed days from CLOB prices_history, marked backfilled=1.

    Uses adapter.prices_history(market_id, from_date) to retrieve price
    points, then inserts one row per calendar date in [from_date, to_date).
    Returns the number of rows successfully inserted.
    """
    price_points = adapter.prices_history(market_id, from_date)
    count = 0
    for pp in price_points:
        snap_date = str(pp.timestamp)[:10]
        if snap_date < from_date or snap_date >= to_date:
            continue
        db.execute(
            "INSERT OR IGNORE INTO snapshots "
            "(snap_date, market_id, event_id, interest, question, outcome, "
            "probability, volume_usd, end_date, backfilled) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (snap_date, market_id, event_id, interest, question, outcome,
             pp.price, volume_usd, end_date),
        )
        count += 1
    db.commit()
    return count
