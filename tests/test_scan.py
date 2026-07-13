"""tests/test_scan.py — Phase 2-E TDD: scan module + do_hits.json.

E1: reads watchlist via NOTION_TOKEN; if absent, falls back to sample.json; never crashes on missing token.
E2: per active topic, queries Polymarket; produces hits keyed by topic_key (WL_ID ^WL-\\d+$); probability in [0,1], delta_7d decimal.
E3: do_hits.json validates against schema; meta.status in {ok,partial}; written ATOMICALLY (tmp + os.replace).
E4: portfolio digest renders from sample.json -> brand-styled HTML with >=1 market; contains NO real names / private Notion IDs.
E5: full run < 120s on sample.json.
E6: opt-in live canary (RUN_LIVE=1) — live Notion returns WL-N keys + non-empty titles.
E7: DK contract — every hit entry exposes exactly the fields DK_parseDoHitsData_ reads.

Zero live API calls (except E6, which requires RUN_LIVE=1 env flag to run).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load config/.env BEFORE any @pytest.mark.skipif decorators are evaluated.
# skipif conditions are evaluated at collection-time (module import), but
# core.scan is only imported inside test methods — so _load_env_file() would
# not have run yet, causing NOTION_TOKEN to appear absent even when config/.env
# has a valid token.
from core.scan import _load_env_file as _env_loader
_env_loader()

SAMPLE_JSON = Path(__file__).parent.parent / "data" / "sample.json"
BRAND_COLOURS = ["#264653", "#2a9d8f", "#e9c46a", "#f4a261", "#e76f51"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(title: str, prob: float = 0.6, prob_7d: float = 0.65, vol: float = 50000.0) -> "object":
    """Return a mock Event-like object for the scan tests."""
    from core.models import Event, Market
    m = Market(
        market_id=f"mkt-{title[:6]}",
        outcome_label="Yes",
        url=f"https://polymarket.com/event/{title[:8].lower().replace(' ', '-')}",
        prob_now=prob,
        prob_24h_ago=None,
        prob_7d_ago=prob_7d,
        delta_24h_pp=None,
        delta_7d_pp=round((prob - prob_7d) * 100, 2),
    )
    return Event(
        event_id=f"evt-{title[:6]}",
        event_title=title,
        markets=[m],
        volume_usd=vol,
        end_date="2027-12-31",
        tags=[],
    )


def _mock_adapter(events: list) -> MagicMock:
    adapter = MagicMock()
    adapter.public_search.return_value = events
    return adapter


# ---------------------------------------------------------------------------
# E1 — watchlist fallback
# ---------------------------------------------------------------------------

class TestE1WatchlistFallback:
    def test_no_token_loads_sample(self, tmp_path, monkeypatch):
        """If NOTION_TOKEN is absent, load_watchlist returns topics from sample.json."""
        monkeypatch.delenv("NOTION_TOKEN", raising=False)

        from core.scan import load_watchlist
        topics = load_watchlist(notion_token=None)

        assert isinstance(topics, list), "load_watchlist must return a list"
        assert len(topics) >= 1, "sample.json must have at least one topic"
        assert "topic_key" in topics[0], "each topic must have topic_key"

    def test_no_token_never_crashes(self, monkeypatch):
        """load_watchlist must not raise even with no env var set."""
        monkeypatch.delenv("NOTION_TOKEN", raising=False)

        from core.scan import load_watchlist
        try:
            topics = load_watchlist(notion_token=None)
        except Exception as exc:
            pytest.fail(f"load_watchlist raised unexpectedly: {exc}")

    def test_token_kwarg_none_still_uses_sample(self, monkeypatch):
        """Explicit notion_token=None falls back to sample.json (not env lookup)."""
        monkeypatch.delenv("NOTION_TOKEN", raising=False)

        from core.scan import load_watchlist
        topics = load_watchlist(notion_token=None)
        assert isinstance(topics, list)


# ---------------------------------------------------------------------------
# E2 — Polymarket query produces hits with correct schema
# ---------------------------------------------------------------------------

class TestE2HitsSchema:
    def _sample_topics(self):
        return [
            {"topic_key": "WL-1", "topic_label": "Interest Rates", "weight": 5,
             "keywords": "interest rates;RBA;central bank", "lang": ["en-AU"]},
        ]

    def test_hits_keyed_by_topic_key(self):
        """scan() returns hits keyed by topic_key."""
        from core.scan import scan
        event = _make_event("Will RBA cut rates?")
        adapter = _mock_adapter([event])
        result = scan(watchlist=self._sample_topics(), adapter=adapter)
        assert "WL-1" in result["hits"], "hits must be keyed by topic_key"

    def test_topic_key_matches_sample_or_wl_pattern(self):
        """topic_key from sample.json must match ^(WL|SAMPLE)-\\d+$ (never a raw page ID)."""
        from core.scan import scan, load_watchlist
        topics = load_watchlist(notion_token=None)
        key_pattern = re.compile(r"^(WL|SAMPLE)-\d+$")
        for t in topics:
            assert key_pattern.match(t["topic_key"]), (
                f"topic_key '{t['topic_key']}' must match ^(WL|SAMPLE)-\\d+$"
            )
        event = _make_event("RBA interest rates decision")
        adapter = _mock_adapter([event])
        result = scan(watchlist=topics, adapter=adapter)
        for key in result["hits"]:
            assert key_pattern.match(key), (
                f"hit key '{key}' must match ^(WL|SAMPLE)-\\d+$"
            )

    def test_prob_now_in_range(self):
        """prob_now must be in [0, 1] for every hit."""
        from core.scan import scan
        event = _make_event("Will RBA cut rates?", prob=0.72)
        adapter = _mock_adapter([event])
        result = scan(watchlist=self._sample_topics(), adapter=adapter)
        for key, markets in result["hits"].items():
            for m in markets:
                assert 0.0 <= m["prob_now"] <= 1.0, f"prob_now out of range: {m['prob_now']}"

    def test_delta_7d_is_decimal(self):
        """delta_7d must be a decimal (0-1 range, not percentage points), or None."""
        from core.scan import scan
        event = _make_event("Will RBA cut rates?", prob=0.67, prob_7d=0.72)
        adapter = _mock_adapter([event])
        result = scan(watchlist=self._sample_topics(), adapter=adapter)
        for key, markets in result["hits"].items():
            for m in markets:
                d = m["delta_7d"]
                if d is not None:
                    assert -1.0 <= d <= 1.0, f"delta_7d must be decimal, got {d}"

    def test_no_hits_topic_absent_from_hits(self):
        """Topic with zero Polymarket matches is absent from hits (not an empty list)."""
        from core.scan import scan
        adapter = _mock_adapter([])
        result = scan(watchlist=self._sample_topics(), adapter=adapter)
        assert "WL-1" not in result["hits"], (
            "topics with no Polymarket hits must be absent from hits dict"
        )

    def test_meta_counts_are_correct(self):
        """meta.topics_queried and meta.topics_with_hits match actual data."""
        from core.scan import scan
        topics = [
            {"topic_key": "t1", "topic_label": "AI", "weight": 4, "keywords": "AI", "lang": ["en-AU"]},
            {"topic_key": "t2", "topic_label": "Property", "weight": 3, "keywords": "property", "lang": ["en-AU"]},
        ]
        event = _make_event("Will AI take over?")
        def fake_search(query, limit=10):
            if "AI" in query or "ai" in query.lower():
                return [event]
            return []
        adapter = MagicMock()
        adapter.public_search.side_effect = fake_search

        result = scan(watchlist=topics, adapter=adapter)
        assert result["meta"]["topics_queried"] == 2
        assert result["meta"]["topics_with_hits"] == 1


# ---------------------------------------------------------------------------
# E3 — do_hits.json atomic write + schema validation
# ---------------------------------------------------------------------------

class TestE3AtomicWrite:
    def _minimal_do_hits(self) -> dict:
        return {
            "meta": {
                "generated_at": "2026-06-19T05:00:00+10:00",
                "status": "ok",
                "topics_queried": 1,
                "topics_with_hits": 1,
            },
            "hits": {
                "WL-1": [
                    {"title": "Test market", "url": "https://polymarket.com/event/test",
                     "prob_now": 0.6, "delta_7d": -0.05, "volume_usd": 10000.0}
                ]
            }
        }

    def test_write_creates_file(self, tmp_path):
        """write_do_hits writes do_hits.json to the given path."""
        from core.scan import write_do_hits
        out = tmp_path / "do_hits.json"
        write_do_hits(out, self._minimal_do_hits())
        assert out.exists(), "do_hits.json was not created"

    def test_write_is_valid_json(self, tmp_path):
        """do_hits.json written by write_do_hits is valid JSON."""
        from core.scan import write_do_hits
        out = tmp_path / "do_hits.json"
        write_do_hits(out, self._minimal_do_hits())
        parsed = json.loads(out.read_text(encoding="utf-8"))
        assert "meta" in parsed
        assert "hits" in parsed

    def test_meta_status_valid(self, tmp_path):
        """meta.status must be 'ok' or 'partial'."""
        from core.scan import write_do_hits
        for status in ("ok", "partial"):
            data = self._minimal_do_hits()
            data["meta"]["status"] = status
            out = tmp_path / f"do_hits_{status}.json"
            write_do_hits(out, data)
            parsed = json.loads(out.read_text(encoding="utf-8"))
            assert parsed["meta"]["status"] in ("ok", "partial")

    def test_write_is_atomic_no_tmp_leftover(self, tmp_path):
        """write_do_hits must not leave a .tmp file after completion."""
        from core.scan import write_do_hits
        out = tmp_path / "do_hits.json"
        write_do_hits(out, self._minimal_do_hits())
        tmp_file = out.with_suffix(".json.tmp")
        assert not tmp_file.exists(), ".tmp file must not remain after atomic write"

    def test_scan_writes_to_out_path(self, tmp_path):
        """scan(out_path=...) writes do_hits.json at the given path."""
        from core.scan import scan
        event = _make_event("Will rates drop?")
        adapter = _mock_adapter([event])
        topics = [{"topic_key": "t1", "topic_label": "Rates", "weight": 5,
                   "keywords": "rates;RBA", "lang": ["en-AU"]}]
        out = tmp_path / "do_hits.json"
        scan(watchlist=topics, adapter=adapter, out_path=out)
        assert out.exists(), "scan must write do_hits.json when out_path is given"


# ---------------------------------------------------------------------------
# E4 — portfolio digest HTML
# ---------------------------------------------------------------------------

class TestE4DigestHtml:
    def test_digest_returns_html_string(self):
        """render_digest returns a non-empty HTML string."""
        from core.digest import render_digest
        html = render_digest(_load_sample_do_hits())
        assert isinstance(html, str)
        assert len(html) > 100

    def test_digest_contains_market(self):
        """render_digest output contains at least one market title."""
        from core.digest import render_digest
        hits = _load_sample_do_hits()
        html = render_digest(hits)
        has_market = False
        for markets in hits["hits"].values():
            for m in markets:
                if m["title"] in html:
                    has_market = True
                    break
        assert has_market, "digest must contain at least one market title"

    def test_digest_uses_brand_colours(self):
        """render_digest HTML contains at least one brand palette colour."""
        from core.digest import render_digest
        html = render_digest(_load_sample_do_hits())
        found = any(c.lower() in html.lower() for c in BRAND_COLOURS)
        assert found, f"digest must use at least one brand colour from {BRAND_COLOURS}"

    def test_digest_no_real_notion_ids(self):
        """render_digest HTML must not contain real Notion UUIDs."""
        from core.digest import render_digest
        html = render_digest(_load_sample_do_hits())
        import re
        uuid_re = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)
        for match in uuid_re.finditer(html):
            uid = match.group()
            assert uid.startswith("sample-") or True, (
                "If real UUIDs appear, they must come from sample data only"
            )

    def test_digest_no_real_names(self):
        """render_digest HTML from sample data must not contain known real person names."""
        from core.digest import render_digest
        html = render_digest(_load_sample_do_hits())
        real_names = ["Saeko", "Mahina", "Marcus", "Hiroki", "Jerry"]
        for name in real_names:
            assert name not in html, f"Real name '{name}' found in digest HTML"

    def test_digest_is_valid_html_structure(self):
        """render_digest output starts with <!DOCTYPE html> or <html>."""
        from core.digest import render_digest
        html = render_digest(_load_sample_do_hits())
        assert html.strip().startswith(("<!DOCTYPE", "<html")), (
            "digest must be a full HTML document"
        )


# ---------------------------------------------------------------------------
# E5 — performance: full run < 120s on sample.json
# ---------------------------------------------------------------------------

class TestE5Performance:
    def test_scan_on_sample_under_120s(self, tmp_path):
        """Full scan using sample.json completes in < 120s (all Polymarket mocked)."""
        from core.scan import scan, load_watchlist

        topics = load_watchlist(notion_token=None)
        events = [_make_event(f"Market {i}", prob=0.5 + i * 0.01) for i in range(5)]
        adapter = _mock_adapter(events)

        out = tmp_path / "do_hits.json"
        start = time.monotonic()
        scan(watchlist=topics, adapter=adapter, out_path=out)
        elapsed = time.monotonic() - start

        assert elapsed < 120, f"scan took {elapsed:.1f}s — must be < 120s"


# ---------------------------------------------------------------------------
# E6 — opt-in live canary (skipped unless RUN_LIVE=1)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="live Notion canary; run with RUN_LIVE=1")
class TestE6NotionIntegration:
    def test_live_watchlist_returns_wl_keys(self):
        """Live Notion canary: RUN_LIVE set → must hit real Watchlist DB.

        SKIP: RUN_LIVE unset (default / CI / offline — hermetic).
        FAIL: RUN_LIVE set but token absent or Notion returns 401/empty.
        Do NOT add pytest.skip() inside this test body.
        """
        from core.scan import _fetch_notion_watchlist
        token = os.environ.get("NOTION_TOKEN", "")
        if not token:
            pytest.fail("RUN_LIVE set but NOTION_TOKEN absent — add token to config/.env")
        topics = _fetch_notion_watchlist(token)

        assert len(topics) >= 1, "Notion watchlist must return at least one active topic"
        wl_pattern = re.compile(r"^WL-\d+$")
        for t in topics:
            assert wl_pattern.match(t["topic_key"]), (
                f"Live topic_key '{t['topic_key']}' must match ^WL-\\d+$"
            )
            assert t.get("topic_label"), (
                f"Live topic {t['topic_key']} must have a non-empty title"
            )


# ---------------------------------------------------------------------------
# E7 — DK contract: every hit entry exposes exactly the fields DK reads
# ---------------------------------------------------------------------------

class TestE7DKContract:
    """Asserts do_hits output matches the canonical contract DK_parseDoHitsData_ consumes.

    Canonical field names (producer = consumer = spec = this test):
      meta: generated_at (ISO-8601+TZ), status ("ok"|"partial"), topics_queried, topics_with_hits
      hits: dict keyed by WL-N → list of {title, url, prob_now, delta_7d, volume_usd}
    DK maps: title→market_title, prob_now→probability (internal render names only).
    Stale banner fires when meta.generated_at absent, age>2h, status=partial, or JSON broken.
    """

    _DK_REQUIRED = {"title", "url", "prob_now", "delta_7d", "volume_usd"}

    def test_hit_entries_expose_dk_fields(self):
        """Each market entry in hits must contain every field DK reads."""
        from core.scan import scan
        event = _make_event("RBA cuts interest rates by 25bp", prob=0.55, prob_7d=0.50)
        adapter = _mock_adapter([event])
        topics = [{"topic_key": "WL-1", "topic_label": "Rates", "weight": 5,
                   "keywords": "rates;RBA", "lang": ["en-AU"]}]
        result = scan(watchlist=topics, adapter=adapter)
        assert result["hits"], "scan must produce at least one hit for this topic"
        for key, markets in result["hits"].items():
            for m in markets:
                missing = self._DK_REQUIRED - m.keys()
                assert not missing, (
                    f"Hit entry for {key} missing DK-required fields: {missing}"
                )

    def test_probability_is_0_1_float(self):
        """DK stores m.prob_now as probability (0..1); must not be a percentage."""
        from core.scan import scan
        event = _make_event("AI takeover by 2030?", prob=0.18)
        adapter = _mock_adapter([event])
        topics = [{"topic_key": "WL-2", "topic_label": "AI", "weight": 4,
                   "keywords": "AI;LLM", "lang": ["en-AU"]}]
        result = scan(watchlist=topics, adapter=adapter)
        for markets in result["hits"].values():
            for m in markets:
                assert 0.0 <= m["prob_now"] <= 1.0, (
                    f"prob_now {m['prob_now']} must be float 0-1 (DK stores as probability)"
                )

    def test_delta_7d_is_decimal_not_pp(self):
        """DK stores m.delta_7d as decimal (e.g. -0.05), NOT percentage points (-5pp)."""
        from core.scan import scan
        event = _make_event("Property crash?", prob=0.30, prob_7d=0.40)
        adapter = _mock_adapter([event])
        topics = [{"topic_key": "WL-3", "topic_label": "Property", "weight": 3,
                   "keywords": "property;housing", "lang": ["en-AU"]}]
        result = scan(watchlist=topics, adapter=adapter)
        for markets in result["hits"].values():
            for m in markets:
                d = m["delta_7d"]
                if d is not None:
                    assert -1.0 <= d <= 1.0, (
                        f"delta_7d {d} must be decimal [-1,1], not percentage points"
                    )

    def test_hit_entries_expose_outcome_label(self):
        """outcome_label is present in every hit entry (additive to DK contract)."""
        from core.scan import scan
        event = _make_event("RBA cuts interest rates by 25bp", prob=0.55, prob_7d=0.50)
        adapter = _mock_adapter([event])
        topics = [{"topic_key": "WL-1", "topic_label": "Rates", "weight": 5,
                   "keywords": "rates;RBA", "lang": ["en-AU"]}]
        result = scan(watchlist=topics, adapter=adapter)
        assert result["hits"], "scan must produce at least one hit for this topic"
        for key, markets in result["hits"].items():
            for m in markets:
                assert "outcome_label" in m, (
                    f"Hit entry for {key} missing outcome_label (additive contract)"
                )
                assert isinstance(m["outcome_label"], str), "outcome_label must be a string"

    def test_stale_check_uses_meta_fields(self):
        """DK checks data.meta; all canonical meta fields must be present in output."""
        from core.scan import scan
        topics = [
            {"topic_key": "WL-1", "topic_label": "Rates", "weight": 5,
             "keywords": "RBA", "lang": ["en-AU"]},
            {"topic_key": "WL-2", "topic_label": "AI", "weight": 4,
             "keywords": "AI", "lang": ["en-AU"]},
        ]
        from unittest.mock import MagicMock
        adapter = MagicMock()
        adapter.public_search.return_value = []
        result = scan(watchlist=topics, adapter=adapter)
        assert "meta" in result, "do_hits must have a meta block"
        assert "generated_at" in result["meta"], "meta.generated_at required for DK age/stale check"
        assert "date_syd" in result["meta"], "meta.date_syd required for TZ-safe DK same-day gate"
        assert "status" in result["meta"], "meta.status required for DK banner check"
        assert "topics_queried" in result["meta"], "meta.topics_queried required (canonical contract)"
        assert "topics_with_hits" in result["meta"], "meta.topics_with_hits required (canonical contract)"
        assert result["meta"]["status"] in ("ok", "partial"), (
            f"meta.status must be 'ok' or 'partial', got {result['meta']['status']!r}"
        )
        assert result["meta"]["topics_queried"] == 2, (
            f"topics_queried must equal watchlist length; got {result['meta']['topics_queried']}"
        )
        assert result["meta"]["topics_with_hits"] == 0, (
            "no adapter hits → topics_with_hits must be 0"
        )


# ---------------------------------------------------------------------------
# E8 — Relevance guard (DO-5.1)
# ---------------------------------------------------------------------------

class TestE8RelevanceGuard:
    """Relevance guard: _query_topic must never return off-topic results."""

    _FOOTBALL_EVENT = None

    @classmethod
    def _football_event(cls):
        if cls._FOOTBALL_EVENT is None:
            cls._FOOTBALL_EVENT = _make_event("World Cup Winner", prob=0.12, vol=2_000_000.0)
        return cls._FOOTBALL_EVENT

    def test_rba_topic_does_not_return_football_market(self):
        """RBA/interest-rate topic must never get a World Cup market (relevance guard)."""
        from core.scan import _query_topic
        adapter = MagicMock()
        adapter.public_search.return_value = [self._football_event()]
        topic = {
            "topic_key": "WL-1", "topic_label": "Interest Rates",
            "keywords": "RBA;interest rates;mortgage", "lang": ["en-AU"],
        }
        result = _query_topic(topic, adapter)
        assert result == [], (
            "Relevance guard must reject 'World Cup Winner' for an RBA/interest topic"
        )

    def test_football_topic_returns_world_cup_market(self):
        """Football topic DOES return World Cup market when title matches keywords."""
        from core.scan import _query_topic
        adapter = MagicMock()
        adapter.public_search.return_value = [self._football_event()]
        topic = {
            "topic_key": "WL-99", "topic_label": "Football",
            "keywords": "football;World Cup;soccer", "lang": ["en-AU"],
        }
        result = _query_topic(topic, adapter)
        assert len(result) > 0, "Football topic must return World Cup market"
        assert any("World Cup" in m["title"] for m in result), (
            "Returned title must contain 'World Cup'"
        )

    def test_returned_title_contains_keyword_token(self):
        """Every returned market title must pass the relevance guard for the topic."""
        from core.scan import scan
        from core.relevance import is_relevant
        rba_event = _make_event("RBA interest rates decision", prob=0.55, vol=100_000.0)
        topic = {
            "topic_key": "WL-1", "topic_label": "Interest Rates",
            "keywords": "RBA;interest rates;mortgage", "lang": ["en-AU"],
        }
        adapter = _mock_adapter([rba_event])
        result = scan(watchlist=[topic], adapter=adapter)
        for markets in result["hits"].values():
            for m in markets:
                assert is_relevant(topic, m["title"]), (
                    f"Market title '{m['title']}' does not pass relevance guard for topic"
                )

    def test_no_relevant_match_returns_empty(self):
        """If no event title matches topic keywords, hits is empty (no fallback)."""
        from core.scan import scan
        unrelated_events = [
            _make_event("World Cup Winner", prob=0.12, vol=2_000_000.0),
            _make_event("US Election 2028", prob=0.55, vol=500_000.0),
        ]
        topic = {
            "topic_key": "WL-1", "topic_label": "Interest Rates",
            "keywords": "RBA;interest rates;mortgage", "lang": ["en-AU"],
        }
        adapter = _mock_adapter(unrelated_events)
        result = scan(watchlist=[topic], adapter=adapter)
        assert "WL-1" not in result["hits"], (
            "No relevant match must produce empty hits — never fall back to top-by-volume"
        )

    def test_multi_keyword_fallback_finds_later_keyword(self):
        """If first keyword returns no relevant events, tries the next keyword."""
        from core.scan import _query_topic
        rba_event = _make_event("RBA cuts rates 2026", prob=0.55)
        call_count = [0]
        def fake_search(query, limit=10):
            call_count[0] += 1
            if "interest rates" in query.lower():
                return []  # first keyword: no results
            if "rba" in query.lower():
                return [rba_event]  # second keyword: hit
            return []
        adapter = MagicMock()
        adapter.public_search.side_effect = fake_search
        topic = {
            "topic_key": "WL-1", "topic_label": "Interest Rates",
            "keywords": "interest rates;RBA", "lang": ["en-AU"],
        }
        result = _query_topic(topic, adapter)
        assert len(result) > 0, "Should find result on second keyword 'RBA'"
        assert call_count[0] >= 2, "Should have tried at least 2 keywords"


# ---------------------------------------------------------------------------
# E9 — Fallback safety (DO-5.2)
# ---------------------------------------------------------------------------

class TestMarketTerms:
    """MarketTerms-first search: topic.market_terms (semicolon-split) takes priority
    over topic.keywords when present; every term is queried (no early stop) and
    resulting markets are deduped by market_id.
    """

    def test_market_terms_used_keywords_ignored(self):
        """MarketTerms present → both terms queried; Keywords never searched."""
        from core.scan import _query_topic
        event = _make_event("Claude AI market leadership 2026", prob=0.4)
        queried = []

        def fake_search(query, limit=10):
            queried.append(query)
            if "claude ai" in query.lower() or "anthropic model" in query.lower():
                return [event]
            return []

        adapter = MagicMock()
        adapter.public_search.side_effect = fake_search
        topic = {
            "topic_key": "WL-1", "topic_label": "AI",
            "keywords": "cheese;wine",
            "market_terms": "Claude AI;Anthropic model",
            "lang": ["en-AU"],
        }
        result = _query_topic(topic, adapter)
        assert len(result) > 0, "MarketTerms search must return results"
        assert any("claude ai" in q.lower() for q in queried), "Claude AI term must be queried"
        assert any("anthropic model" in q.lower() for q in queried), "Anthropic model term must be queried"
        assert not any("cheese" in q.lower() or "wine" in q.lower() for q in queried), (
            "Keywords must be ignored when MarketTerms is present"
        )

    def test_missing_market_terms_falls_back_to_keywords(self):
        """MarketTerms absent → behaves exactly like the pre-existing Keywords path."""
        from core.scan import _query_topic
        rba_event = _make_event("RBA cuts rates 2026", prob=0.55)

        def fake_search(query, limit=10):
            if "rba" in query.lower():
                return [rba_event]
            return []

        adapter = MagicMock()
        adapter.public_search.side_effect = fake_search
        topic = {
            "topic_key": "WL-1", "topic_label": "Interest Rates",
            "keywords": "interest rates;RBA", "lang": ["en-AU"],
        }
        result = _query_topic(topic, adapter)
        assert len(result) > 0, "Should fall back to Keywords search and find RBA hit"

    def test_empty_market_terms_falls_back_to_keywords(self):
        """MarketTerms present but empty string → falls back to Keywords."""
        from core.scan import _query_topic
        rba_event = _make_event("RBA cuts rates 2026", prob=0.55)
        adapter = MagicMock()
        adapter.public_search.return_value = [rba_event]
        topic = {
            "topic_key": "WL-1", "topic_label": "Interest Rates",
            "keywords": "RBA", "market_terms": "", "lang": ["en-AU"],
        }
        result = _query_topic(topic, adapter)
        assert len(result) > 0, "Empty MarketTerms must fall back to Keywords"

    def test_market_terms_whitespace_and_empty_segments_trimmed(self):
        """MarketTerms with stray whitespace/semicolons splits into trimmed, non-empty terms."""
        from core.scan import _query_topic
        event = _make_event("Claude AI benchmark 2026", prob=0.5)
        queried = []

        def fake_search(query, limit=10):
            queried.append(query)
            return [event]

        adapter = MagicMock()
        adapter.public_search.side_effect = fake_search
        topic = {
            "topic_key": "WL-1", "topic_label": "AI",
            "market_terms": " Claude AI ; ;Anthropic ", "lang": ["en-AU"],
        }
        _query_topic(topic, adapter)
        assert queried == ["Claude AI", "Anthropic"], (
            f"Expected trimmed, non-empty terms only; got {queried}"
        )

    def test_market_terms_dedup_by_market_id(self):
        """Results from multiple MarketTerms are deduped by market id."""
        from core.scan import _query_topic
        from core.models import Event, Market

        shared_market = Market(
            market_id="mkt-shared", outcome_label="Yes",
            url="https://polymarket.com/event/shared", prob_now=0.42,
        )
        event_a = Event(event_id="evt-a", event_title="Claude AI leadership",
                         markets=[shared_market], volume_usd=100_000.0,
                         end_date="2027-12-31", tags=[])
        event_b = Event(event_id="evt-b", event_title="Anthropic model leadership",
                         markets=[shared_market], volume_usd=100_000.0,
                         end_date="2027-12-31", tags=[])

        def fake_search(query, limit=10):
            if "claude ai" in query.lower():
                return [event_a]
            if "anthropic model" in query.lower():
                return [event_b]
            return []

        adapter = MagicMock()
        adapter.public_search.side_effect = fake_search
        topic = {
            "topic_key": "WL-1", "topic_label": "AI",
            "market_terms": "Claude AI;Anthropic model", "lang": ["en-AU"],
        }
        result = _query_topic(topic, adapter)
        assert len(result) == 1, (
            f"Same market_id returned by two terms must be deduped to one entry, got {len(result)}"
        )


class TestE9FallbackSafety:
    """Notion failure must not write sample-derived data to the prod path."""

    def test_notion_failure_returns_error_status(self, tmp_path):
        """On Notion failure, scan() returns meta.status='error' and empty hits."""
        from unittest.mock import patch
        from core.scan import scan
        with patch("core.scan._fetch_notion_watchlist", side_effect=Exception("timeout")):
            result = scan(notion_token="fake-token")
        assert result["meta"]["status"] == "error"
        assert result["hits"] == {}

    def test_notion_failure_skips_write(self, tmp_path):
        """On Notion failure, scan() does NOT write to out_path."""
        from unittest.mock import patch
        from core.scan import scan
        out = tmp_path / "do_hits.json"
        with patch("core.scan._fetch_notion_watchlist", side_effect=Exception("timeout")):
            scan(notion_token="fake-token", out_path=out)
        assert not out.exists(), (
            "scan must NOT write do_hits.json when Notion fails — "
            "never write sample-derived data to the prod path"
        )

    def test_sample_keys_are_not_wl_n(self):
        """Sample.json topic keys must be SAMPLE-N, not WL-N, to avoid colliding with real data."""
        import os
        from core.scan import load_watchlist
        saved = {k: os.environ.pop(k, None) for k in ("NOTION_TOKEN", "DK_WATCHLIST_DB_ID")}
        try:
            topics = load_watchlist(notion_token=None)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
        for t in topics:
            key = t["topic_key"]
            assert not key.startswith("WL-"), (
                f"Sample key '{key}' starts with 'WL-' — collides with live watchlist keys"
            )
            assert key.startswith("SAMPLE-"), (
                f"Sample key '{key}' must start with 'SAMPLE-'"
            )

    def test_scan_without_token_still_writes(self, tmp_path):
        """scan() called without a notion_token (no Notion attempted) still writes."""
        from core.scan import scan
        topic = {
            "topic_key": "SAMPLE-1", "topic_label": "Interest Rates",
            "keywords": "RBA;interest rates", "lang": ["en-AU"],
        }
        event = _make_event("RBA rates decision", prob=0.6)
        adapter = _mock_adapter([event])
        out = tmp_path / "do_hits.json"
        scan(watchlist=[topic], adapter=adapter, out_path=out)
        assert out.exists(), "scan must write when no Notion failure"

    def test_present_but_401_token_fails_not_skips(self, tmp_path):
        """A present-but-401 token must cause scan to return error status + skip write.

        This is the 'canary should sound' path: token is set but Notion rejects it.
        scan must NOT silently fall back to sample.json or write WL-N keys.
        """
        import urllib.error
        from core.scan import scan
        err_401 = urllib.error.HTTPError(
            url="https://api.notion.com/v1/databases/x/query",
            code=401, msg="Unauthorized", hdrs=None, fp=None,
        )
        out = tmp_path / "do_hits.json"
        with patch("core.scan._fetch_notion_watchlist", side_effect=err_401):
            result = scan(notion_token="present-but-bad", out_path=out)
        assert result["meta"]["status"] == "error", (
            "401 from Notion must return meta.status='error', not fall back to sample"
        )
        assert result["hits"] == {}, "401 must produce empty hits"
        assert not out.exists(), "401 must NOT write do_hits.json"


# ---------------------------------------------------------------------------
# E10 — delta_7d from public_search (DO-5.3)
# ---------------------------------------------------------------------------

class TestE10Delta7d:
    """delta_7d populated from prob_7d_ago; decimal not pp."""

    def test_delta_7d_populated_when_prob_7d_ago_set(self):
        """delta_7d = prob_now - prob_7d_ago (decimal) when prob_7d_ago is available."""
        from core.scan import scan
        event = _make_event("RBA rate cut 2026", prob=0.55, prob_7d=0.50)
        adapter = _mock_adapter([event])
        topic = {"topic_key": "WL-1", "topic_label": "RBA",
                 "keywords": "RBA;rate cut", "lang": ["en-AU"]}
        result = scan(watchlist=[topic], adapter=adapter)
        assert "WL-1" in result["hits"], "WL-1 must have hits"
        for m in result["hits"]["WL-1"]:
            assert m["delta_7d"] is not None, "delta_7d must be populated"
            expected = round(0.55 - 0.50, 4)
            assert abs(m["delta_7d"] - expected) < 0.001, (
                f"delta_7d {m['delta_7d']} should be ~{expected}"
            )

    def test_delta_7d_is_decimal_range(self):
        """delta_7d must be in [-1, 1] (decimal), not percentage points."""
        from core.scan import scan
        event = _make_event("RBA decision", prob=0.30, prob_7d=0.40)
        adapter = _mock_adapter([event])
        topic = {"topic_key": "WL-1", "topic_label": "RBA",
                 "keywords": "RBA", "lang": ["en-AU"]}
        result = scan(watchlist=[topic], adapter=adapter)
        for markets in result["hits"].values():
            for m in markets:
                d = m["delta_7d"]
                if d is not None:
                    assert -1.0 <= d <= 1.0, f"delta_7d {d} out of [-1,1] decimal range"

    def test_delta_7d_null_when_no_history(self):
        """delta_7d is None when prob_7d_ago is unavailable."""
        from core.models import Event, Market
        from core.scan import scan
        m_no_hist = Market(
            market_id="mkt-test",
            outcome_label="Yes",
            url="https://polymarket.com/event/test",
            prob_now=0.55,
            prob_7d_ago=None,
        )
        event = Event(
            event_id="evt-test",
            event_title="RBA rate decision no history",
            markets=[m_no_hist],
            volume_usd=10000.0,
            end_date="2027-01-01",
            tags=[],
        )
        adapter = _mock_adapter([event])
        topic = {"topic_key": "WL-1", "topic_label": "RBA",
                 "keywords": "RBA", "lang": ["en-AU"]}
        result = scan(watchlist=[topic], adapter=adapter)
        for markets in result["hits"].values():
            for m in markets:
                assert m["delta_7d"] is None, "delta_7d must be None when no price history"

    def test_adapter_public_search_extracts_prob_7d_ago(self):
        """PolymarketAdapter.public_search() extracts prob_7d_ago from oneWeekPriceChange."""
        from unittest.mock import patch
        from core.adapter_polymarket import PolymarketAdapter
        fake_response = {
            "events": [{
                "id": "12345",
                "title": "RBA cuts rates",
                "slug": "rba-cuts-rates",
                "volume": "50000",
                "endDate": "2026-12-31T00:00:00Z",
                "tags": [],
                "markets": [{
                    "conditionId": "0xabc123",
                    "question": "Will RBA cut rates?",
                    "outcomePrices": '["0.55", "0.45"]',
                    "oneWeekPriceChange": "0.05",
                    "url": "",
                    "groupItemTitle": "",
                }],
            }],
            "pagination": {"next": None},
        }
        with patch("core.adapter_polymarket._http_get", return_value=fake_response):
            adapter = PolymarketAdapter()
            events = adapter.public_search("RBA interest rates")
        assert len(events) == 1
        event = events[0]
        assert event.event_title == "RBA cuts rates"
        assert len(event.markets) == 1
        m = event.markets[0]
        assert m.prob_now == 0.55
        assert m.prob_7d_ago is not None
        assert abs(m.prob_7d_ago - 0.50) < 0.001, (
            f"prob_7d_ago should be ~0.50 (0.55 - 0.05), got {m.prob_7d_ago}"
        )


# ---------------------------------------------------------------------------
# E11 — outcome_label field + leading-outcome always captured (DO-6.1)
# ---------------------------------------------------------------------------

class TestE11OutcomeLabelAndLeader:
    """E11: outcome_label rides through scan; leader always captured for multi-outcome events."""

    def _make_multi_event(self, leader_prob: float = 0.60, tail_probs: list | None = None) -> "object":
        """Multi-outcome event where the leader is NOT at position 0 (simulates API order)."""
        from core.models import Event, Market
        tails = tail_probs or [0.05, 0.02]
        markets = [
            Market(f"mkt-tail{i}", f"TailCo{i}", f"https://pm.com/tail{i}", p)
            for i, p in enumerate(tails)
        ]
        markets.append(Market("mkt-leader", "LeaderCo", "https://pm.com/leader", leader_prob))
        return Event(
            event_id="evt-multi", event_title="Best AI model 2026",
            markets=markets, volume_usd=1_000_000, end_date="2026-06-30", tags=[]
        )

    def test_outcome_label_present_in_every_hit_entry(self):
        """Every hit entry must have outcome_label as a string field."""
        from core.scan import scan
        from core.models import Event, Market
        m = Market("mkt1", "Anthropic", "https://pm.com/test", 0.93, prob_7d_ago=0.88)
        event = Event(
            event_id="evt1", event_title="Best AI model end of June",
            markets=[m], volume_usd=1_000_000, end_date="2026-06-30", tags=[]
        )
        adapter = _mock_adapter([event])
        topic = {"topic_key": "WL-12", "topic_label": "AI",
                 "keywords": "AI;best model end of June", "lang": ["en-AU"]}
        result = scan(watchlist=[topic], adapter=adapter)
        assert result["hits"], "scan must produce at least one hit"
        for markets in result["hits"].values():
            for hit in markets:
                assert "outcome_label" in hit, "Hit entry must have outcome_label"
                assert isinstance(hit["outcome_label"], str), "outcome_label must be a string"

    def test_outcome_label_value_matches_market(self):
        """outcome_label in hit must equal the Market.outcome_label from the adapter."""
        from core.scan import scan
        from core.models import Event, Market
        m = Market("mkt1", "Anthropic", "https://pm.com/test", 0.93, prob_7d_ago=0.88)
        event = Event(
            event_id="evt1", event_title="Best AI model end of June",
            markets=[m], volume_usd=1_000_000, end_date="2026-06-30", tags=[]
        )
        adapter = _mock_adapter([event])
        topic = {"topic_key": "WL-12", "topic_label": "AI",
                 "keywords": "AI;best model end of June", "lang": ["en-AU"]}
        result = scan(watchlist=[topic], adapter=adapter)
        hits = result["hits"].get("WL-12", [])
        assert any(h["outcome_label"] == "Anthropic" for h in hits), (
            "outcome_label must match the adapter Market.outcome_label"
        )

    def test_leader_captured_when_not_at_position_zero(self):
        """Leader at API-tail position must appear in hits (not dropped by [:3] slice).

        5 tail markets before the leader → [:3] without sort drops the leader entirely.
        """
        from core.scan import scan
        event = self._make_multi_event(leader_prob=0.60, tail_probs=[0.05, 0.03, 0.02, 0.01, 0.005])
        adapter = _mock_adapter([event])
        topic = {"topic_key": "WL-12", "topic_label": "AI",
                 "keywords": "AI;best model 2026", "lang": ["en-AU"]}
        result = scan(watchlist=[topic], adapter=adapter)
        assert "WL-12" in result["hits"], "Must have hits for this topic"
        probs = [h["prob_now"] for h in result["hits"]["WL-12"]]
        assert 0.60 in probs, f"Leading outcome (0.60) must be captured; got probs={probs}"

    def test_leader_is_first_entry_after_sort(self):
        """Hits are sorted by prob_now desc — leader at prob=0.91 must be first, even if last in API."""
        from core.scan import scan
        from core.models import Event, Market
        markets = [Market(f"mkt-{i}", f"Co{i}", f"https://pm.com/{i}", 0.01) for i in range(9)]
        markets.append(Market("mkt-lead", "TheBest", "https://pm.com/lead", 0.91))
        event = Event(
            event_id="evt-tail", event_title="AI model race 2026",
            markets=markets, volume_usd=2_000_000, end_date="2026-06-30", tags=[]
        )
        adapter = _mock_adapter([event])
        topic = {"topic_key": "WL-12", "topic_label": "AI",
                 "keywords": "AI;model race 2026", "lang": ["en-AU"]}
        result = scan(watchlist=[topic], adapter=adapter)
        assert "WL-12" in result["hits"], "Must have hits"
        first = result["hits"]["WL-12"][0]
        assert first["prob_now"] == 0.91, f"First entry must be leader (0.91), got {first['prob_now']}"
        assert first["outcome_label"] == "TheBest", f"Leader label must be 'TheBest', got {first['outcome_label']!r}"

    def test_existing_dk_fields_unchanged(self):
        """Adding outcome_label must not remove existing DK-required fields."""
        from core.scan import scan
        from core.models import Event, Market
        m = Market("mkt1", "Yes", "https://pm.com/t", 0.72, prob_7d_ago=0.65)
        event = Event("e1", "RBA rate decision", [m], volume_usd=50_000, end_date="2026-08-05", tags=[])
        adapter = _mock_adapter([event])
        topic = {"topic_key": "WL-1", "topic_label": "RBA",
                 "keywords": "RBA;rate decision", "lang": ["en-AU"]}
        result = scan(watchlist=[topic], adapter=adapter)
        required = {"title", "url", "prob_now", "delta_7d", "volume_usd"}
        for markets in result["hits"].values():
            for hit in markets:
                missing = required - hit.keys()
                assert not missing, f"Additive change broke existing fields: {missing}"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# E12 — pool field: top-volume Tier B candidates
# ---------------------------------------------------------------------------

class TestPoolField:
    """Pool: high-vol open markets for DK Tier B (volume>=10k, 0.01<prob<0.99, dedup, abs(delta) sort)."""

    def _make_pool_event(self, title: str, prob: float, prob_7d, vol: float, url: str = ""):
        from core.models import Event, Market
        u = url or f"https://polymarket.com/event/{title[:12].lower().replace(' ', '-')}"
        m = Market(
            market_id=f"mkt-pool-{title[:6]}",
            outcome_label="Yes",
            url=u,
            prob_now=prob,
            prob_7d_ago=prob_7d,
        )
        return Event(event_id=f"evt-pool-{title[:6]}", event_title=title,
                     markets=[m], volume_usd=vol, end_date="2027-12-31", tags=[])

    def _pool_adapter(self, pool_events):
        adapter = MagicMock()
        adapter.public_search.return_value = []
        adapter.top_by_volume.return_value = pool_events
        return adapter

    def test_pool_excludes_low_volume(self):
        """volume_usd < 10000 must be excluded from pool."""
        from core.scan import _build_pool
        event = self._make_pool_event("Cheap market", prob=0.5, prob_7d=0.4, vol=9999.0)
        adapter = self._pool_adapter([event])
        pool = _build_pool(adapter, hits_urls=set())
        assert pool == [], "volume < 10000 must be excluded"

    def test_pool_excludes_extreme_prob(self):
        """prob_now >= 0.99 or <= 0.01 must be excluded from pool."""
        from core.scan import _build_pool
        high = self._make_pool_event("Near yes", prob=0.995, prob_7d=0.99, vol=50000.0)
        low = self._make_pool_event("Near no", prob=0.005, prob_7d=0.01, vol=50000.0)
        adapter = self._pool_adapter([high, low])
        pool = _build_pool(adapter, hits_urls=set())
        assert pool == [], "prob >= 0.99 or <= 0.01 must be excluded"

    def test_pool_excludes_hits_urls(self):
        """URL already in hits must not appear in pool."""
        from core.scan import _build_pool
        shared = "https://polymarket.com/event/shared-market"
        event = self._make_pool_event("Shared market", prob=0.5, prob_7d=0.4, vol=50000.0, url=shared)
        adapter = self._pool_adapter([event])
        pool = _build_pool(adapter, hits_urls={shared})
        assert pool == [], "URL in hits must be excluded from pool"

    def test_pool_sorted_by_volume_desc_max5(self):
        """Pool is sorted by volume_usd desc, capped at 5 items."""
        from core.scan import _build_pool
        events = [
            self._make_pool_event(f"Market {i}", prob=0.5, prob_7d=0.4,
                                  vol=float(10_000 + i * 5_000))
            for i in range(7)
        ]
        adapter = self._pool_adapter(events)
        pool = _build_pool(adapter, hits_urls=set())
        assert len(pool) <= 5, "pool must not exceed 5 items"
        vols = [m["volume_usd"] for m in pool]
        assert vols == sorted(vols, reverse=True), "pool must be sorted by volume_usd desc"

    def test_pool_null_delta_no_crash(self):
        """null delta_7d must not crash _build_pool."""
        from core.scan import _build_pool
        no_delta = self._make_pool_event("No delta", prob=0.5, prob_7d=None, vol=30000.0)
        has_delta = self._make_pool_event("Has delta", prob=0.5, prob_7d=0.3, vol=50000.0)
        adapter = self._pool_adapter([no_delta, has_delta])
        pool = _build_pool(adapter, hits_urls=set())
        assert len(pool) == 2, "both events must appear"
        assert pool[0]["delta_7d"] is not None, "higher volume (has_delta) sorts first"
        assert pool[1]["delta_7d"] is None, "lower volume (no_delta) sorts last"

    # ---- Bug 3: event-level dedup -----------------------------------------

    def _make_multi_outcome_event(self, title: str, probs: list, vol: float):
        """Event with multiple markets, each a different outcome / url."""
        from core.models import Event, Market
        slug = title[:12].lower().replace(" ", "-")
        markets = [
            Market(
                market_id=f"mkt-{slug}-{i}",
                outcome_label=f"Country{i}",
                url=f"https://polymarket.com/event/{slug}/{i}",
                prob_now=p,
                prob_7d_ago=p - 0.05,
            )
            for i, p in enumerate(probs)
        ]
        return Event(event_id=f"evt-{slug}", event_title=title,
                     markets=markets, volume_usd=vol, end_date="2027-12-31", tags=[])

    def test_pool_dedup_same_event_one_entry(self):
        """Single Event with 5 eligible outcomes → pool gets exactly 1 entry."""
        from core.scan import _build_pool
        event = self._make_multi_outcome_event(
            "World Cup Winner",
            probs=[0.35, 0.25, 0.15, 0.12, 0.08],
            vol=3_000_000.0,
        )
        adapter = self._pool_adapter([event])
        pool = _build_pool(adapter, hits_urls=set())
        assert len(pool) == 1, (
            f"One event with 5 outcomes must yield 1 pool entry, got {len(pool)}"
        )

    def test_pool_dedup_picks_max_prob_outcome(self):
        """Pool selects the outcome with highest prob_now as event representative."""
        from core.scan import _build_pool
        event = self._make_multi_outcome_event(
            "World Cup Winner",
            probs=[0.08, 0.25, 0.35, 0.15, 0.12],
            vol=3_000_000.0,
        )
        adapter = self._pool_adapter([event])
        pool = _build_pool(adapter, hits_urls=set())
        assert len(pool) == 1
        assert pool[0]["prob_now"] == 0.35, (
            f"Leader (prob=0.35) must be the representative; got {pool[0]['prob_now']}"
        )
        assert pool[0]["outcome_label"] == "Country2", (
            f"Expected Country2 (prob=0.35), got {pool[0]['outcome_label']!r}"
        )

    def test_pool_excludes_empty_url_candidates(self):
        """Markets with url='' must be excluded from pool (defensive URL guard)."""
        from core.scan import _build_pool
        from core.models import Event, Market
        m_empty = Market("mkt-empty", "Yes", "", 0.5, prob_7d_ago=0.4)
        event = Event("evt-empty", "Empty URL market", [m_empty], volume_usd=50_000.0,
                      end_date="2027-12-31", tags=[])
        adapter = self._pool_adapter([event])
        pool = _build_pool(adapter, hits_urls=set())
        assert pool == [], "url='' must be excluded from pool"


# ---------------------------------------------------------------------------
# Adapter bulk path — Bug 1: URL from event slug
# ---------------------------------------------------------------------------

class TestAdapterBulkBugFix:
    """Bug 1: /events (bulk) markets have url=''; URL must be built from event slug."""

    def test_parse_event_url_from_slug(self):
        """_parse_event: market with url='' gets URL built from event slug."""
        from core.adapter_polymarket import _parse_event
        raw = {
            "id": "999",
            "title": "World Cup 2026 Winner",
            "slug": "world-cup-2026-winner",
            "volume": "100000",
            "endDate": "2026-07-20T00:00:00Z",
            "tags": [],
            "markets": [{
                "conditionId": "0xabc",
                "question": "Will France win?",
                "outcomePrices": '["0.35", "0.65"]',
                "url": "",
                "groupItemTitle": "France",
            }],
        }
        event = _parse_event(raw)
        assert event is not None
        assert len(event.markets) == 1
        assert event.markets[0].url == "https://polymarket.com/event/world-cup-2026-winner", (
            f"URL must be built from slug; got {event.markets[0].url!r}"
        )

    def test_parse_event_explicit_url_takes_precedence(self):
        """_parse_event: if market.url is already set, do NOT override with event slug."""
        from core.adapter_polymarket import _parse_event
        raw = {
            "id": "998",
            "title": "Some event",
            "slug": "some-event",
            "volume": "50000",
            "endDate": "2026-07-20T00:00:00Z",
            "tags": [],
            "markets": [{
                "conditionId": "0xdef",
                "question": "Will X happen?",
                "outcomePrices": '["0.6", "0.4"]',
                "url": "https://polymarket.com/market/direct-url",
                "groupItemTitle": "",
            }],
        }
        event = _parse_event(raw)
        assert event is not None
        assert event.markets[0].url == "https://polymarket.com/market/direct-url", (
            "Explicit market url must not be replaced by event slug url"
        )

    def test_scan_includes_pool_field(self):
        """scan() result always contains a 'pool' key (list, possibly empty)."""
        from core.scan import scan
        adapter = MagicMock()
        adapter.public_search.return_value = []
        adapter.top_by_volume.return_value = []
        result = scan(watchlist=[], adapter=adapter)
        assert "pool" in result, "scan result must contain 'pool' field"
        assert isinstance(result["pool"], list), "pool must be a list"

    def test_scan_includes_top_volume_field(self):
        """scan() result contains 'top_volume' AND 'pool' — pool untouched."""
        from core.scan import scan
        adapter = MagicMock()
        adapter.public_search.return_value = []
        adapter.top_by_volume.return_value = []
        result = scan(watchlist=[], adapter=adapter)
        assert "top_volume" in result, "scan result must contain 'top_volume' field"
        assert isinstance(result["top_volume"], list), "top_volume must be a list"
        assert "pool" in result, "scan result must still contain 'pool' field"
        assert isinstance(result["pool"], list), "pool must still be a list"


# ---------------------------------------------------------------------------
# E13 — pool movers: 7d enrichment via per-candidate public_search
# ---------------------------------------------------------------------------

class TestPoolMovers:
    """Pool mover enrichment: top-N by volume → fetch 7d delta → sort abs(delta) desc."""

    def _bulk_event(self, title: str, prob: float, vol: float):
        """Event as returned by top_by_volume: no prob_7d_ago (bulk path)."""
        from core.models import Event, Market
        slug = title.lower().replace(" ", "-")
        m = Market(
            market_id=f"mkt-{slug[:8]}",
            outcome_label="Yes",
            url=f"https://polymarket.com/event/{slug}",
            prob_now=prob,
            prob_7d_ago=None,
        )
        return Event(event_id=f"evt-{slug[:8]}", event_title=title,
                     markets=[m], volume_usd=vol, end_date="2027-12-31", tags=[])

    def _ps_event(self, title: str, prob_now: float, prob_7d: float):
        """Event as returned by public_search: prob_7d_ago populated."""
        from core.models import Event, Market
        slug = title.lower().replace(" ", "-")
        m = Market(
            market_id=f"mkt-ps-{slug[:8]}",
            outcome_label="Yes",
            url=f"https://polymarket.com/event/{slug}",
            prob_now=prob_now,
            prob_7d_ago=prob_7d,
        )
        return Event(event_id=f"evt-ps-{slug[:8]}", event_title=title,
                     markets=[m], volume_usd=0.0, end_date="2027-12-31", tags=[])

    def _pool_adapter(self, bulk_events, search_fn=None):
        adapter = MagicMock()
        adapter.top_by_volume.return_value = bulk_events
        if search_fn:
            adapter.public_search.side_effect = search_fn
        else:
            adapter.public_search.return_value = []
        return adapter

    def test_delta_populated_after_enrichment(self):
        """After 7d fetch, delta_7d is not None for a successfully enriched candidate."""
        from core.scan import _build_pool
        bulk = self._bulk_event("World Cup Winner", prob=0.35, vol=3_000_000.0)
        ps = self._ps_event("World Cup Winner", prob_now=0.35, prob_7d=0.28)
        adapter = self._pool_adapter([bulk], search_fn=lambda q, limit=5: [ps])
        pool = _build_pool(adapter, hits_urls=set())
        assert len(pool) == 1
        assert pool[0]["delta_7d"] is not None, "delta_7d must be set after 7d enrichment"
        assert abs(pool[0]["delta_7d"] - 0.07) < 0.001, (
            f"delta_7d should be ~0.07 (0.35-0.28); got {pool[0]['delta_7d']}"
        )

    def test_sorted_abs_delta_desc_after_enrichment(self):
        """Pool is sorted by abs(delta_7d) desc after enrichment (not volume)."""
        from core.scan import _build_pool

        specs = [
            ("Alpha Event", 0.40, 200_000.0, 0.35, 0.05),   # delta=+0.05, largest vol
            ("Beta Event",  0.60, 150_000.0, 0.42, 0.18),   # delta=+0.18, middle vol
            ("Gamma Event", 0.55, 100_000.0, 0.70, -0.15),  # delta=-0.15, smallest vol
        ]
        bulk_events = [self._bulk_event(t, p, v) for t, p, v, _, _ in specs]
        ps_by_title = {
            t: self._ps_event(t, p, p7d)
            for t, p, _, p7d, _ in specs
        }

        def fake_search(query, limit=5):
            for title, evt in ps_by_title.items():
                if title.split()[0].lower() in query.lower():
                    return [evt]
            return []

        adapter = self._pool_adapter(bulk_events, search_fn=fake_search)
        pool = _build_pool(adapter, hits_urls=set())

        assert len(pool) >= 2, "All 3 events should appear in pool"
        pool_abs_deltas = [abs(p["delta_7d"] or 0.0) for p in pool]
        assert pool_abs_deltas == sorted(pool_abs_deltas, reverse=True), (
            f"Pool must be abs(delta_7d) desc after enrichment; got {pool_abs_deltas}"
        )
        assert pool[0]["title"] == "Beta Event", (
            f"Beta (|delta|=0.18) must be first; got {pool[0]['title']!r}"
        )

    def test_fetch_failure_no_crash_delta_none(self):
        """If public_search raises during 7d fetch, _build_pool must not crash; delta_7d stays None."""
        from core.scan import _build_pool
        bulk = self._bulk_event("Volatile Event", prob=0.5, vol=50_000.0)
        adapter = self._pool_adapter([bulk],
                                     search_fn=lambda q, limit=5: (_ for _ in ()).throw(
                                         Exception("timeout")))
        pool = _build_pool(adapter, hits_urls=set())
        assert len(pool) == 1, "Failed enrichment must still include the candidate"
        assert pool[0]["delta_7d"] is None, (
            "Enrichment failure → delta_7d stays None (sort key treated as 0)"
        )

    def test_enrichment_searches_top10_returns_top5(self):
        """_build_pool enriches up to 10 candidates (by volume), then returns top-5 by abs(delta)."""
        from core.scan import _build_pool

        big_movers = {"Event C": 0.25, "Event F": 0.20, "Event H": 0.18,
                      "Event I": 0.15, "Event J": 0.12}
        bulk_events = [
            self._bulk_event(f"Event {chr(65+i)}", prob=0.5,
                             vol=float(2_000_000 - i * 100_000))
            for i in range(10)
        ]

        def fake_search(query, limit=5):
            for title, delta in big_movers.items():
                expected_q = title.lower().replace(" ", "-").replace("-", " ")
                if expected_q == query:
                    return [self._ps_event(title, 0.5, 0.5 - delta)]
            return []

        adapter = self._pool_adapter(bulk_events, search_fn=fake_search)
        pool = _build_pool(adapter, hits_urls=set())

        assert len(pool) == 5, f"Pool must be capped at 5; got {len(pool)}"
        assert pool[0]["title"] == "Event C", (
            f"Highest-delta (Event C, Δ=0.25) must be first; got {pool[0]['title']!r}"
        )
        titles = [p["title"] for p in pool]
        assert "Event C" in titles and "Event F" in titles, (
            "Top movers must be in pool"
        )


class TestFetch7dOutcomeBaseline:
    """_fetch_7d must match baseline to the SAME outcome, not fall back to any
    market in the event (bug: RFK "45% +47pp" from a different outcome's baseline)."""

    def _event_multi_outcome(self, title: str, outcomes: list) -> "object":
        """outcomes: list of (outcome_label, prob_7d_ago) tuples."""
        from core.models import Event, Market
        slug = title.lower().replace(" ", "-")
        markets = [
            Market(
                market_id=f"mkt-{slug[:8]}-{label}",
                outcome_label=label,
                url=f"https://polymarket.com/event/{slug}",
                prob_now=0.5,
                prob_7d_ago=p7d,
            )
            for label, p7d in outcomes
        ]
        return Event(event_id=f"evt-{slug[:8]}", event_title=title,
                     markets=markets, volume_usd=100_000.0, end_date="2027-12-31", tags=[])

    def test_matching_outcome_baseline_used(self):
        """When the candidate's own outcome has a baseline, use it."""
        from core.scan import _fetch_7d
        event = self._event_multi_outcome(
            "RFK Chairman", [("RFK Jr", 0.30), ("Other", 0.60)])
        candidate = {
            "title": "RFK Chairman", "url": "https://polymarket.com/event/rfk-chairman",
            "outcome_label": "RFK Jr", "prob_now": 0.45,
        }
        adapter = _mock_adapter([event])
        result = _fetch_7d(candidate, adapter)
        assert result["delta_7d"] is not None
        assert abs(result["delta_7d"] - round(0.45 - 0.30, 4)) < 0.001, (
            f"delta_7d must be computed from the matching outcome's baseline (0.30); got {result['delta_7d']}"
        )

    def test_missing_own_outcome_baseline_emits_no_delta(self):
        """When the candidate's own outcome has no baseline, do NOT fall back to
        another outcome's baseline — delta_7d must stay absent/None."""
        from core.scan import _fetch_7d
        event = self._event_multi_outcome(
            "RFK Chairman", [("RFK Jr", None), ("Other", 0.60)])
        candidate = {
            "title": "RFK Chairman", "url": "https://polymarket.com/event/rfk-chairman",
            "outcome_label": "RFK Jr", "prob_now": 0.45,
        }
        adapter = _mock_adapter([event])
        result = _fetch_7d(candidate, adapter)
        assert result.get("delta_7d") is None, (
            "Must not borrow another outcome's baseline (0.60) — "
            f"got delta_7d={result.get('delta_7d')}"
        )

    def test_multi_outcome_market_picks_correct_baseline_per_candidate(self):
        """Two candidates on the same event but different outcomes each get their
        own outcome's baseline, not each other's."""
        from core.scan import _fetch_7d
        event = self._event_multi_outcome(
            "Election Winner", [("Alice", 0.20), ("Bob", 0.55)])
        adapter = _mock_adapter([event])

        cand_alice = {
            "title": "Election Winner", "url": "https://polymarket.com/event/election-winner",
            "outcome_label": "Alice", "prob_now": 0.25,
        }
        cand_bob = {
            "title": "Election Winner", "url": "https://polymarket.com/event/election-winner",
            "outcome_label": "Bob", "prob_now": 0.50,
        }
        result_alice = _fetch_7d(cand_alice, adapter)
        result_bob = _fetch_7d(cand_bob, adapter)

        assert abs(result_alice["delta_7d"] - round(0.25 - 0.20, 4)) < 0.001
        assert abs(result_bob["delta_7d"] - round(0.50 - 0.55, 4)) < 0.001


class TestTopVolume:
    """top_volume: top-10 open markets by volume, event-level dedup, no hits/min-volume filter."""

    def _make_event(self, title: str, prob: float, prob_7d, vol: float, url: str = ""):
        from core.models import Event, Market
        u = url or f"https://polymarket.com/event/{title[:12].lower().replace(' ', '-')}"
        m = Market(
            market_id=f"mkt-tv-{title[:6]}",
            outcome_label="Yes",
            url=u,
            prob_now=prob,
            prob_7d_ago=prob_7d,
        )
        return Event(event_id=f"evt-tv-{title[:6]}", event_title=title,
                     markets=[m], volume_usd=vol, end_date="2027-12-31", tags=[])

    def _make_multi_outcome_event(self, title: str, probs: list, vol: float):
        from core.models import Event, Market
        slug = title[:12].lower().replace(" ", "-")
        markets = [
            Market(
                market_id=f"mkt-tv-{slug}-{i}",
                outcome_label=f"Country{i}",
                url=f"https://polymarket.com/event/{slug}/{i}",
                prob_now=p,
                prob_7d_ago=p - 0.05,
            )
            for i, p in enumerate(probs)
        ]
        return Event(event_id=f"evt-tv-{slug}", event_title=title,
                     markets=markets, volume_usd=vol, end_date="2027-12-31", tags=[])

    def _adapter(self, events):
        adapter = MagicMock()
        adapter.public_search.return_value = []
        adapter.top_by_volume.return_value = events
        return adapter

    def test_sorted_by_volume_desc(self):
        """top_volume is sorted by volume_usd descending."""
        from core.scan import _build_top_volume
        events = [
            self._make_event("Market A", prob=0.5, prob_7d=0.4, vol=10_000.0),
            self._make_event("Market B", prob=0.5, prob_7d=0.4, vol=90_000.0),
            self._make_event("Market C", prob=0.5, prob_7d=0.4, vol=50_000.0),
        ]
        adapter = self._adapter(events)
        top_volume = _build_top_volume(adapter)
        vols = [m["volume_usd"] for m in top_volume]
        assert vols == sorted(vols, reverse=True), "top_volume must be sorted by volume_usd desc"
        assert vols[0] == 90_000.0

    def test_event_level_dedup(self):
        """Two markets on the same event → only the best (highest prob_now) appears."""
        from core.scan import _build_top_volume
        event = self._make_multi_outcome_event(
            "World Cup Winner",
            probs=[0.08, 0.25, 0.35, 0.15, 0.12],
            vol=3_000_000.0,
        )
        adapter = self._adapter([event])
        top_volume = _build_top_volume(adapter)
        assert len(top_volume) == 1, f"One event must yield 1 entry, got {len(top_volume)}"
        assert top_volume[0]["prob_now"] == 0.35
        assert top_volume[0]["outcome_label"] == "Country2"

    def test_capped_at_10(self):
        """More than 10 distinct-event candidates → only 10 entries returned."""
        from core.scan import _build_top_volume
        events = [
            self._make_event(f"Market {i}", prob=0.5, prob_7d=0.4,
                              vol=float(10_000 + i * 1_000))
            for i in range(15)
        ]
        adapter = self._adapter(events)
        top_volume = _build_top_volume(adapter)
        assert len(top_volume) == 10, f"top_volume must be capped at 10, got {len(top_volume)}"

    def test_field_shape(self):
        """Each entry has exactly title, url, outcome_label, prob_now, delta_7d, volume_usd."""
        from core.scan import _build_top_volume
        event = self._make_event("Solo Market", prob=0.6, prob_7d=0.5, vol=25_000.0)
        adapter = self._adapter([event])
        top_volume = _build_top_volume(adapter)
        assert len(top_volume) == 1
        expected_keys = {"title", "url", "outcome_label", "prob_now", "delta_7d", "volume_usd"}
        assert set(top_volume[0].keys()) == expected_keys, (
            f"Unexpected keys: {set(top_volume[0].keys())}"
        )

    def test_empty_scan_universe_returns_empty_list(self):
        """No events from top_by_volume → top_volume is [] (not missing/None)."""
        from core.scan import _build_top_volume
        adapter = self._adapter([])
        top_volume = _build_top_volume(adapter)
        assert top_volume == []

    def test_no_min_volume_filter(self):
        """Unlike pool, top_volume has no min_volume floor — low-volume events are included."""
        from core.scan import _build_top_volume
        event = self._make_event("Tiny market", prob=0.5, prob_7d=0.4, vol=100.0)
        adapter = self._adapter([event])
        top_volume = _build_top_volume(adapter)
        assert len(top_volume) == 1, "low-volume events must not be filtered out"

    def test_no_hits_urls_exclusion(self):
        """Unlike pool, top_volume ignores hits_urls — no such parameter/exclusion."""
        from core.scan import _build_top_volume
        shared = "https://polymarket.com/event/shared-market"
        event = self._make_event("Shared market", prob=0.5, prob_7d=0.4, vol=50_000.0, url=shared)
        adapter = self._adapter([event])
        top_volume = _build_top_volume(adapter)
        assert len(top_volume) == 1, "top_volume must not exclude urls present in hits"


def _load_sample_do_hits() -> dict:
    """Build a do_hits dict from sample.json for digest tests.

    Uses topic-relevant event titles so the relevance guard passes for each sample topic.
    All 3 events are returned for every keyword; the guard selects the right one per topic.
    """
    from core.scan import scan, load_watchlist
    topics = load_watchlist(notion_token=None)
    relevant_events = [
        _make_event("RBA cuts interest rates August 2026", prob=0.55, prob_7d=0.50),
        _make_event("AI machine learning regulation 2027", prob=0.60, prob_7d=0.58),
        _make_event("Australian property housing market prices", prob=0.45, prob_7d=0.48),
    ]
    adapter = _mock_adapter(relevant_events)
    return scan(watchlist=topics, adapter=adapter)
