#!/usr/bin/env python3
"""oracle.py — CLI entry point for Dear Oracle predictor.

Usage:
    python oracle.py "Who will win the 2026 World Cup?"
    python oracle.py "Will AGI be declared by end of 2027?"
    python oracle.py log record "<question>" <outcome_label> <user_prob> [--market-prob P]
    python oracle.py log list
    python oracle.py log resolve <id> <yes|no>
    python oracle.py log scores

Delegates entirely to core/predictor.py (prediction) and core/log.py (log).
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.predictor import predict, PredictorAnswer, ZeroResult, _render_answer, _render_zero


def _db_connect() -> sqlite3.Connection:
    db_path = Path(__file__).parent / "data" / "oracle.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).parent / "data" / "schema.sql"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    if schema_path.exists():
        conn.executescript(schema_path.read_text(encoding="utf-8"))
    return conn


def _main_log(args: list[str]) -> None:
    from core.log import record, list_open, resolve, scores

    parser = argparse.ArgumentParser(prog="oracle.py log")
    sub = parser.add_subparsers(dest="cmd", required=True)

    rec_p = sub.add_parser("record", help="Record a new prediction")
    rec_p.add_argument("question")
    rec_p.add_argument("outcome_label")
    rec_p.add_argument("user_prob", type=float)
    rec_p.add_argument("--market-prob", type=float, default=None, dest="market_prob")

    sub.add_parser("list", help="List open predictions")

    res_p = sub.add_parser("resolve", help="Resolve a prediction")
    res_p.add_argument("id", type=int)
    res_p.add_argument("outcome", choices=["yes", "no"])

    sub.add_parser("scores", help="Show calibration table for resolved predictions")

    ns = parser.parse_args(args)
    db = _db_connect()
    try:
        if ns.cmd == "record":
            pid = record(db, ns.question, ns.outcome_label, ns.user_prob, ns.market_prob)
            print(
                f"Recorded id={pid}: {ns.question!r} → {ns.outcome_label}"
                f" @ {ns.user_prob:.0%}"
                + (f"  (market {ns.market_prob:.0%})" if ns.market_prob is not None else "")
            )

        elif ns.cmd == "list":
            rows = list_open(db)
            if not rows:
                print("No open predictions.")
                return
            print(f"{'id':>4}  {'days':>4}  {'you':>6}  {'mkt':>6}  outcome   question")
            print("-" * 80)
            for r in rows:
                mkt = f"{r['market_prob']:.0%}" if r["market_prob"] is not None else "  —  "
                print(
                    f"{r['id']:>4}  {r['days_open']:>4}  {r['user_prob']:>5.0%}"
                    f"  {mkt:>6}  {r['outcome_label']:<9} {r['question']}"
                )

        elif ns.cmd == "resolve":
            occurred = ns.outcome == "yes"
            result = resolve(db, ns.id, occurred)
            outcome_str = "yes" if result["occurred"] else "no"
            print(
                f"Resolved id={ns.id}: outcome={outcome_str},"
                f" Brier={result['brier_score']:.4f}"
            )

        elif ns.cmd == "scores":
            result = scores(db)
            rows = result["rows"]
            if not rows:
                print("No resolved predictions yet.")
                return
            print(
                f"{'question':<40}  {'your p':>6}  {'mkt p':>6}"
                f"  {'outcome':>7}  {'Brier':>6}"
            )
            print("-" * 80)
            for r in rows:
                mkt = f"{r['market_prob']:.0%}" if r["market_prob"] is not None else "  —  "
                outcome_str = "yes" if r["occurred"] else "no"
                print(
                    f"{r['question'][:40]:<40}  {r['user_prob']:>5.0%}"
                    f"  {mkt:>6}  {outcome_str:>7}  {r['brier_score']:>6.4f}"
                )
            print()
            mu = result["mean_user_brier"]
            mm = result["mean_market_brier"]
            if mu is not None:
                print(f"Mean Brier — you:    {mu:.4f}")
            if mm is not None:
                print(f"Mean Brier — market: {mm:.4f}")
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python oracle.py "<question>"')
        print('       python oracle.py log record|list|resolve|scores ...')
        sys.exit(1)

    if sys.argv[1] == "log":
        _main_log(sys.argv[2:])
        return

    query = " ".join(sys.argv[1:])

    interests_path = str(Path(__file__).parent / "config" / "interests.json")

    result = predict(query, interests_path=interests_path)

    if isinstance(result, PredictorAnswer):
        _render_answer(result)
    else:
        _render_zero(result)


if __name__ == "__main__":
    main()
