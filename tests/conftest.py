"""conftest.py — shared pytest fixtures for Dear Oracle.

Provides:
  - MockAdapter: reads pre-built Event/Market dicts from fixture JSON files,
    returns proper dataclasses. Zero network calls.
  - worldcup_adapter / election_multi_adapter / zero_adapter fixtures.
  - db(): in-memory SQLite with schema.sql applied.
  - load_fixture(): helper for direct fixture loading.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from core.models import Event, Market, Tag

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SCHEMA_SQL = Path(__file__).parent.parent / "data" / "schema.sql"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _market_from_dict(d: dict) -> Market:
    return Market(
        market_id=d["market_id"],
        outcome_label=d["outcome_label"],
        url=d["url"],
        prob_now=d["prob_now"],
        prob_24h_ago=d.get("prob_24h_ago"),
        prob_7d_ago=d.get("prob_7d_ago"),
        delta_24h_pp=d.get("delta_24h_pp"),
        delta_7d_pp=d.get("delta_7d_pp"),
    )


def _event_from_dict(d: dict) -> Event:
    markets = [_market_from_dict(m) for m in d.get("markets", [])]
    tags = [Tag(slug=t["slug"], tag_id=t["tag_id"]) for t in d.get("tags", [])]
    return Event(
        event_id=d["event_id"],
        event_title=d["event_title"],
        markets=markets,
        volume_usd=d.get("volume_usd"),
        end_date=d.get("end_date"),
        tags=tags,
    )


class MockAdapter:
    """Deterministic adapter backed by a fixture file. Zero network calls."""

    def __init__(self, fixture_name: str):
        self._data = load_fixture(fixture_name)
        self._events: list[Event] = [
            _event_from_dict(e) for e in self._data.get("events", [])
        ]

    def search(self, query: str, limit: int = 10) -> list[Event]:
        return self._events[:limit]

    def events_by_tag(self, tag_id: str, limit: int = 20) -> list[Event]:
        matched = [
            e for e in self._events
            if any(t.tag_id == tag_id for t in e.tags)
        ]
        return matched[:limit]

    def markets_for_event(self, event_id: str) -> list[Market]:
        for event in self._events:
            if event.event_id == event_id:
                return list(event.markets)
        return []

    def tags(self) -> list[Tag]:
        raw = self._data.get("tags", [])
        return [Tag(slug=t["slug"], tag_id=t["tag_id"]) for t in raw]


# ---------------------------------------------------------------------------
# Adapter fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def worldcup_adapter() -> MockAdapter:
    return MockAdapter("gamma_worldcup.json")


@pytest.fixture
def election_multi_adapter() -> MockAdapter:
    return MockAdapter("gamma_election_multi.json")


@pytest.fixture
def zero_adapter() -> MockAdapter:
    return MockAdapter("gamma_zero.json")


@pytest.fixture
def noisy_adapter() -> MockAdapter:
    return MockAdapter("gamma_worldcup_noisy.json")


@pytest.fixture
def ai_tags_adapter() -> MockAdapter:
    return MockAdapter("gamma_tags_ai.json")


# ---------------------------------------------------------------------------
# SQLite in-memory db (Sprint 3+)
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """Return an in-memory SQLite connection with the full schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    if SCHEMA_SQL.exists():
        conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    yield conn
    conn.close()
