"""tests/test_prompt_lint.py — static prompt guardrail checks (Sprint 4, every commit).

Runs with zero Claude calls. Reads prompts/*.md directly.
"""
import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

CANONICAL_VOICE = (
    "> You report what the market is pricing. You do not recommend positions,\n"
    "> you do not predict outcomes yourself, and you never use imperative\n"
    "> language about money, trades, or bets. Probabilities belong to the\n"
    "> crowd; you are the messenger.\n"
    "> If web search returns no credible reporting for a movement, SKIP the\n"
    '> why-section for that market and say so plainly ("the crowd moved;\n'
    '> no reliable reporting found") — never fabricate an explanation.'
)

PROHIBITED = re.compile(r"\b(buy|sell|invest|bet|position)\b", re.IGNORECASE)


def _prompt_files():
    return sorted(PROMPTS_DIR.glob("*.md"))


def test_voice_block_verbatim():
    """Every prompts/*.md must contain the conservative-voice block byte-for-byte."""
    files = _prompt_files()
    assert files, "No prompt files found — check PROMPTS_DIR"

    missing = [f.name for f in files if CANONICAL_VOICE not in f.read_text(encoding="utf-8")]
    assert not missing, (
        f"Conservative-voice block missing from: {missing}\n"
        f"Expected verbatim:\n{CANONICAL_VOICE}"
    )


def test_no_prohibited_tokens():
    """No prompts/*.md body contains buy|sell|invest|bet|position outside the guardrail."""
    files = _prompt_files()
    assert files, "No prompt files found"

    violations = []
    for f in files:
        content = f.read_text(encoding="utf-8")
        # Strip the guardrail block itself before scanning
        body = content.replace(CANONICAL_VOICE, "")
        match = PROHIBITED.search(body)
        if match:
            violations.append(f"{f.name}: found '{match.group()}' at pos {match.start()}")

    assert not violations, "Prohibited tokens found outside guardrail:\n" + "\n".join(violations)
