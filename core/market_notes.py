"""core/market_notes.py — rule-based note/relevance annotation for the do_hits pool.

classify_relevance(title) -> 'rba' | 'property' | 'ai' | 'au_politics' | 'none'
build_note(item)          -> one-line note: delta phrase + personal implication
annotate_pool(pool)       -> new list with note/relevance, relevance-first mover sort
"""
from __future__ import annotations

import re

_RULES: list[tuple[str, re.Pattern]] = [
    ("rba", re.compile(r"\brba\b|reserve bank|cash rate", re.I)),
    ("property", re.compile(r"propert|housing|house price|mortgage|real estate|smsf", re.I)),
    ("ai", re.compile(r"\bai\b|artificial intelligence|anthropic|openai|\bclaude\b|nvidia|\bagi\b", re.I)),
    ("au_politics", re.compile(r"\baustralia", re.I)),
]

_IMPLICATION = {
    "rba": "feeds straight into your mortgage and Townsville cashflow assumptions.",
    "property": "worth checking against your next-purchase timing.",
    "ai": "signal for your AI work and client conversations.",
    "au_politics": "policy backdrop for your AU investments.",
    "none": "no direct AU angle — context only.",
}

_BANDS = [(15, "surged", "collapsed"), (5, "jumped", "dropped"), (1, "firmed", "slipped")]


def classify_relevance(title: str) -> str:
    for tag, pattern in _RULES:
        if pattern.search(title or ""):
            return tag
    return "none"


def _delta_phrase(delta_7d: float | None, outcome: str) -> str:
    pp = round((delta_7d or 0.0) * 100)
    if delta_7d is None or abs(pp) < 1:
        return f"{outcome} steady over 7d"
    for floor, up, down in _BANDS:
        if abs(pp) >= floor:
            verb = up if pp > 0 else down
            return f"{outcome} {verb} {'+' if pp > 0 else ''}{pp}pp over 7d"
    return f"{outcome} steady over 7d"


def build_note(item: dict) -> str:
    outcome = (item.get("outcome_label") or "").strip() or "Lead outcome"
    relevance = item.get("relevance") or classify_relevance(item.get("title", ""))
    return f"{_delta_phrase(item.get('delta_7d'), outcome)} — {_IMPLICATION[relevance]}"


def annotate_pool(pool: list[dict]) -> list[dict]:
    out = []
    for item in pool:
        relevance = classify_relevance(item.get("title", ""))
        enriched = {**item, "relevance": relevance}
        enriched["note"] = build_note(enriched)
        out.append(enriched)
    out.sort(key=lambda m: (m["relevance"] == "none", -abs(m.get("delta_7d") or 0.0)))
    return out
