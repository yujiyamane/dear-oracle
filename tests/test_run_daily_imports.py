"""tests/test_run_daily_imports.py — smoke test: run_daily.py imports and main() runs end-to-end.

Zero live API or Claude calls: collect and write_interests_atomic are stubbed.
The letter pipeline was retired (2026-07-04) — main() ends after collect.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _fake_collect(profile, adapter, db, today, exports_dir=None):
    if exports_dir is not None:
        out_dir = Path(exports_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{today}.signals.json").write_text(
            json.dumps({"schema_version": 2, "signals": [], "standings": [], "coverage_transitions": []}),
            encoding="utf-8",
        )


def test_run_daily_has_no_letter_pipeline():
    import inspect

    from core import run_daily

    src = inspect.getsource(run_daily)
    assert "run_letter" not in src
    assert "drive_letters_path" not in src


def test_main_smoke(tmp_path, monkeypatch):
    with (
        patch("core.collector.collect", _fake_collect),
        patch("core.onboard.write_interests_atomic"),
    ):
        import core.run_daily as rd

        result = rd.main()

    assert result == 0

    log_file = PROJECT_ROOT / "data" / "logs" / "dear-oracle.log"
    assert log_file.exists(), "Log file was not created"
    content = log_file.read_text(encoding="utf-8")
    assert "END" in content, f"Expected 'END' in log, got tail: {content[-300:]}"
