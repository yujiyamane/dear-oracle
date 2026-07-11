"""core/veto_gate.py — DO v2 AI relevance veto gate (dk-do-v2-PLAN.md DO-V2-2 §4).

Amended design law: code retrieves and hard-filters candidates; AI may only
VETO (binary relevance verdict, reason logged); AI never adds candidates.
Hard filters (active/closed/volume/liquidity/horizon) already ran upstream in
core.reality_check.hard_filter_events — this module's only job is a binary
yes/no on an already-admitted candidate.

Guards against the CHS ("Capitol Hill Seattle News") false-match bug class
from DK's own history: a market can share keywords/an outlet name with a news
item while being about a genuinely unrelated real-world event. If the
connection is unclear, this gate must veto — partial keyword overlap alone is
never sufficient grounds for relevance.

Fails CLOSED on any call/parse failure: relevant=False, reason logged. An
ambiguous or broken AI response must never let a bad candidate through.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from core._claude_cli import call_claude_cli
from core.models import Event

log = logging.getLogger(__name__)

__all__ = ["veto_check"]

_MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT_SECONDS = 45  # bumped from 30 -- a real timeout occurred under concurrent load in a live dry run


def _real_call_claude(prompt: str, model: str) -> str:
    return call_claude_cli(prompt, model, _TIMEOUT_SECONDS)


def _build_prompt(news_item: dict, candidate_event: Event) -> str:
    title = news_item.get("title", "")
    headlines = news_item.get("headlines", [])
    headlines_block = "\n".join(f"- {h}" for h in headlines)
    outcome_labels = ", ".join(m.outcome_label for m in candidate_event.markets) or "(none)"
    return (
        "You are a strict relevance gate between a news item and a prediction market "
        "candidate. Your ONLY job is a binary veto — you can reject this candidate, but "
        "you can never approve a candidate that code hasn't already retrieved.\n\n"
        "Known failure mode to guard against: a market can share keywords or an outlet "
        "name with a news item while being about a completely unrelated real-world event "
        "(e.g. a Polymarket market mentioning \"Capitol Hill Seattle News\" is NOT "
        "automatically relevant to a story that happens to mention Capitol Hill or Seattle). "
        "Partial keyword overlap alone is never sufficient grounds for relevance. If the "
        "connection between the news item and the market is unclear or requires a stretch, "
        "veto it.\n\n"
        f"News item title: {title}\n"
        f"News item headlines:\n{headlines_block}\n\n"
        f"Candidate market title: {candidate_event.event_title}\n"
        f"Candidate market outcomes: {outcome_labels}\n\n"
        "Is this market genuinely about the same real-world event/topic as the news item?\n\n"
        'Respond with ONLY strict JSON: {"relevant": true|false, "reason": "short reason"}. '
        "No markdown fences, no explanation outside the JSON."
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


def veto_check(
    news_item: dict, candidate_event: Event, call_claude: Callable[[str, str], str] | None = None
) -> tuple[bool, str]:
    """Binary relevance veto for one already hard-filtered candidate.

    Returns (relevant, reason). relevant=False means CODE must drop this
    candidate. Fails closed (relevant=False) on any call/parse failure.
    """
    caller = call_claude or _real_call_claude
    prompt = _build_prompt(news_item, candidate_event)
    try:
        raw = caller(prompt, _MODEL)
    except Exception as exc:
        reason = f"veto call failed: {exc}"
        log.warning("veto_check: call_claude failed: %s", exc)
        return False, reason

    stripped = _strip_fences(raw or "")
    array_text = _extract_json_object(stripped)
    if array_text is None:
        reason = "veto call failed: no JSON object found in response"
        log.warning("veto_check: %s (raw=%r)", reason, (raw or "")[:200])
        return False, reason

    try:
        parsed = json.loads(array_text)
    except json.JSONDecodeError as exc:
        reason = f"veto call failed: JSON decode error: {exc}"
        log.warning("veto_check: %s (raw=%r)", reason, array_text[:200])
        return False, reason

    if not isinstance(parsed, dict) or "relevant" not in parsed:
        reason = "veto call failed: missing 'relevant' key"
        log.warning("veto_check: %s (parsed=%r)", reason, parsed)
        return False, reason

    relevant = parsed.get("relevant")
    if not isinstance(relevant, bool):
        reason = "veto call failed: 'relevant' is not a boolean"
        log.warning("veto_check: %s (parsed=%r)", reason, parsed)
        return False, reason

    verdict_reason = parsed.get("reason", "")
    if not isinstance(verdict_reason, str):
        verdict_reason = str(verdict_reason)

    return relevant, verdict_reason
