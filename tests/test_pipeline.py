"""tests/test_pipeline.py — Sprint 4 Phase A: dryRun E2E + fallback (ZERO Claude calls).

All tests inject canned envelopes; no subprocess is ever spawned for letter
generation — subprocess.run is mocked where needed.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.conftest import load_fixture

FIXTURES_DIR = Path(__file__).parent / "fixtures"
PROMPTS_DIR  = Path(__file__).parent.parent / "prompts"


# ---------------------------------------------------------------------------
# test_dryrun_one_mover
# ---------------------------------------------------------------------------

def test_dryrun_one_mover(db, tmp_path):
    """Canned one-mover envelope -> html+plaintext written; digest 3 lines non-empty;
    html contains 'Where things stand'."""
    from core.oracle_dryrun import dryrun

    envelope = json.loads((FIXTURES_DIR / "envelope_ok.json").read_text(encoding="utf-8"))
    signals  = load_fixture("signals_one_mover.json")

    result = dryrun(envelope, signals, tmp_path, db, "2026-06-13")

    assert "html" in result
    assert "plaintext" in result
    assert result.get("assertions_passed") is True

    lines = result["plaintext"].split("\n")
    assert len(lines) >= 3, "plaintext must have at least 3 lines"
    for i in range(3):
        assert lines[i].strip(), f"digest line {i + 1} is empty"

    assert "Where things stand" in result["html"]

    # Files must be written to exports_dir/letters/
    assert (tmp_path / "letters" / "2026-06-13.html").exists()
    assert (tmp_path / "letters" / "2026-06-13.txt").exists()


# ---------------------------------------------------------------------------
# test_fallback_on_malformed
# ---------------------------------------------------------------------------

def test_fallback_on_malformed(db, tmp_path):
    """Malformed stdout from claude -p -> deterministic fallback; run_log written;
    delivery still emits html + plaintext."""
    from core.pipeline import run_letter

    malformed    = (FIXTURES_DIR / "envelope_malformed.txt").read_text(encoding="utf-8")
    signals      = load_fixture("signals_one_mover.json")
    signals_path = tmp_path / "2026-06-13.signals.json"
    signals_path.write_text(json.dumps(signals), encoding="utf-8")

    preflight_ok  = SimpleNamespace(returncode=0, stdout="ok",       stderr="")
    letter_garble = SimpleNamespace(returncode=0, stdout=malformed,  stderr="")

    with patch("core.pipeline.subprocess.run", side_effect=[preflight_ok, letter_garble]):
        result = run_letter(signals_path, PROMPTS_DIR, tmp_path, db, "2026-06-13")

    assert result["fallback"] is True
    assert "html"      in result
    assert "plaintext" in result

    row = db.execute(
        "SELECT * FROM run_log WHERE phase='letter' AND status='fallback'"
    ).fetchone()
    assert row is not None, "run_log must have a (letter, fallback) entry"


# ---------------------------------------------------------------------------
# test_all_dormant_shortform
# ---------------------------------------------------------------------------

def test_all_dormant_shortform(db, tmp_path):
    """All-dormant signals -> oracle_dryrun produces output without crashing;
    standings[] is empty in the fixture."""
    from core.oracle_dryrun import dryrun

    signals  = load_fixture("signals_all_dormant.json")
    envelope = {
        "html":      "<p>Where things stand — all interests dormant</p>",
        "plaintext": "Where things stand — 2026-06-13\nNo markets to show\nAll interests currently dormant",
    }

    result = dryrun(envelope, signals, tmp_path, db, "2026-06-13")

    assert "html"      in result
    assert "plaintext" in result
    assert signals["standings"] == [], "signals_all_dormant must have empty standings"


# ---------------------------------------------------------------------------
# test_digest_extraction
# ---------------------------------------------------------------------------

def test_digest_extraction(db, tmp_path):
    """Digest = exactly the first 3 plaintext lines; each must be non-empty."""
    from core.oracle_dryrun import dryrun

    plaintext = (
        "AI moved past threshold: AGI Yes 24% (+6pp in 24h)\n"
        "Volume tripled overnight — conviction money, not noise\n"
        "Where things stand: AGI Yes 24%"
    )
    envelope = {"html": "<p>Where things stand</p>", "plaintext": plaintext}
    signals  = load_fixture("signals_one_mover.json")

    result = dryrun(envelope, signals, tmp_path, db, "2026-06-13")

    digest_lines = result["plaintext"].split("\n")[:3]
    assert len(digest_lines) == 3
    for line in digest_lines:
        assert line.strip(), f"digest line must not be empty, got: {line!r}"


# ---------------------------------------------------------------------------
# test_windows_posix_argv
# ---------------------------------------------------------------------------

def test_windows_posix_argv(monkeypatch):
    """Windows routes through cmd /c; POSIX calls the binary directly. Zero real Claude calls."""
    import core.pipeline as pipeline_mod

    # --- Windows ---
    monkeypatch.setattr(pipeline_mod.os, "name", "nt")
    monkeypatch.setattr(pipeline_mod.shutil, "which", lambda _cmd: r"C:\npm\claude.cmd")

    with patch("core.pipeline.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        pipeline_mod.preflight("claude")

    argv_nt = mock_run.call_args[0][0]
    assert argv_nt[0] == "cmd" and argv_nt[1] == "/c", (
        f"Windows must prefix with ['cmd', '/c'], got: {argv_nt}"
    )
    assert r"claude.cmd" in argv_nt[2]

    # --- POSIX ---
    monkeypatch.setattr(pipeline_mod.os, "name", "posix")
    monkeypatch.setattr(pipeline_mod.shutil, "which", lambda _cmd: "/usr/bin/claude")

    with patch("core.pipeline.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        pipeline_mod.preflight("claude")

    argv_posix = mock_run.call_args[0][0]
    assert argv_posix[0] == "/usr/bin/claude", (
        f"POSIX must call binary directly, got: {argv_posix}"
    )
    assert argv_posix[:2] != ["cmd", "/c"]


# ---------------------------------------------------------------------------
# test_subprocess_utf8_encoding
# ---------------------------------------------------------------------------

def test_subprocess_utf8_encoding(db, tmp_path):
    """Both subprocess.run calls (preflight + letter) must specify encoding='utf-8'."""
    from core.pipeline import run_letter

    signals      = load_fixture("signals_one_mover.json")
    signals_path = tmp_path / "2026-06-13.signals.json"
    signals_path.write_text(json.dumps(signals), encoding="utf-8")

    letter_json = '{"html": "<p>test</p>", "plaintext": "line1\\nline2\\nline3"}'
    stdout_ok   = f"---ORACLE-LETTER-START---\n{letter_json}\n---ORACLE-LETTER-END---\n"

    preflight_ok = SimpleNamespace(returncode=0, stdout="ok",      stderr="")
    letter_ok    = SimpleNamespace(returncode=0, stdout=stdout_ok, stderr="")

    with patch("core.pipeline.subprocess.run", side_effect=[preflight_ok, letter_ok]) as mock_run:
        run_letter(signals_path, PROMPTS_DIR, tmp_path, db, "2026-06-13")

    assert mock_run.call_count == 2, "expected exactly 2 subprocess.run calls"
    for i, call_obj in enumerate(mock_run.call_args_list):
        assert call_obj.kwargs.get("encoding") == "utf-8", (
            f"subprocess.run call {i} missing encoding='utf-8'; kwargs={call_obj.kwargs}"
        )


# ---------------------------------------------------------------------------
# test_letter_prompt_via_stdin
# ---------------------------------------------------------------------------

def test_letter_prompt_via_stdin(db, tmp_path):
    """run_letter passes prompt+signals as combined stdin; no .md path in argv."""
    from core.pipeline import run_letter

    signals      = load_fixture("signals_one_mover.json")
    signals_text = json.dumps(signals)
    signals_path = tmp_path / "2026-06-13.signals.json"
    signals_path.write_text(signals_text, encoding="utf-8")

    letter_text       = (PROMPTS_DIR / "letter.md").read_text(encoding="utf-8")
    expected_combined = letter_text + "\n\n=== SIGNALS JSON ===\n" + signals_text

    letter_json = '{"html": "<p>test</p>", "plaintext": "line1\\nline2\\nline3"}'
    stdout_ok   = f"---ORACLE-LETTER-START---\n{letter_json}\n---ORACLE-LETTER-END---\n"

    preflight_ok = SimpleNamespace(returncode=0, stdout="ok",      stderr="")
    letter_ok    = SimpleNamespace(returncode=0, stdout=stdout_ok, stderr="")

    with patch("core.pipeline.subprocess.run", side_effect=[preflight_ok, letter_ok]) as mock_run:
        run_letter(signals_path, PROMPTS_DIR, tmp_path, db, "2026-06-13")

    letter_call = mock_run.call_args_list[1]
    assert letter_call.kwargs.get("input") == expected_combined, (
        "input must be letter_text + separator + signals_text"
    )
    argv = letter_call.args[0]
    assert "-p" in argv, "argv must contain -p"
    assert not any(arg.endswith(".md") for arg in argv), (
        f"no .md file path expected in argv, got: {argv}"
    )


# ---------------------------------------------------------------------------
# test_extract_with_session_brief
# ---------------------------------------------------------------------------

def test_extract_with_session_brief(db, tmp_path):
    """Markers in preamble-noisy stdout (box chars + emoji) -> parses, fallback=False."""
    from core.pipeline import run_letter

    signals      = load_fixture("signals_one_mover.json")
    signals_path = tmp_path / "2026-06-13.signals.json"
    signals_path.write_text(json.dumps(signals), encoding="utf-8")

    session_brief_noise = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  📋 Session Brief\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "  ✅ Recent:\n"
        "  - [chore] Engine stabilisation\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    letter_json = '{"html": "<p>Where things stand</p>", "plaintext": "line1\\nline2\\nline3"}'
    stdout = (
        session_brief_noise
        + "---ORACLE-LETTER-START---\n"
        + letter_json + "\n"
        + "---ORACLE-LETTER-END---\n"
    )

    preflight_ok = SimpleNamespace(returncode=0, stdout="ok",    stderr="")
    letter_resp  = SimpleNamespace(returncode=0, stdout=stdout,  stderr="")

    with patch("core.pipeline.subprocess.run", side_effect=[preflight_ok, letter_resp]):
        result = run_letter(signals_path, PROMPTS_DIR, tmp_path, db, "2026-06-13")

    assert result["fallback"] is False
    assert result["html"] == "<p>Where things stand</p>"
    assert "line1" in result["plaintext"] and "line2" in result["plaintext"]


# ---------------------------------------------------------------------------
# test_extract_brace_fallback
# ---------------------------------------------------------------------------

def test_extract_brace_fallback(db, tmp_path):
    """No markers but valid JSON braces in stdout -> extracted correctly, fallback=False."""
    from core.pipeline import run_letter

    signals      = load_fixture("signals_one_mover.json")
    signals_path = tmp_path / "2026-06-13.signals.json"
    signals_path.write_text(json.dumps(signals), encoding="utf-8")

    letter_json = '{"html": "<p>Where things stand</p>", "plaintext": "line1\\nline2\\nline3"}'
    stdout      = f"Some preamble text\n{letter_json}\nsome postamble"

    preflight_ok = SimpleNamespace(returncode=0, stdout="ok",   stderr="")
    letter_resp  = SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    with patch("core.pipeline.subprocess.run", side_effect=[preflight_ok, letter_resp]):
        result = run_letter(signals_path, PROMPTS_DIR, tmp_path, db, "2026-06-13")

    assert result["fallback"] is False
    assert "html" in result and "plaintext" in result


# ---------------------------------------------------------------------------
# test_extract_unparseable
# ---------------------------------------------------------------------------

def test_extract_unparseable(db, tmp_path):
    """No parseable JSON in stdout at all -> deterministic fallback."""
    from core.pipeline import run_letter

    signals      = load_fixture("signals_one_mover.json")
    signals_path = tmp_path / "2026-06-13.signals.json"
    signals_path.write_text(json.dumps(signals), encoding="utf-8")

    stdout = "Sorry, I encountered an error. Please try again later."

    preflight_ok = SimpleNamespace(returncode=0, stdout="ok",   stderr="")
    letter_resp  = SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    with patch("core.pipeline.subprocess.run", side_effect=[preflight_ok, letter_resp]):
        result = run_letter(signals_path, PROMPTS_DIR, tmp_path, db, "2026-06-13")

    assert result["fallback"] is True
    assert "html" in result and "plaintext" in result
