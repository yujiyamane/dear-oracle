"""core/_claude_cli.py — shared `claude` CLI subprocess helper.

Two Windows gotchas found via live E2E dry runs (dk-do-v2-PLAN.md Phase 3 gate):

1. `claude` resolves to `claude.CMD` (an npm shim), and Python's subprocess
   module does NOT do PATHEXT resolution for a bare command name the way
   PowerShell's `&` or cmd.exe do -- subprocess.run(["claude", ...]) fails
   with WinError 2 ("cannot find the file specified") even though `claude`
   works fine from any interactive shell. Fix: resolve the full path once
   via shutil.which (mirrors dk-synthesis.ps1's own `Get-Command claude`).

2. subprocess.run(..., text=True) without an explicit `encoding=` decodes/
   encodes stdin/stdout using locale.getpreferredencoding() on Windows --
   typically cp1252, NOT UTF-8. Any non-ASCII in the prompt (Japanese
   keyperson names like "セイゴくん", the 【LOCAL/...】 badge convention, etc.)
   crashes with `'charmap' codec can't encode character ...`. This is the
   exact same root-cause class as DK's own B6 mojibake bug (dk-synthesis.ps1's
   Invoke-Claude had the identical problem with PowerShell's default
   encoding). Fix: pass encoding="utf-8" explicitly.
"""
from __future__ import annotations

import shutil
import subprocess

__all__ = ["call_claude_cli"]

_claude_path: str | None = None


def _resolve_claude_path() -> str:
    global _claude_path
    if _claude_path is None:
        resolved = shutil.which("claude")
        _claude_path = resolved or "claude"
    return _claude_path


def call_claude_cli(prompt: str, model: str, timeout_seconds: int = 30) -> str:
    """Pipe prompt to `claude -p --model <model>` via stdin, return stdout.
    Never raises for a missing/failing claude binary in a way callers can't
    catch -- subprocess.run's own exceptions (FileNotFoundError, TimeoutExpired,
    etc.) propagate normally; callers already wrap this in try/except."""
    exe = _resolve_claude_path()
    result = subprocess.run(
        [exe, "-p", "--model", model],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )
    return result.stdout
