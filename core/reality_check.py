"""core/reality_check.py — DO v2 core: hard filters, dedup, caps.

Amended design law (dk-do-v2-PLAN.md, approved 2026-07-10):
  Code retrieves and hard-filters candidates; AI may only VETO (binary relevance
  verdict, reason logged); AI never adds candidates; code enforces all caps and
  maths; AI writes all prose.

This module implements the code half: hard_filter_events, dedup_events, and the
two caps (per news item, per edition). The AI veto gate and So-what/Then-what
synthesis are separate modules (Phase 3) that consume this module's output.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Protocol

from core.models import Event, RealityCheckHit

__all__ = [
    "RealityCheckConfig",
    "RealityCheckHit",
    "TTLCache",
    "hard_filter_events",
    "dedup_events",
    "cap_markets_per_news_item",
    "cap_markets_per_edition",
    "search_query_variants",
]


class TTLCache:
    """In-process TTL cache (default 30s per dk-do-v2-PLAN.md DO-V2-2). Not
    thread-safe; scoped to a single scan run."""

    def __init__(self, ttl_seconds: float = 30.0, clock: Callable[[], float] = time.time):
        self._ttl = ttl_seconds
        self._clock = clock
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (self._clock() + self._ttl, value)


class _SearchAdapter(Protocol):
    def public_search(self, query: str, limit: int = 10) -> list[Event]: ...


def search_query_variants(
    adapter: _SearchAdapter, queries: list[str], cache: TTLCache, limit: int = 10
) -> list[list[Event]]:
    """One Gamma /public-search call per query variant, TTL-cached by query string
    so repeat queries within the cache window are served without a re-fetch."""
    results: list[list[Event]] = []
    for q in queries:
        cached = cache.get(q)
        if cached is not None:
            results.append(cached)
            continue
        events = adapter.public_search(q, limit=limit)
        cache.set(q, events)
        results.append(events)
    return results


@dataclass
class RealityCheckConfig:
    min_volume_usd: float = 10_000.0
    min_liquidity_usd: float = 1_000.0
    max_days_out: int = 90
    max_markets_per_news_item: int = 2
    max_markets_per_edition: int = 8


def _horizon_ok(end_date: str | None, today: str, max_days_out: int) -> bool:
    if not end_date:
        return False
    try:
        end = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
        start = datetime.strptime(today, "%Y-%m-%d").date()
    except ValueError:
        return False
    return date.min <= end and (end - start).days <= max_days_out and (end - start).days >= 0


def hard_filter_events(events: list[Event], config: RealityCheckConfig, today: str) -> list[Event]:
    """active=true, closed=false, volume/liquidity floor, endDate within horizon."""
    result = []
    for e in events:
        if e.active is not True or e.closed is not False:
            continue
        if (e.volume_usd or 0.0) < config.min_volume_usd:
            continue
        if (e.liquidity_usd or 0.0) < config.min_liquidity_usd:
            continue
        if not _horizon_ok(e.end_date, today, config.max_days_out):
            continue
        result.append(e)
    return result


def dedup_events(event_lists: list[list[Event]]) -> list[Event]:
    """Dedup across query variants (2-3 queries per news cluster) by event_id,
    keeping the first occurrence's ordering across variant lists."""
    seen: dict[str, Event] = {}
    order: list[str] = []
    for events in event_lists:
        for e in events:
            if e.event_id not in seen:
                seen[e.event_id] = e
                order.append(e.event_id)
    return [seen[eid] for eid in order]


def cap_markets_per_news_item(events: list[Event], config: RealityCheckConfig) -> list[Event]:
    """Max N markets per news item (default 2), highest volume first."""
    ordered = sorted(events, key=lambda e: e.volume_usd or 0.0, reverse=True)
    return ordered[: config.max_markets_per_news_item]


def cap_markets_per_edition(per_news_item: list[list[Event]], config: RealityCheckConfig) -> list[list[Event]]:
    """Max N total market lookups across the whole edition (default 8). Trims from
    the tail (lowest-priority news items) first, preserving each kept item's list intact."""
    result: list[list[Event]] = []
    remaining = config.max_markets_per_edition
    for events in per_news_item:
        if remaining <= 0:
            result.append([])
            continue
        take = events[:remaining]
        result.append(take)
        remaining -= len(take)
    return result
