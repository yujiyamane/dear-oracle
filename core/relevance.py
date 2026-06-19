"""Relevance guard for Dear Oracle topic to market matching (stdlib-only)."""

import re

MIN_TOKEN_LEN = 4

ACRONYMS = {
    "rba", "wsl", "nsw", "ai", "smsf", "llm", "fed", "fifa", "afl", "nrl",
    "kpop", "us", "uk", "eu",
}

STOPWORDS = {
    "the", "a", "an", "to", "of", "in", "on", "at", "for", "and", "or",
    "will", "be", "is", "are", "was", "with", "by", "from", "as", "that",
    "this", "it", "its", "their", "his", "her", "what", "who", "when",
    "which", "how", "many", "more", "than", "before", "after", "during",
    "conditions", "opportunities", "news", "update", "updates", "market",
    "markets", "general", "winner", "event",
}


def tokenize(text):
    if not text:
        return set()
    return {t for t in re.split(r"[^0-9a-zA-Z]+", text.lower()) if t}


def _signal_tokens(topic):
    pool = tokenize(topic.get("topic_label", "")) | tokenize(topic.get("keywords", ""))
    acro, generic = set(), set()
    for tok in pool:
        if tok in STOPWORDS:
            continue
        if tok in ACRONYMS:
            acro.add(tok)
        elif len(tok) >= MIN_TOKEN_LEN:
            generic.add(tok)
    return acro, generic


def _keyword_phrases(topic):
    phrases = []
    for raw in (topic.get("keywords", "") or "").split(";"):
        words = {w for w in tokenize(raw) if w not in STOPWORDS}
        if len(words) >= 2:
            phrases.append(words)
    return phrases


def is_relevant(topic, title):
    title_tokens = tokenize(title)
    if not title_tokens:
        return False
    acro, generic = _signal_tokens(topic)
    if acro & title_tokens:
        return True
    for phrase in _keyword_phrases(topic):
        if phrase <= title_tokens:
            return True
    return len(generic & title_tokens) >= 2
