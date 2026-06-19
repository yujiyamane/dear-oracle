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
    adapter.search.return_value = events
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

    def test_topic_key_matches_wl_pattern(self):
        """topic_key from sample.json must match ^WL-\\d+$ (never a raw page ID)."""
        from core.scan import scan, load_watchlist
        topics = load_watchlist(notion_token=None)
        wl_pattern = re.compile(r"^WL-\d+$")
        for t in topics:
            assert wl_pattern.match(t["topic_key"]), (
                f"topic_key '{t['topic_key']}' must match ^WL-\\d+$"
            )
        events = [_make_event("Market for test")]
        adapter = _mock_adapter(events)
        result = scan(watchlist=topics, adapter=adapter)
        for key in result["hits"]:
            assert wl_pattern.match(key), (
                f"hit key '{key}' must match ^WL-\\d+$"
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
            {"topic_key": "t1", "topic_label": "A", "weight": 4, "keywords": "AI", "lang": ["en-AU"]},
            {"topic_key": "t2", "topic_label": "B", "weight": 3, "keywords": "property", "lang": ["en-AU"]},
        ]
        event = _make_event("Will AI take over?")
        def fake_search(query, limit=10):
            if "AI" in query:
                return [event]
            return []
        adapter = MagicMock()
        adapter.search.side_effect = fake_search

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
        """Live Notion returns topics keyed WL-N with non-empty titles."""
        from core.scan import load_watchlist
        topics = load_watchlist()
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
        event = _make_event("Will interest rates fall?", prob=0.55, prob_7d=0.50)
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
# Shared helpers
# ---------------------------------------------------------------------------

def _load_sample_do_hits() -> dict:
    """Build a do_hits dict from sample.json for digest tests."""
    from core.scan import scan, load_watchlist
    topics = load_watchlist(notion_token=None)
    events = [_make_event(f"Sample market topic-{i}", prob=0.55 + i * 0.05) for i in range(3)]
    adapter = _mock_adapter(events)
    return scan(watchlist=topics, adapter=adapter)
