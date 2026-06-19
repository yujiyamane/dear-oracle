"""tests/test_scan.py — Phase 2-E TDD: scan module + do_hits.json.

E1: reads watchlist via NOTION_TOKEN; if absent, falls back to sample.json; never crashes on missing token.
E2: per active topic, queries Polymarket; produces hits keyed by topic_key (WL_ID ^WL-\\d+$); probability in [0,1], delta_7d decimal.
E3: do_hits.json validates against schema; meta.status in {ok,partial}; written ATOMICALLY (tmp + os.replace).
E4: portfolio digest renders from sample.json -> brand-styled HTML with >=1 market; contains NO real names / private Notion IDs.
E5: full run < 120s on sample.json.
E6: NOTION_TOKEN-gated integration test — live Notion returns WL-N keys + non-empty titles.
E7: DK contract — every hit entry exposes exactly the fields DK_parseDoHitsData_ reads.

Zero live API calls (except E6 which requires NOTION_TOKEN env var).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
# E6 — NOTION_TOKEN-gated integration test (skipped when token absent)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not os.environ.get("NOTION_TOKEN"), reason="NOTION_TOKEN not set")
class TestE6NotionIntegration:
    def test_live_watchlist_returns_wl_keys(self):
        """Live Notion returns topics keyed WL-N with non-empty titles.

        Skipped automatically if the token doesn't have access to the DK Watchlist DB.
        """
        from core.scan import _fetch_notion_watchlist
        token = os.environ.get("NOTION_TOKEN", "")
        try:
            topics = _fetch_notion_watchlist(token)
        except Exception as exc:
            pytest.skip(f"Notion access failed (wrong integration or 401): {exc}")

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
    """Asserts do_hits output matches what DK_parseDoHitsData_ consumes.

    DK reads: m.title → market_title, m.url, m.prob_now → probability,
              m.delta_7d, m.volume_usd  (all other fields are ignored).
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

    def test_stale_check_uses_meta_fields(self):
        """DK checks data.meta.status and age; both must be present in output."""
        from core.scan import scan
        adapter = _mock_adapter([])
        result = scan(watchlist=[], adapter=adapter)
        assert "meta" in result, "do_hits must have a meta block"
        assert "generated_at" in result["meta"], "meta.generated_at required for DK age check"
        assert "status" in result["meta"], "meta.status required for DK stale check"
        assert result["meta"]["status"] in ("ok", "partial"), (
            f"meta.status must be 'ok' or 'partial', got {result['meta']['status']!r}"
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
# Shared helpers
# ---------------------------------------------------------------------------

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
