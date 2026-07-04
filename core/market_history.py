"""core/market_history.py — 7-day probability history carried inside do_hits.json.

No database: scan() reads the previous do_hits.json at out_path before
overwriting it, and each market's history rides along in the file itself.

load_prev_history(path) -> (dict[url, history], prev_date_syd)
attach_history(items, prev, date_syd, prev_date) -> None (mutates items)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

HISTORY_CAP = 7


def load_prev_history(path: Path) -> tuple[dict[str, list[float]], str]:
    """Collect {url: history} from an existing do_hits.json; ({}, '') on any failure.

    Items without a stored history fall back to [prob_now] so a sparkline can
    start from the first day the previous file existed.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}, ""

    prev: dict[str, list[float]] = {}

    def _collect(item: dict) -> None:
        url = item.get("url")
        if not url:
            return
        history = item.get("history")
        if not isinstance(history, list) or not history:
            prob = item.get("prob_now")
            if prob is None:
                return
            history = [prob]
        prev[url] = [float(p) for p in history]

    for markets in (data.get("hits") or {}).values():
        if isinstance(markets, list):
            for m in markets:
                if isinstance(m, dict):
                    _collect(m)
    for m in data.get("pool") or []:
        if isinstance(m, dict):
            _collect(m)

    prev_date = str((data.get("meta") or {}).get("date_syd") or "")
    return prev, prev_date


def attach_history(
    items: list[dict],
    prev: dict[str, list[float]],
    date_syd: str,
    prev_date: str,
) -> None:
    """Set item['history'] = prior history + today's prob_now, capped at HISTORY_CAP.

    Same-day re-runs (date_syd == prev_date) replace the last point instead of
    appending, so manual re-scans stay idempotent.
    """
    same_day = bool(prev_date) and date_syd == prev_date
    for item in items:
        url = item.get("url")
        prob = item.get("prob_now")
        if not url or prob is None:
            continue
        history = list(prev.get(url, []))
        if same_day and history:
            history[-1] = float(prob)
        else:
            history.append(float(prob))
        item["history"] = history[-HISTORY_CAP:]
