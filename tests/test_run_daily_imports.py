"""tests/test_run_daily_imports.py — smoke test: run_daily.py imports and main() runs end-to-end.

Zero live API or Claude calls: collect, run_letter, and write_interests_atomic are all stubbed.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CANNED_ENVELOPE = {"html": "<p>x</p>", "plaintext": "a\nb\nc", "fallback": True}


def _fake_collect(profile, adapter, db, today, exports_dir=None):
    if exports_dir is not None:
        out_dir = Path(exports_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{today}.signals.json").write_text(
            json.dumps({"schema_version": 2, "signals": [], "standings": [], "coverage_transitions": []}),
            encoding="utf-8",
        )


def _fake_run_letter(signals_path, prompts_dir, exports_dir, db, today, **kwargs):
    letters_dir = Path(exports_dir) / "letters"
    letters_dir.mkdir(parents=True, exist_ok=True)
    (letters_dir / f"{today}.html").write_text("<p>x</p>", encoding="utf-8")
    (letters_dir / f"{today}.txt").write_text("a\nb\nc", encoding="utf-8")
    return CANNED_ENVELOPE


def test_main_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("DEAR_ORACLE_DRIVE_PATH", str(tmp_path))

    with (
        patch("core.collector.collect", _fake_collect),
        patch("core.pipeline.run_letter", _fake_run_letter),
        patch("core.onboard.write_interests_atomic"),
    ):
        import core.run_daily as rd

        result = rd.main()

    assert result == 0

    log_file = PROJECT_ROOT / "data" / "logs" / "dear-oracle.log"
    assert log_file.exists(), "Log file was not created"
    content = log_file.read_text(encoding="utf-8")
    assert "END" in content, f"Expected 'END' in log, got tail: {content[-300:]}"
