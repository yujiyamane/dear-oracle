"""core/pipeline.py — Layer 2 Python wrapper around the claude -p letter step.

Public API
----------
preflight(claude_cmd="claude") -> bool
    Smoke-test the claude CLI. Returns True iff exit code is 0.

run_letter(signals_path, prompts_dir, exports_dir, db, today, claude_cmd="claude") -> dict
    Preflight -> claude -p (prompt+signals via stdin) -> extract JSON -> write html/txt.
    On any failure -> deterministic_fallback; logs ('letter', 'fallback').
    Returns {"html":..., "plaintext":..., "fallback": bool}.

deterministic_fallback(signals, db, today) -> dict
    Build a 3-line plaintext digest from standings[] / signals[].
    Returns {"html": "<p>...</p>", "plaintext": ..., "fallback": True}.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

MARKER_START = "---ORACLE-LETTER-START---"
MARKER_END   = "---ORACLE-LETTER-END---"

# Headless invocation flags — prevents any tool-permission prompt that would
# block the subprocess (subscription OAuth/keychain auth stays intact; do NOT
# use --bare which strictly requires ANTHROPIC_API_KEY and ignores keychain).
# Config-dir isolation (CLAUDE_CONFIG_DIR) would also break keychain auth, so
# we rely on flags only.  --tools "" disables all built-in tools (no prompts
# needed).  --permission-mode dontAsk is belt-and-suspenders.
# NOTE: --max-turns is NOT present in this CLI version (confirmed via --help).
_HEADLESS_FLAGS: list[str] = [
    "--output-format", "json",
    "--permission-mode", "dontAsk",
    "--tools", "",               # "" disables ALL built-in tools → no permission prompt
    "--disable-slash-commands",  # disable all skills / slash commands
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_argv(claude_cmd: str, *args: str) -> list[str]:
    """Build subprocess argv cross-platform.

    On Windows, .cmd/.bat npm shims can't be spawned without shell involvement;
    prefix with ["cmd", "/c"] so the shim resolves via cmd.exe PATH lookup.
    On POSIX, call the resolved binary directly.
    """
    resolved = shutil.which(claude_cmd) or claude_cmd
    if os.name == "nt":
        return ["cmd", "/c", resolved, *args]
    return [resolved, *args]


def _extract_envelope(stdout: str) -> dict | None:
    """Extract JSON envelope from stdout, tolerating Session Brief preamble.

    Strategy 1 — marker-based: substring between MARKER_START / MARKER_END lines.
    Strategy 2 — brace-based:  stdout[first '{' : last '}' + 1].
    Both must parse as JSON with 'html' and 'plaintext' keys; else return None.
    """
    # Strategy 1: explicit markers
    if MARKER_START in stdout and MARKER_END in stdout:
        start     = stdout.index(MARKER_START) + len(MARKER_START)
        end       = stdout.index(MARKER_END, start)
        candidate = stdout[start:end].strip()
        try:
            data = json.loads(candidate)
            if "html" in data and "plaintext" in data:
                return data
        except json.JSONDecodeError:
            pass

    # Strategy 2: first '{' to last '}'
    if "{" in stdout and "}" in stdout:
        candidate = stdout[stdout.index("{") : stdout.rindex("}") + 1]
        try:
            data = json.loads(candidate)
            if "html" in data and "plaintext" in data:
                return data
        except json.JSONDecodeError:
            pass

    return None


def _log(db, phase: str, status: str, detail: str | None = None) -> None:
    if db is None:
        return
    db.execute(
        "INSERT INTO run_log (run_at, phase, status, detail) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), phase, status, detail),
    )
    db.commit()


def _write_letter(envelope: dict, exports_dir, today: str) -> None:
    if exports_dir is None:
        return
    letters_dir = Path(exports_dir) / "letters"
    letters_dir.mkdir(parents=True, exist_ok=True)
    (letters_dir / f"{today}.html").write_text(envelope["html"],      encoding="utf-8")
    (letters_dir / f"{today}.txt" ).write_text(envelope["plaintext"], encoding="utf-8")


# ---------------------------------------------------------------------------
# Public: preflight
# ---------------------------------------------------------------------------

def preflight(claude_cmd: str = "claude") -> bool:
    """Run `claude -p "ping"` with headless flags; 30 s timeout.

    Returns True if exit code is 0, False on any failure or timeout.
    """
    try:
        result = subprocess.run(
            _build_argv(claude_cmd, "-p", "ping", *_HEADLESS_FLAGS),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public: deterministic_fallback
# ---------------------------------------------------------------------------

def deterministic_fallback(signals: dict, db, today: str) -> dict:
    """Build a 3-line plaintext-only letter from signals without AI.

    Line 1: biggest mover title + delta, or "Where things stand — <date>".
    Lines 2-3: top two standings.
    HTML: "<p>" + plaintext + "</p>".
    """
    standings     = signals.get("standings", [])
    signal_events = signals.get("signals",   [])

    # --- Line 1: biggest mover ---
    best_abs_delta: float | None = None
    line1: str | None = None

    for sig in signal_events:
        if not sig.get("threshold_exceeded"):
            continue
        for outcome in sig.get("outcomes", []):
            d24 = outcome.get("delta_24h_pp")
            if d24 is None:
                continue
            if best_abs_delta is None or abs(d24) > best_abs_delta:
                best_abs_delta = abs(d24)
                prob  = int(round(outcome["prob_now"] * 100))
                sign  = "+" if d24 > 0 else ""
                line1 = (
                    f"{sig['event_title']}  "
                    f"{prob}% ({sign}{int(d24)}pp in 24h)"
                )

    if line1 is None:
        line1 = f"Where things stand — {today}"

    # --- Lines 2-3: top standings ---
    standing_lines: list[str] = []
    for s in standings[:2]:
        tops = s.get("top_outcomes", [])
        if tops:
            top   = tops[0]
            prob  = int(round(top["prob_now"] * 100))
            delta = top.get("delta_24h_pp")
            if delta is not None:
                sign      = "+" if delta > 0 else ""
                delta_str = f" ({sign}{int(delta)}pp)"
            else:
                delta_str = ""
            standing_lines.append(
                f"{s['event_title']}    {top['label']} {prob}%{delta_str}"
            )

    while len(standing_lines) < 2:
        standing_lines.append("No markets to show")

    plaintext = line1 + "\n" + standing_lines[0] + "\n" + standing_lines[1]
    html      = "<p>" + plaintext + "</p>"

    return {"html": html, "plaintext": plaintext, "fallback": True}


# ---------------------------------------------------------------------------
# Public: run_letter
# ---------------------------------------------------------------------------

def run_letter(
    signals_path,
    prompts_dir,
    exports_dir,
    db,
    today: str,
    claude_cmd: str = "claude",
) -> dict:
    """Run the full Layer 2 pipeline step for one day.

    1. Preflight (`claude -p "ping"`): on failure -> fallback + log auth error.
    2. Read prompts/letter.md + signals JSON; pass combined as stdin to `claude -p`.
    3. Extract JSON from stdout via marker then brace strategy.
    4. Write html/txt to exports_dir/letters/<today>.{html,txt}.
    5. Log result to run_log.
    """
    signals_path = Path(signals_path)
    signals_text = signals_path.read_text(encoding="utf-8")
    signals      = json.loads(signals_text)

    # --- Preflight ---
    if not preflight(claude_cmd):
        _log(db, "auth", "error")
        result = deterministic_fallback(signals, db, today)
        _write_letter(result, exports_dir, today)
        return result

    _log(db, "auth", "ok")

    # --- Letter generation ---
    letter_text = (Path(prompts_dir) / "letter.md").read_text(encoding="utf-8")
    combined    = letter_text + "\n\n=== SIGNALS JSON ===\n" + signals_text

    try:
        proc = subprocess.run(
            _build_argv(claude_cmd, "-p", *_HEADLESS_FLAGS),
            input=combined,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude exited {proc.returncode}: {proc.stderr[:200]}"
            )

        # --output-format json wraps model output: {"type":"result","result":"<text>"}
        # Extract the model text first, then apply marker/brace extraction on it.
        try:
            cli_response = json.loads(proc.stdout)
            model_text   = cli_response["result"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ValueError(
                f"cli json parse failed "
                f"(len={len(proc.stdout)}): {proc.stdout[:300]!r}"
            ) from exc

        envelope = _extract_envelope(model_text)
        if envelope is None:
            raise ValueError(
                f"no parseable JSON in model output "
                f"(len={len(model_text)}): {model_text[:300]!r}"
            )

        output = {"html": envelope["html"], "plaintext": envelope["plaintext"], "fallback": False}
        _write_letter(output, exports_dir, today)
        _log(db, "letter", "ok")
        return output

    except (json.JSONDecodeError, RuntimeError, subprocess.TimeoutExpired, KeyError, ValueError) as exc:
        detail = str(exc)[:500]
        _log(db, "letter", "fallback", detail)
        result = deterministic_fallback(signals, db, today)
        _write_letter(result, exports_dir, today)
        return result
