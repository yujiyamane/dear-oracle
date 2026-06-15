"""core/log.py — prediction_log CRUD for oracle-log subcommand.

All operations are deterministic: pure SQLite, no network, no AI.
"""
import sqlite3
from datetime import datetime

from core.brier import binary_brier


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def record(
    db: sqlite3.Connection,
    question: str,
    outcome_label: str,
    user_prob: float,
    market_prob: float | None,
) -> int:
    """Insert an open prediction; return the new row id."""
    cur = db.execute(
        """
        INSERT INTO prediction_log
          (question, outcome_label, user_prob, market_prob, recorded_at, status)
        VALUES (?, ?, ?, ?, ?, 'open')
        """,
        (question, outcome_label, user_prob, market_prob, _now_iso()),
    )
    db.commit()
    return cur.lastrowid


def list_open(db: sqlite3.Connection) -> list[dict]:
    """Return all open predictions, each with a computed days_open field."""
    rows = db.execute(
        "SELECT * FROM prediction_log WHERE status = 'open' ORDER BY recorded_at"
    ).fetchall()
    now = datetime.now().astimezone()
    result = []
    for row in rows:
        d = dict(row)
        try:
            rec = datetime.fromisoformat(d["recorded_at"])
            d["days_open"] = (now - rec).days
        except (ValueError, TypeError):
            d["days_open"] = None
        result.append(d)
    return result


def resolve(db: sqlite3.Connection, prediction_id: int, occurred: bool) -> dict:
    """Mark a prediction resolved; compute binary Brier score.

    Raises ValueError if not found or already resolved.
    """
    row = db.execute(
        "SELECT * FROM prediction_log WHERE id = ?", (prediction_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Prediction id={prediction_id} not found.")
    d = dict(row)
    if d["status"] == "resolved":
        raise ValueError(f"Prediction id={prediction_id} is already resolved.")

    score = binary_brier(d["user_prob"], occurred)
    resolved_at = _now_iso()
    db.execute(
        """
        UPDATE prediction_log
           SET status = 'resolved',
               occurred = ?,
               brier_score = ?,
               resolved_at = ?
         WHERE id = ?
        """,
        (1 if occurred else 0, score, resolved_at, prediction_id),
    )
    db.commit()
    return {
        **d,
        "status": "resolved",
        "occurred": 1 if occurred else 0,
        "brier_score": score,
        "resolved_at": resolved_at,
    }


def scores(db: sqlite3.Connection) -> dict:
    """Return resolved rows with per-row market Brier and aggregate means.

    Returns:
        {
            "rows": list[dict],        # each row gains a "market_brier" key
            "mean_user_brier": float | None,
            "mean_market_brier": float | None,  # only over rows with market_prob
        }
    """
    rows = db.execute(
        "SELECT * FROM prediction_log WHERE status = 'resolved' ORDER BY resolved_at"
    ).fetchall()

    result_rows: list[dict] = []
    user_briers: list[float] = []
    market_briers: list[float] = []

    for row in rows:
        d = dict(row)
        user_briers.append(d["brier_score"])
        if d["market_prob"] is not None:
            mb = binary_brier(d["market_prob"], bool(d["occurred"]))
            d["market_brier"] = mb
            market_briers.append(mb)
        else:
            d["market_brier"] = None
        result_rows.append(d)

    mean_user = sum(user_briers) / len(user_briers) if user_briers else None
    mean_market = sum(market_briers) / len(market_briers) if market_briers else None

    return {
        "rows": result_rows,
        "mean_user_brier": mean_user,
        "mean_market_brier": mean_market,
    }
