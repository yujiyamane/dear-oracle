#!/usr/bin/env python3
"""oracle.py — CLI entry point for Dear Oracle predictor.

Usage:
    python oracle.py "Who will win the 2026 World Cup?"
    python oracle.py "Will AGI be declared by end of 2027?"

Delegates entirely to core/predictor.py.  interests.json is auto-loaded
from config/ if present; cold mode (no file) works on first clone.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.predictor import predict, PredictorAnswer, ZeroResult, _render_answer, _render_zero


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python oracle.py "<question>"')
        sys.exit(1)

    query = " ".join(sys.argv[1:])

    interests_path = str(Path(__file__).parent / "config" / "interests.json")

    result = predict(query, interests_path=interests_path)

    if isinstance(result, PredictorAnswer):
        _render_answer(result)
    else:
        _render_zero(result)


if __name__ == "__main__":
    main()
