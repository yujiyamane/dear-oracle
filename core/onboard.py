"""core/onboard.py — deterministic helpers for oracle-onboard (Sprint 2).

Public API (PLAN.md Sprint 2 + INTERFACES.md §5):

  coverage_for(keyword_or_tag, adapter)
      -> (candidates: list[{slug, tag_id}], market_count: int)
      Queries adapter.tags() + adapter.search() to surface candidate tags,
      then counts live markets via events_by_tag. Returns ([], 0) on zero
      coverage — the caller writes status="dormant" in that case.

  write_interests_atomic(profile, path)
      Writes to path+'.tmp', fsyncs, then calls _os_replace(tmp, path).
      _os_replace is a module-level name so tests can monkeypatch a crash.

  load_interests_mode(path) -> 'first_letter' | 'ps' | 'corrupt'
      No file            -> 'first_letter'
      Unparseable / no schema_version in contents -> 'corrupt'
      Valid schema_version present -> 'ps'

  add_interest(profile, interest_dict) -> new profile (pure)
  drop_interest(profile, name)         -> new profile (pure)
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

_DEFAULT_MAX_MARKETS = 5
_DEFAULT_THRESHOLD_PP = 5.0

# Exposed at module level so tests can monkeypatch a crash between tmp-write
# and the final rename (simulates a process death mid-write).
_os_replace = os.replace


# ---------------------------------------------------------------------------
# coverage_for
# ---------------------------------------------------------------------------

def coverage_for(keyword_or_tag: str, adapter: Any) -> tuple[list[dict], int]:
    """Return candidate {slug,tag_id} pairs and live market count.

    Strategy:
      1. Substring match on adapter.tags() slug (normalised to lowercase).
      2. Tags extracted from adapter.search(keyword) event results.
      3. For each unique candidate tag, count markets via events_by_tag().
         Deduplicates events by event_id to avoid double-counting.
    """
    all_tags = adapter.tags()
    kw = keyword_or_tag.lower()

    candidate_map: dict[str, dict] = {}

    # 1. Slug substring match
    for tag in all_tags:
        slug_norm = tag.slug.lower()
        if kw in slug_norm or slug_norm in kw:
            candidate_map[tag.tag_id] = {"slug": tag.slug, "tag_id": tag.tag_id}

    # 2. Tags from search results
    events = adapter.search(keyword_or_tag, limit=20)
    for event in events:
        for tag in event.tags:
            if tag.tag_id not in candidate_map:
                candidate_map[tag.tag_id] = {"slug": tag.slug, "tag_id": tag.tag_id}

    candidates = list(candidate_map.values())

    # 3. Count markets across candidate tags (dedup by event_id)
    seen_event_ids: set[str] = set()
    market_count = 0
    for c in candidates:
        tag_events = adapter.events_by_tag(c["tag_id"], limit=50)
        for ev in tag_events:
            if ev.event_id not in seen_event_ids:
                seen_event_ids.add(ev.event_id)
                market_count += len(ev.markets)

    return candidates, market_count


# ---------------------------------------------------------------------------
# write_interests_atomic
# ---------------------------------------------------------------------------

def write_interests_atomic(profile: dict, path: str | Path) -> None:
    """Write interests.json atomically: tmp -> fsync -> rename.

    Uses module-level _os_replace so tests can monkeypatch a mid-write crash.
    If _os_replace raises, the .tmp file is left on disk (crash evidence) and
    the original file is untouched.
    """
    p = Path(path)
    tmp = Path(str(p) + ".tmp")
    content = json.dumps(profile, ensure_ascii=False, indent=2)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    _os_replace(str(tmp), str(p))


# ---------------------------------------------------------------------------
# load_interests_mode
# ---------------------------------------------------------------------------

def load_interests_mode(path: str | Path) -> str:
    """Return the onboard mode by reading schema_version from file contents.

    'first_letter' — file does not exist (clean install)
    'ps'           — file exists and contains a valid schema_version field
    'corrupt'      — file exists but is empty, unparseable, or lacks schema_version
    """
    p = Path(path)
    if not p.exists():
        return "first_letter"
    try:
        content = p.read_text(encoding="utf-8")
        if not content.strip():
            return "corrupt"
        data = json.loads(content)
    except Exception:
        return "corrupt"
    if not isinstance(data, dict) or "schema_version" not in data:
        return "corrupt"
    return "ps"


# ---------------------------------------------------------------------------
# Pure interest-list mutators
# ---------------------------------------------------------------------------

def add_interest(profile: dict, interest_dict: dict) -> dict:
    """Return a new profile with interest_dict appended. Never mutates profile."""
    return {
        **profile,
        "interests": list(profile.get("interests", [])) + [interest_dict],
        "updated_at": _now_iso(),
    }


def drop_interest(profile: dict, name: str) -> dict:
    """Return a new profile with the named interest removed. Never mutates profile."""
    return {
        **profile,
        "interests": [i for i in profile.get("interests", []) if i.get("name") != name],
        "updated_at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
