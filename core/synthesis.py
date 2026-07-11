"""core/synthesis.py — DO v2 Sonnet so-what/then-what synthesis (dk-do-v2-PLAN.md
DO-V2-2 §"Each linked market shows... a two-layer prediction").

Amended design law: AI writes all prose; it never chooses which markets
survive (caps + veto gate already decided that upstream). This module's only
job is two sentences of conservative, grounded prose per surviving hit.

Voice mirrors dear-keyperson's own consequence-chain rules
(dk_synthesis_prompt.md `chain` section) so DO reads consistently with DK:
  - so_what: first-order world/market consequence, ONE sentence, conditional
    language ("likely"/"could"), never a certainty, never an instruction.
  - then_what: second-order, non-obvious knock-on effect, ONE sentence — the
    "no ordinary reader would surface this" bar (dk-do-v2-PLAN.md §2).
  - Grounded only in the given data; no invented facts; no financial advice
    or imperatives ("buy", "sell", "consider", "ask").

Model: Sonnet (per dk-do-v2-PLAN.md §4 "Model tiering" — second-order insight
is exactly where Haiku is weakest). Model string mirrors dk-synthesis.ps1's
documented Sonnet rollback target ("claude-sonnet-4-6").

On any call/parse failure returns ("", "") — the caller/render layer must
treat an empty-prose hit as "no synthesis available" (e.g. omit from render)
rather than crash; that behaviour lives in the caller, not here.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from core._claude_cli import call_claude_cli
from core.models import RealityCheckHit

log = logging.getLogger(__name__)

__all__ = ["synthesize_so_what_then_what"]

_MODEL = "claude-sonnet-4-6"
_TIMEOUT_SECONDS = 30

_EMPTY = ("", "")


def _real_call_claude(prompt: str, model: str) -> str:
    return call_claude_cli(prompt, model, _TIMEOUT_SECONDS)


def _build_prompt(news_item: dict, hit: RealityCheckHit) -> str:
    title = news_item.get("title", "")
    headlines = news_item.get("headlines", [])
    headlines_block = "\n".join(f"- {h}" for h in headlines)
    return (
        "You are writing a two-sentence consequence chain linking a news item to a "
        "prediction-market data point, in the same voice as dear-keyperson's "
        "consequence-chain mode.\n\n"
        f"News item title: {title}\n"
        f"News item headlines:\n{headlines_block}\n\n"
        f"Market: {hit.event_title}\n"
        f"Outcome: {hit.outcome_label}, probability now: {hit.prob_now}\n"
        f"24h change (pp): {hit.delta_24h_pp}\n"
        f"7d change (pp): {hit.delta_7d_pp}\n\n"
        "Write:\n"
        "- so_what: ONE sentence, the first-order world/market consequence. A "
        "conditional prediction ('likely', 'could'), never a certainty and never an "
        "instruction.\n"
        "- then_what: ONE sentence, the second-order, non-obvious knock-on effect — "
        "the kind of mechanism-driven insight (capital flows, supply chains, policy "
        "reactions, positioning) an ordinary reader would not surface on their own.\n\n"
        "Rules: conservative voice, grounded only in the data given above, no invented "
        "facts, no financial advice or imperatives (no 'buy'/'sell'/'consider'/'ask').\n\n"
        'Respond with ONLY strict JSON: {"so_what": "...", "then_what": "..."}. No '
        "markdown fences, no explanation outside the JSON."
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


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    return text[start : end + 1]


def synthesize_so_what_then_what(
    news_item: dict, hit: RealityCheckHit, call_claude: Callable[[str, str], str] | None = None
) -> tuple[str, str]:
    """Return (so_what, then_what) prose for a surviving RealityCheckHit.

    Never raises. On any call/parse failure returns ("", ""); the caller must
    handle an empty-prose hit gracefully (e.g. omit it from render).
    """
    caller = call_claude or _real_call_claude
    prompt = _build_prompt(news_item, hit)
    try:
        raw = caller(prompt, _MODEL)
    except Exception as exc:
        log.warning("synthesize_so_what_then_what: call_claude failed: %s", exc)
        return _EMPTY

    stripped = _strip_fences(raw or "")
    object_text = _extract_json_object(stripped)
    if object_text is None:
        log.warning("synthesize_so_what_then_what: no JSON object found in response: %r", (raw or "")[:200])
        return _EMPTY

    try:
        parsed = json.loads(object_text)
    except json.JSONDecodeError as exc:
        log.warning("synthesize_so_what_then_what: JSON decode failed (%s): %r", exc, object_text[:200])
        return _EMPTY

    if not isinstance(parsed, dict):
        log.warning("synthesize_so_what_then_what: parsed JSON is not an object: %r", parsed)
        return _EMPTY

    so_what = parsed.get("so_what")
    then_what = parsed.get("then_what")
    if not isinstance(so_what, str) or not isinstance(then_what, str):
        log.warning("synthesize_so_what_then_what: missing/non-string so_what/then_what: %r", parsed)
        return _EMPTY

    return so_what, then_what
