"""core/adapter_polymarket.py — Polymarket Gamma adapter (Sprint 1 surface).

Implements: search, events_by_tag, markets_for_event, tags.
CLOB surface (prices_history, resolution) is stubbed — used from Sprint 3/5.

Contract (INTERFACES.md §3):
  - All calls: 10s timeout, single retry with 1s backoff, then return empty + log.
  - Never raise to the caller.
  - Normalises Gamma's str/float prices to float 0.0–1.0.
  - tag_id is stored as str; Gamma returns numeric int.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from core.models import Event, Market, PricePoint, Resolution, Tag

log = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
_TIMEOUT = 10
_RETRY_WAIT = 1.0


# ---------------------------------------------------------------------------
# HTTP helper — timeout + single retry, never raises
# ---------------------------------------------------------------------------

def _http_get(url: str, params: dict[str, Any] | None = None) -> list | dict | None:
    if params:
        url = url + "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}
        )

    for attempt in range(2):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "dear-oracle/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            if attempt == 0:
                log.debug("Gamma retry %s: %s", url, exc)
                time.sleep(_RETRY_WAIT)
            else:
                log.warning("Gamma failed %s: %s", url, exc)
                return None

    return None


# ---------------------------------------------------------------------------
# Gamma response parsers
# ---------------------------------------------------------------------------

def _parse_price(raw: Any) -> float:
    """Normalise Gamma price to float 0.0–1.0.

    Gamma returns decimal strings or small floats (0–1).  INTERFACES §1 states
    the adapter must normalise at the boundary; we never divide by 100 here
    because Gamma uses 0–1 range, not cents.
    """
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _parse_market(raw: dict, event_url: str = "") -> Market | None:
    """Parse one Gamma market dict into a Market dataclass.

    Each binary market represents one Yes/No outcome.  We take index-0 of
    outcomePrices as prob_now (the 'Yes' price).

    outcome_label priority: groupItemTitle (short) > question (long form).
    groupItemTitle is "Spain", "France", etc.; question is the full sentence.

    event_url is used as fallback when market.url is absent (bulk /events path).

    Returns None if required fields are absent (dropped by caller).
    """
    try:
        market_id = raw.get("conditionId") or raw.get("id", "")
        if not market_id:
            return None

        question = raw.get("question", "").strip()
        url = raw.get("url", "") or raw.get("marketUrl", "") or event_url
        outcome_label = raw.get("groupItemTitle") or question

        outcome_prices_raw = raw.get("outcomePrices", "[]")
        if isinstance(outcome_prices_raw, str):
            outcome_prices = json.loads(outcome_prices_raw)
        else:
            outcome_prices = outcome_prices_raw or []

        prob_now = _parse_price(outcome_prices[0]) if outcome_prices else 0.0

        return Market(
            market_id=str(market_id),
            outcome_label=outcome_label,
            url=url,
            prob_now=prob_now,
        )
    except Exception as exc:
        log.debug("Failed to parse market: %s — %s", raw.get("id"), exc)
        return None


def _parse_event(raw: dict) -> Event | None:
    """Parse one Gamma event dict into an Event dataclass."""
    try:
        event_id = str(raw.get("id", ""))
        if not event_id:
            return None

        title = raw.get("title", "").strip()
        slug = raw.get("slug", "")
        event_url = f"https://polymarket.com/event/{slug}" if slug else ""

        volume_raw = raw.get("volume", 0)
        log.debug("Gamma bulk event %s raw volume: %r", event_id, volume_raw)
        volume_usd = float(volume_raw) if volume_raw else None
        end_date_raw = raw.get("endDate", "")
        end_date = end_date_raw[:10] if end_date_raw else None

        tags_raw = raw.get("tags", [])
        tags = [
            Tag(slug=t.get("slug", ""), tag_id=str(t.get("id", "")))
            for t in (tags_raw or [])
            if t.get("id")
        ]

        markets_raw = raw.get("markets", [])
        markets = [m for m in (_parse_market(mr, event_url) for mr in (markets_raw or [])) if m]

        return Event(
            event_id=event_id,
            event_title=title,
            markets=markets,
            volume_usd=volume_usd,
            end_date=end_date,
            tags=tags,
        )
    except Exception as exc:
        log.debug("Failed to parse event: %s — %s", raw.get("id"), exc)
        return None


def _events_from_response(data: Any) -> list[Event]:
    if not isinstance(data, list):
        return []
    return [e for e in (_parse_event(r) for r in data) if e]


# ---------------------------------------------------------------------------
# /public-search parsers (different JSON shape; includes oneWeekPriceChange)
# ---------------------------------------------------------------------------

def _parse_market_public_search(raw: dict, event_url: str = "") -> Market | None:
    """Parse one market from a /public-search event. Extracts prob_7d_ago from oneWeekPriceChange."""
    try:
        market_id = raw.get("conditionId") or raw.get("id", "")
        if not market_id:
            return None

        question = raw.get("question", "").strip()
        url = raw.get("url", "") or event_url
        outcome_label = raw.get("groupItemTitle") or question

        outcome_prices_raw = raw.get("outcomePrices", "[]")
        if isinstance(outcome_prices_raw, str):
            outcome_prices = json.loads(outcome_prices_raw)
        else:
            outcome_prices = outcome_prices_raw or []

        prob_now = _parse_price(outcome_prices[0]) if outcome_prices else 0.0

        prob_7d_ago = None
        week_change_raw = raw.get("oneWeekPriceChange")
        if week_change_raw is not None:
            try:
                change = float(week_change_raw)
                prob_7d_ago = max(0.0, min(1.0, round(prob_now - change, 6)))
            except (TypeError, ValueError):
                pass

        return Market(
            market_id=str(market_id),
            outcome_label=outcome_label,
            url=url,
            prob_now=prob_now,
            prob_7d_ago=prob_7d_ago,
        )
    except Exception as exc:
        log.debug("Failed to parse public-search market: %s", exc)
        return None


def _parse_event_public_search(raw: dict) -> Event | None:
    """Parse one event from a /public-search response."""
    try:
        event_id = str(raw.get("id", ""))
        if not event_id:
            return None

        title = raw.get("title", "").strip()
        slug = raw.get("slug", "")
        event_url = f"https://polymarket.com/event/{slug}" if slug else ""

        volume_raw = raw.get("volume", 0)
        volume_usd = float(volume_raw) if volume_raw else None

        end_date_raw = raw.get("endDate", "")
        end_date = end_date_raw[:10] if end_date_raw else None

        tags_raw = raw.get("tags", [])
        tags = [
            Tag(slug=t.get("slug", ""), tag_id=str(t.get("id", "")))
            for t in (tags_raw or [])
            if t.get("id")
        ]

        markets_raw = raw.get("markets", [])
        markets = [
            m for m in (_parse_market_public_search(mr, event_url) for mr in (markets_raw or []))
            if m
        ]

        liquidity_raw = raw.get("liquidity")
        liquidity_usd = float(liquidity_raw) if liquidity_raw is not None else None
        volume_24hr_raw = raw.get("volume24hr")
        volume_24hr_usd = float(volume_24hr_raw) if volume_24hr_raw is not None else None

        return Event(
            event_id=event_id,
            event_title=title,
            markets=markets,
            volume_usd=volume_usd,
            end_date=end_date,
            tags=tags,
            active=raw.get("active"),
            closed=raw.get("closed"),
            liquidity_usd=liquidity_usd,
            volume_24hr_usd=volume_24hr_usd,
        )
    except Exception as exc:
        log.debug("Failed to parse public-search event: %s", exc)
        return None


# ---------------------------------------------------------------------------
# PolymarketAdapter
# ---------------------------------------------------------------------------

class PolymarketAdapter:
    """Read-only Gamma adapter.  All failures return empty + log; never raise."""

    def search(self, query: str, limit: int = 10) -> list[Event]:
        data = _http_get(
            f"{GAMMA_BASE}/events",
            {
                "search": query,
                "limit": limit,
                "closed": "false",
                "order": "volume",
                "ascending": "false",
            },
        )
        return _events_from_response(data)

    def events_by_tag(self, tag_id: str, limit: int = 20) -> list[Event]:
        data = _http_get(
            f"{GAMMA_BASE}/events",
            {"tag_id": tag_id, "limit": limit, "order": "volume", "ascending": "false"},
        )
        return _events_from_response(data)

    def markets_for_event(self, event_id: str) -> list[Market]:
        data = _http_get(f"{GAMMA_BASE}/markets", {"event_id": event_id})
        if not isinstance(data, list):
            return []
        return [m for m in (_parse_market(r) for r in data) if m]

    def tags(self) -> list[Tag]:
        data = _http_get(f"{GAMMA_BASE}/tags")
        if not isinstance(data, list):
            return []
        return [
            Tag(slug=t.get("slug", ""), tag_id=str(t.get("id", "")))
            for t in data
            if t.get("id")
        ]

    def public_search(self, query: str, limit: int = 10) -> list[Event]:
        """Search via /public-search endpoint. Returns parsed events; never raises."""
        data = _http_get(
            f"{GAMMA_BASE}/public-search",
            {"q": query, "limit": limit},
        )
        if not isinstance(data, dict):
            return []
        events_raw = data.get("events", [])
        if not isinstance(events_raw, list):
            return []
        return [e for e in (_parse_event_public_search(r) for r in events_raw) if e]

    def top_by_volume(self, limit: int = 50) -> list[Event]:
        """Return open events ordered by volume descending. No keyword filter."""
        data = _http_get(
            f"{GAMMA_BASE}/events",
            {"closed": "false", "order": "volume", "ascending": "false", "limit": limit},
        )
        return _events_from_response(data)

    # CLOB surface — Sprint 3/5 — stubs satisfy the Protocol
    def prices_history(self, market_id: str, since: str) -> list[PricePoint]:
        return []

    def resolution(self, market_id: str) -> Resolution | None:
        return None
