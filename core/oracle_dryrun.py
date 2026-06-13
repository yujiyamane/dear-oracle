"""core/oracle_dryrun.py — test entry point that bypasses the claude -p call.

Port of DP_dryRun: inject a canned JSON envelope, run Layer 1->3 assertions,
write html/txt outputs. Zero Claude calls.
"""
from __future__ import annotations

from pathlib import Path


def dryrun(
    canned_envelope: dict,
    signals: dict,
    exports_dir,
    db,
    today: str,
) -> dict:
    """Bypass AI, inject canned_envelope as if claude -p had returned it.

    Parameters
    ----------
    canned_envelope : dict
        Pre-parsed {"html": ..., "plaintext": ...} as if returned by claude -p.
    signals : dict
        The day's market_signals[] (used for context; not re-parsed here).
    exports_dir : Path | str | None
        If not None, write <today>.html and <today>.txt under exports_dir/letters/.
    db : sqlite3.Connection | None
        Unused in dryrun (no run_log writes); accepted for API parity with run_letter.
    today : str
        "YYYY-MM-DD" reference date.

    Returns
    -------
    dict
        The envelope dict plus {"fallback": False, "assertions_passed": True}.
        Raises AssertionError if structural assertions fail.
    """
    assert "html"      in canned_envelope, "canned_envelope missing 'html' key"
    assert "plaintext" in canned_envelope, "canned_envelope missing 'plaintext' key"

    html      = canned_envelope["html"]
    plaintext = canned_envelope["plaintext"]

    # First 3 lines of plaintext must each be non-empty (these are the digest)
    lines = plaintext.split("\n")
    assert len(lines) >= 3, (
        f"plaintext must have at least 3 lines; got {len(lines)}: {lines!r}"
    )
    for i in range(3):
        assert lines[i].strip(), f"digest line {i + 1} is empty: {lines[i]!r}"

    # Write outputs
    if exports_dir is not None:
        letters_dir = Path(exports_dir) / "letters"
        letters_dir.mkdir(parents=True, exist_ok=True)
        (letters_dir / f"{today}.html").write_text(html,      encoding="utf-8")
        (letters_dir / f"{today}.txt" ).write_text(plaintext, encoding="utf-8")

    return {**canned_envelope, "fallback": False, "assertions_passed": True}
