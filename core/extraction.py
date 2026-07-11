"""core/extraction.py — DO v2 Haiku query-variant extraction (dk-do-v2-PLAN.md DO-V2-2 step 1).

Amended design law: code retrieves and hard-filters candidates; AI may only
veto; AI never adds candidates. This module's AI call produces SEARCH QUERIES
only — short entity/keyword strings handed to Polymarket's /public-search.
The actual candidate Events still come from code-driven search
(core.reality_check.search_query_variants) + code-side hard filters
(core.reality_check.hard_filter_events). Extraction never selects a market.

Model: Haiku (claude-haiku-4-5-20251001), mirroring dk-synthesis.ps1's
Invoke-Claude pattern — prompt piped via stdin to `claude -p --model <model>`.
"""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Callable

log = logging.getLogger(__name__)

__all__ = ["extract_query_variants"]

_MODEL = "claude-haiku-4-5-20251001"
_MAX_VARIANTS = 3
_TIMEOUT_SECONDS = 30


def _real_call_claude(prompt: str, model: str) -> str:
    """Subprocess call to the `claude` CLI, prompt piped via stdin. Mirrors
    dk-synthesis.ps1's Invoke-Claude: never raises — caller handles failure."""
    result = subprocess.run(
        ["claude", "-p", "--model", model],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )
    return result.stdout


def _build_prompt(news_item: dict) -> str:
    title = news_item.get("title", "")
    headlines = news_item.get("headlines", [])
    headlines_block = "\n".join(f"- {h}" for h in headlines)
    return (
        "You are extracting short search queries for Polymarket's prediction-market "
        "search endpoint from a news cluster.\n\n"
        f"News item title: {title}\n"
        f"Constituent headlines:\n{headlines_block}\n\n"
        "Return 2-3 short search queries (entities/keywords, NOT full sentences) that "
        "would find prediction markets genuinely about the same real-world event or topic "
        "as this news item.\n\n"
        "Respond with ONLY a JSON array of 2-3 short strings. No markdown fences, no "
        "explanation, no extra text — just the JSON array."
    )


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _extract_json_array(text: str) -> str | None:
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    return text[start : end + 1]


def _parse_variants(raw: str) -> list[str]:
    if not raw or not raw.strip():
        return []
    stripped = _strip_fences(raw)

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        # Whole response wasn't valid JSON on its own (e.g. surrounded by stray
        # prose) — try to salvage a JSON array substring.
        array_text = _extract_json_array(stripped)
        if array_text is None:
            log.warning("extract_query_variants: no JSON array found in response: %r", raw[:200])
            return []
        try:
            parsed = json.loads(array_text)
        except json.JSONDecodeError as exc:
            log.warning("extract_query_variants: JSON decode failed (%s): %r", exc, array_text[:200])
            return []

    if not isinstance(parsed, list):
        log.warning("extract_query_variants: parsed JSON is not a list: %r", parsed)
        return []
    if not all(isinstance(item, str) for item in parsed):
        log.warning("extract_query_variants: non-string item in query list: %r", parsed)
        return []
    return parsed[:_MAX_VARIANTS]


def extract_query_variants(
    news_item: dict, call_claude: Callable[[str, str], str] | None = None
) -> list[str]:
    """Return 2-3 short Polymarket search-query strings for this news cluster.

    news_item shape: {"id": str, "title": str, "headlines": list[str]}.
    Never raises — any call/parse failure logs and returns [].
    """
    caller = call_claude or _real_call_claude
    prompt = _build_prompt(news_item)
    try:
        raw = caller(prompt, _MODEL)
    except Exception as exc:
        log.warning("extract_query_variants: call_claude failed: %s", exc)
        return []
    return _parse_variants(raw)
