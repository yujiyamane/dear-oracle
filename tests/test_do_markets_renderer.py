"""tests/test_do_markets_renderer.py — TDD for do_markets_renderer.

M1: full do_hits → fragment contains prob%, delta, topic keys; is a valid <section>.
M2: empty hits → returns empty string (safe omission, never crashes DK).
M3: missing/None market fields → no crash, graceful rendering.
M4: source-agnostic — output contains NO reference to the data source name.
M5: write_markets_fragment writes file atomically and is idempotent.
M6: malformed/None do_hits input → function never raises.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FULL_DO_HITS = {
    "meta": {
        "generated_at": "2026-06-23T00:04:11.984118+00:00",
        "status": "ok",
        "topics_queried": 18,
        "topics_with_hits": 2,
    },
    "hits": {
        "WL-5": [
            {
                "title": "Will interest rates be cut?",
                "url": "https://example.com/market/1",
                "prob_now": 0.72,
                "delta_7d": 0.05,
                "volume_usd": 1_500_000.0,
            }
        ],
        "WL-12": [
            {
                "title": "Will property prices rise?",
                "url": "https://example.com/market/2",
                "prob_now": 0.48,
                "delta_7d": -0.03,
                "volume_usd": 250_000.0,
            },
            {
                "title": "Another market",
                "url": "https://example.com/market/3",
                "prob_now": 0.60,
                "delta_7d": None,
                "volume_usd": None,
            },
        ],
    },
}

EMPTY_DO_HITS = {
    "meta": {
        "generated_at": "2026-06-23T00:04:11.984118+00:00",
        "status": "ok",
        "topics_queried": 18,
        "topics_with_hits": 0,
    },
    "hits": {},
}

PARTIAL_DO_HITS = {
    "meta": {"generated_at": "2026-06-23T00:04:11.984118+00:00", "status": "partial"},
    "hits": {
        "WL-6": [
            {
                "title": "Some event",
                "url": "https://example.com/market/4",
                "prob_now": None,
                "delta_7d": None,
                "volume_usd": None,
            }
        ]
    },
}


# ---------------------------------------------------------------------------
# M1 — full do_hits produces a well-formed section with expected content
# ---------------------------------------------------------------------------

class TestM1FullDoHits:
    def test_returns_section_element(self):
        """Fragment must open with <section and close with </section>."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(FULL_DO_HITS)
        assert html.strip().startswith("<section"), f"Expected <section> opener, got: {html[:80]}"
        assert "</section>" in html

    def test_contains_prob_percentage(self):
        """Fragment must show prob_now as a % string (e.g. '72%')."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(FULL_DO_HITS)
        assert "72%" in html, "Expected '72%' for prob_now=0.72"

    def test_contains_positive_delta(self):
        """Fragment must show positive delta_7d with a + sign."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(FULL_DO_HITS)
        assert "+5" in html or "+5pp" in html, "Expected positive delta indicator for delta_7d=0.05"

    def test_contains_negative_delta(self):
        """Fragment must show negative delta_7d with a negative sign."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(FULL_DO_HITS)
        assert "-3" in html or "-3pp" in html, "Expected negative delta indicator for delta_7d=-0.03"

    def test_contains_volume_formatted(self):
        """Fragment must format volume_usd into human-readable form (e.g. $1.5M)."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(FULL_DO_HITS)
        assert "$1.5M" in html or "$1,500" in html or "1.5M" in html, "Expected formatted volume"

    def test_contains_market_title(self):
        """Fragment must include market titles."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(FULL_DO_HITS)
        assert "interest rates" in html.lower() or "Will interest rates" in html

    def test_null_delta_shows_dash_or_empty(self):
        """Null delta_7d must render gracefully (dash or simply omitted)."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(FULL_DO_HITS)
        # Should not crash and should not output 'None'
        assert "None" not in html

    def test_null_volume_does_not_crash(self):
        """Null volume_usd must not crash and must not output 'None'."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(FULL_DO_HITS)
        assert "None" not in html

    def test_uses_inline_styles_only(self):
        """Fragment must use inline styles (no class= referencing external CSS)."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(FULL_DO_HITS)
        # Inline styles means style= attributes present
        assert 'style=' in html

    def test_brand_palette_colours_present(self):
        """At least one brand colour must appear in the fragment."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(FULL_DO_HITS)
        brand = {"#264653", "#2a9d8f", "#e9c46a", "#f4a261", "#e76f51",
                 "#264653".upper(), "#2A9D8F", "#E9C46A", "#F4A261", "#E76F51"}
        assert any(c.lower() in html.lower() for c in brand), "Expected at least one brand colour"


# ---------------------------------------------------------------------------
# M2 — empty hits → empty string (safe omission)
# ---------------------------------------------------------------------------

class TestM2EmptyHits:
    def test_empty_hits_returns_empty_string(self):
        """When hits is empty, render_markets_fragment must return '' (omit section)."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(EMPTY_DO_HITS)
        assert html == "", f"Expected empty string for empty hits, got: {html[:80]}"

    def test_missing_hits_key_returns_empty_string(self):
        """When 'hits' key is absent, must return ''."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment({"meta": {"status": "ok"}})
        assert html == ""


# ---------------------------------------------------------------------------
# M3 — missing/None fields per market → no crash
# ---------------------------------------------------------------------------

class TestM3MissingFields:
    def test_all_none_fields_no_crash(self):
        """Market with all None fields must not raise."""
        from core.do_markets_renderer import render_markets_fragment
        try:
            html = render_markets_fragment(PARTIAL_DO_HITS)
        except Exception as exc:
            pytest.fail(f"render_markets_fragment raised on all-None fields: {exc}")
        assert isinstance(html, str)

    def test_missing_title_no_crash(self):
        """Market with no 'title' field must not raise."""
        from core.do_markets_renderer import render_markets_fragment
        data = {
            "meta": {"status": "ok"},
            "hits": {"WL-1": [{"url": "https://example.com", "prob_now": 0.5}]},
        }
        html = render_markets_fragment(data)
        assert isinstance(html, str)
        assert "None" not in html

    def test_missing_url_no_crash(self):
        """Market with no 'url' field must not raise."""
        from core.do_markets_renderer import render_markets_fragment
        data = {
            "meta": {"status": "ok"},
            "hits": {"WL-2": [{"title": "Some event", "prob_now": 0.3}]},
        }
        html = render_markets_fragment(data)
        assert isinstance(html, str)


# ---------------------------------------------------------------------------
# M4 — source-agnostic (no data source name in output)
# ---------------------------------------------------------------------------

class TestM4SourceAgnostic:
    FORBIDDEN_TERMS = ["polymarket", "Polymarket", "PolyMarket", "POLYMARKET"]

    def test_no_source_name_in_output(self):
        """Output must not mention the data source by name."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(FULL_DO_HITS)
        for term in self.FORBIDDEN_TERMS:
            assert term not in html, f"Found forbidden term '{term}' in output"

    def test_no_source_name_in_empty_output(self):
        """Even empty output must not mention the data source."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(EMPTY_DO_HITS)
        for term in self.FORBIDDEN_TERMS:
            assert term not in html


# ---------------------------------------------------------------------------
# M7 — curation: resolved-drop, dedup, |Δ7d| sort, cap, volume threshold
# ---------------------------------------------------------------------------

# Fixture that mirrors live do_hits.json structure (19 markets → should curate to 3)
LIVE_LIKE_DO_HITS = {
    "meta": {"generated_at": "2026-06-23T00:04:00+00:00", "status": "ok",
             "topics_queried": 7, "topics_with_hits": 7},
    "hits": {
        "WL-5": [
            {"title": "World Cup: Team Unbeaten", "url": "https://ex.com/1", "prob_now": 0.75, "delta_7d": 0.405, "volume_usd": 99000},
            {"title": "World Cup: Team Unbeaten", "url": "https://ex.com/2", "prob_now": 0.60, "delta_7d": 0.10,  "volume_usd": 99000},
            {"title": "World Cup: Team Unbeaten", "url": "https://ex.com/3", "prob_now": 0.61, "delta_7d": 0.314, "volume_usd": 99000},
        ],
        "WL-6": [
            {"title": "WHO declare PHE", "url": "https://ex.com/4", "prob_now": 0.0,  "delta_7d": 0.0,   "volume_usd": 11000},
        ],
        "WL-11": [
            {"title": "RBA Decision August", "url": "https://ex.com/5", "prob_now": 0.01, "delta_7d": -0.001, "volume_usd": 3000},
            {"title": "RBA Decision August", "url": "https://ex.com/6", "prob_now": 0.01, "delta_7d": -0.062, "volume_usd": 3000},
            {"title": "RBA Decision August", "url": "https://ex.com/7", "prob_now": 0.85, "delta_7d": 0.015,  "volume_usd": 3000},
        ],
        "WL-12": [
            {"title": "Best AI model June", "url": "https://ex.com/8",  "prob_now": 0.07, "delta_7d": 0.012,  "volume_usd": 16_591_000},
            {"title": "Best AI model June", "url": "https://ex.com/9",  "prob_now": 0.01, "delta_7d": -0.022, "volume_usd": 16_591_000},
            {"title": "Best AI model June", "url": "https://ex.com/10", "prob_now": 0.0,  "delta_7d": None,   "volume_usd": 16_591_000},
        ],
        "WL-16": [
            {"title": "Stray Kids Box Office", "url": "https://ex.com/11", "prob_now": 0.0, "delta_7d": None, "volume_usd": 31000},
            {"title": "Stray Kids Box Office", "url": "https://ex.com/12", "prob_now": 0.0, "delta_7d": None, "volume_usd": 31000},
            {"title": "Stray Kids Box Office", "url": "https://ex.com/13", "prob_now": 0.0, "delta_7d": None, "volume_usd": 31000},
        ],
        "WL-29": [
            {"title": "Top AI model Dec", "url": "https://ex.com/14", "prob_now": 1.0, "delta_7d": 0.0, "volume_usd": 1_108_000},
            {"title": "Top AI model Dec", "url": "https://ex.com/15", "prob_now": 0.0, "delta_7d": 0.0, "volume_usd": 1_108_000},
            {"title": "Top AI model Dec", "url": "https://ex.com/16", "prob_now": 0.0, "delta_7d": 0.0, "volume_usd": 1_108_000},
        ],
        "WL-30": [
            {"title": "World Test Championship", "url": "https://ex.com/17", "prob_now": 1.0,  "delta_7d": 0.309,  "volume_usd": 499000},
            {"title": "World Test Championship", "url": "https://ex.com/18", "prob_now": 0.0,  "delta_7d": -0.289, "volume_usd": 499000},
            {"title": "World Test Championship", "url": "https://ex.com/19", "prob_now": 0.0,  "delta_7d": -0.489, "volume_usd": 499000},
        ],
    },
}


class TestM7Curation:
    def test_resolved_exact_zero_excluded(self):
        """prob_now == 0.0 must be excluded from rendered output."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {"WL-1": [
            {"title": "Resolved zero", "url": "https://ex.com", "prob_now": 0.0, "delta_7d": 0.5, "volume_usd": 100000},
            {"title": "Live market",   "url": "https://ex.com", "prob_now": 0.5, "delta_7d": 0.1, "volume_usd": 100000},
        ]}}
        html = render_markets_fragment(data)
        assert "Live market" in html
        assert "Resolved zero" not in html

    def test_resolved_exact_one_excluded(self):
        """prob_now == 1.0 must be excluded."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {"WL-1": [
            {"title": "Resolved one", "url": "https://ex.com", "prob_now": 1.0, "delta_7d": 0.3, "volume_usd": 50000},
            {"title": "Live market",  "url": "https://ex.com", "prob_now": 0.6, "delta_7d": 0.1, "volume_usd": 50000},
        ]}}
        html = render_markets_fragment(data)
        assert "Live market" in html
        assert "Resolved one" not in html

    def test_near_resolved_threshold_excluded(self):
        """prob_now <= resolved_threshold must be excluded (default 0.01)."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {"WL-1": [
            {"title": "Near zero", "url": "https://ex.com", "prob_now": 0.01, "delta_7d": 0.4, "volume_usd": 50000},
            {"title": "Live",      "url": "https://ex.com", "prob_now": 0.50, "delta_7d": 0.1, "volume_usd": 50000},
        ]}}
        html = render_markets_fragment(data)
        assert "Live" in html
        assert "Near zero" not in html

    def test_dedup_same_title_keeps_highest_prob(self):
        """Multiple markets with same title in a WL key → only highest prob_now shown."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {"WL-1": [
            {"title": "Same Event", "url": "https://ex.com/a", "prob_now": 0.45, "delta_7d": 0.05, "volume_usd": 50000},
            {"title": "Same Event", "url": "https://ex.com/b", "prob_now": 0.72, "delta_7d": 0.10, "volume_usd": 50000},
            {"title": "Same Event", "url": "https://ex.com/c", "prob_now": 0.33, "delta_7d": 0.20, "volume_usd": 50000},
        ]}}
        html = render_markets_fragment(data)
        # 72% must appear; 45% and 33% must not (only one row for this event)
        assert "72%" in html
        assert html.count("Same Event") == 1, "Expected exactly one row per event title"

    def test_sort_by_abs_delta_descending(self):
        """Markets must be ordered by |delta_7d| descending across WL keys."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {
            "WL-A": [{"title": "Small delta", "url": "https://ex.com/a", "prob_now": 0.5, "delta_7d": 0.02, "volume_usd": 10000}],
            "WL-B": [{"title": "Big delta",   "url": "https://ex.com/b", "prob_now": 0.5, "delta_7d": 0.30, "volume_usd": 10000}],
            "WL-C": [{"title": "Neg delta",   "url": "https://ex.com/c", "prob_now": 0.5, "delta_7d": -0.15, "volume_usd": 10000}],
        }}
        html = render_markets_fragment(data)
        pos_big  = html.index("Big delta")
        pos_neg  = html.index("Neg delta")
        pos_small = html.index("Small delta")
        assert pos_big < pos_neg < pos_small, "Expected order: Big(0.30) > Neg(-0.15) > Small(0.02)"

    def test_cap_at_max_markets(self):
        """render_markets_fragment(data, max_markets=2) must show at most 2 rows."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {f"WL-{i}": [
            {"title": f"Market {i}", "url": "https://ex.com", "prob_now": 0.5, "delta_7d": i * 0.01, "volume_usd": 10000}
        ] for i in range(1, 8)}}
        html = render_markets_fragment(data, max_markets=2)
        # Count rows by counting occurrences of "Market " prefix in content
        count = sum(1 for i in range(1, 8) if f"Market {i}" in html)
        assert count <= 2, f"Expected ≤2 markets, found {count}"

    def test_min_volume_filters_thin_markets(self):
        """Markets below min_volume_usd must be excluded."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {"WL-1": [
            {"title": "Thin market", "url": "https://ex.com/a", "prob_now": 0.5, "delta_7d": 0.5, "volume_usd": 500},
            {"title": "Fat market",  "url": "https://ex.com/b", "prob_now": 0.5, "delta_7d": 0.1, "volume_usd": 50000},
        ]}}
        html = render_markets_fragment(data, min_volume_usd=1000)
        assert "Fat market" in html
        assert "Thin market" not in html

    def test_none_delta_sorts_last(self):
        """Markets with delta_7d=None must sort after markets with real deltas."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {
            "WL-A": [{"title": "No delta",   "url": "https://ex.com/a", "prob_now": 0.5, "delta_7d": None, "volume_usd": 10000}],
            "WL-B": [{"title": "Has delta",  "url": "https://ex.com/b", "prob_now": 0.5, "delta_7d": 0.05, "volume_usd": 10000}],
        }}
        html = render_markets_fragment(data)
        assert html.index("Has delta") < html.index("No delta"), "None-delta must sort last"

    def test_integration_live_like_19_to_3(self):
        """Live-like 19-market fixture must curate down to exactly 3 rows: World Cup, RBA, AI."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(LIVE_LIKE_DO_HITS)
        assert "World Cup" in html,      "Expected World Cup market to survive curation"
        assert "RBA Decision" in html,   "Expected RBA market to survive curation"
        assert "Best AI model" in html,  "Expected AI model market to survive curation"
        assert "Stray Kids" not in html, "Stray Kids must be excluded (resolved 0%)"
        assert "WHO declare" not in html, "WHO PHE must be excluded (resolved 0%)"
        # Exactly 3 unique event titles should be present
        count = sum(1 for title in ("World Cup", "RBA Decision", "Best AI model") if title in html)
        assert count == 3
        # Confirm World Cup is the top row (highest |Δ7d|)
        assert html.index("World Cup") < html.index("RBA Decision")
        assert html.index("World Cup") < html.index("Best AI model")

    def test_all_resolved_returns_empty(self):
        """If all markets are resolved after curation, returns ''."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {"WL-1": [
            {"title": "Done", "url": "https://ex.com", "prob_now": 0.0,  "delta_7d": 0.9, "volume_usd": 1000000},
            {"title": "Done", "url": "https://ex.com", "prob_now": 1.0,  "delta_7d": 0.9, "volume_usd": 1000000},
        ]}}
        html = render_markets_fragment(data)
        assert html == "", "All-resolved hits must produce empty string"


# ---------------------------------------------------------------------------
# M5 — write_markets_fragment: atomic write, idempotent
# ---------------------------------------------------------------------------

class TestM5WriteMarketsFragment:
    def test_writes_file(self, tmp_path):
        """write_markets_fragment must create the output file."""
        from core.do_markets_renderer import write_markets_fragment
        out = tmp_path / "do_markets.html"
        write_markets_fragment(FULL_DO_HITS, out)
        assert out.exists()

    def test_writes_valid_html(self, tmp_path):
        """Written file must contain the section HTML."""
        from core.do_markets_renderer import write_markets_fragment
        out = tmp_path / "do_markets.html"
        write_markets_fragment(FULL_DO_HITS, out)
        content = out.read_text(encoding="utf-8")
        assert "<section" in content

    def test_idempotent_overwrite(self, tmp_path):
        """Calling write twice overwrites cleanly."""
        from core.do_markets_renderer import write_markets_fragment
        out = tmp_path / "do_markets.html"
        write_markets_fragment(FULL_DO_HITS, out)
        first = out.read_text(encoding="utf-8")
        write_markets_fragment(FULL_DO_HITS, out)
        second = out.read_text(encoding="utf-8")
        assert first == second

    def test_empty_hits_writes_empty_file(self, tmp_path):
        """Empty hits must write an empty file (DK reads empty string → omits section)."""
        from core.do_markets_renderer import write_markets_fragment
        out = tmp_path / "do_markets.html"
        write_markets_fragment(EMPTY_DO_HITS, out)
        assert out.exists()
        assert out.read_text(encoding="utf-8") == ""

    def test_creates_parent_dirs(self, tmp_path):
        """write_markets_fragment must create parent directories if missing."""
        from core.do_markets_renderer import write_markets_fragment
        out = tmp_path / "subdir" / "do_markets.html"
        write_markets_fragment(FULL_DO_HITS, out)
        assert out.exists()


# ---------------------------------------------------------------------------
# M6 — malformed / None input never raises
# ---------------------------------------------------------------------------

class TestM6MalformedInput:
    def test_none_input_raises_nothing(self):
        from core.do_markets_renderer import render_markets_fragment
        try:
            html = render_markets_fragment(None)  # type: ignore[arg-type]
        except Exception as exc:
            pytest.fail(f"render_markets_fragment(None) raised: {exc}")
        assert isinstance(html, str)

    def test_empty_dict_raises_nothing(self):
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment({})
        assert isinstance(html, str)
        assert html == ""

    def test_hits_is_none_raises_nothing(self):
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment({"meta": {}, "hits": None})
        assert isinstance(html, str)

    def test_markets_list_is_not_list_raises_nothing(self):
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment({"hits": {"WL-1": "bad-value"}})
        assert isinstance(html, str)


# ---------------------------------------------------------------------------
# M8 — outcome_label rendering (DO-6.1)
# ---------------------------------------------------------------------------

class TestM8OutcomeLabel:
    """Renderer appends '— {label}' to title when outcome_label is non-empty."""

    def test_label_appended_to_title_when_present(self):
        """When outcome_label is set, row shows '{title} — {label}'."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {"WL-12": [{
            "title": "Which company has best AI model?",
            "outcome_label": "Anthropic",
            "url": "https://example.com/ai",
            "prob_now": 0.93,
            "delta_7d": 0.05,
            "volume_usd": 16_000_000,
        }]}}
        html = render_markets_fragment(data)
        assert "Which company has best AI model? — Anthropic" in html, (
            "Row must show 'title — label' when outcome_label is set"
        )

    def test_missing_label_key_shows_bare_title(self):
        """When outcome_label key is absent, row shows bare title (no ' — ')."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {"WL-5": [{
            "title": "Will interest rates be cut?",
            "url": "https://example.com/rates",
            "prob_now": 0.72,
            "delta_7d": 0.05,
            "volume_usd": 1_500_000,
        }]}}
        html = render_markets_fragment(data)
        assert "Will interest rates be cut?" in html
        assert " — " not in html, "No em-dash separator when outcome_label absent"

    def test_empty_label_shows_bare_title(self):
        """When outcome_label is empty string, row shows bare title."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {"WL-5": [{
            "title": "Will rates be cut?",
            "outcome_label": "",
            "url": "https://example.com/rates",
            "prob_now": 0.72,
            "delta_7d": 0.05,
            "volume_usd": 1_500_000,
        }]}}
        html = render_markets_fragment(data)
        assert "Will rates be cut?" in html
        assert " — " not in html, "No em-dash separator when outcome_label is empty"

    def test_dedup_keeps_leader_label(self):
        """Dedup by title keeps the highest-prob entry — that entry must carry its label."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {"WL-12": [
            {"title": "Best AI model", "outcome_label": "Anthropic",
             "url": "https://ex.com/1", "prob_now": 0.93, "delta_7d": 0.05, "volume_usd": 10_000_000},
            {"title": "Best AI model", "outcome_label": "Google",
             "url": "https://ex.com/2", "prob_now": 0.06, "delta_7d": 0.01, "volume_usd": 10_000_000},
        ]}}
        html = render_markets_fragment(data)
        assert "Best AI model — Anthropic" in html, "Dedup must keep leader with its label"
        assert "93%" in html
        assert html.count("Best AI model") == 1, "Dedup must produce exactly one row"

    def test_existing_fixtures_unaffected_no_label(self):
        """Existing FULL_DO_HITS fixture (no outcome_label) must still render correctly."""
        from core.do_markets_renderer import render_markets_fragment
        html = render_markets_fragment(FULL_DO_HITS)
        assert "interest rates" in html.lower()
        assert "72%" in html
        assert " — " not in html, "No em-dash when no labels in fixture"


# ---------------------------------------------------------------------------
# M9 — Volume B-tier formatting (P2-2)
# ---------------------------------------------------------------------------

class TestM9VolumeBTier:
    """_fmt_vol must format volumes >= 1B as $X.XXB, not $XXXXX.XM."""

    def test_999m_stays_in_m_tier(self):
        """$999M boundary: 999_000_000 → '$999.0M'."""
        from core.do_markets_renderer import _fmt_vol
        assert _fmt_vol(999_000_000) == "$999.0M"

    def test_1b_formats_as_b_tier(self):
        """Exact 1B threshold: 1_000_000_000 → '$1.00B'."""
        from core.do_markets_renderer import _fmt_vol
        assert _fmt_vol(1_000_000_000) == "$1.00B"

    def test_3456m_formats_as_b_tier(self):
        """Real-world symptom: 3_456_700_000 → '$3.46B', not '$3456.7M'."""
        from core.do_markets_renderer import _fmt_vol
        assert _fmt_vol(3_456_700_000) == "$3.46B"

    def test_1218m_formats_as_b_tier(self):
        """Real-world symptom: 1_218_700_000 → '$1.22B', not '$1218.7M'."""
        from core.do_markets_renderer import _fmt_vol
        assert _fmt_vol(1_218_700_000) == "$1.22B"

    def test_b_tier_renders_in_fragment(self):
        """Fragment with a $3.46B volume must contain '$3.46B' in the HTML output."""
        from core.do_markets_renderer import render_markets_fragment
        data = {"hits": {"WL-1": [{
            "title": "Big market",
            "url": "https://example.com",
            "prob_now": 0.55,
            "delta_7d": 0.10,
            "volume_usd": 3_456_700_000,
        }]}}
        html = render_markets_fragment(data)
        assert "$3.46B" in html, f"Expected '$3.46B' in fragment, got: {html[:300]}"


# ---------------------------------------------------------------------------
# M10 — Null-baseline delta suppression (P2-1)
# ---------------------------------------------------------------------------

class TestM10NullBaselineDelta:
    """delta_7d must be None when prob_7d_ago is 0.0 (new market, zero baseline)."""

    def test_delta_null_when_prob_7d_zero(self):
        """prob_7d_ago=0.0 must produce delta_7d=None (not +Xpp equal to current prob)."""
        from core.models import Event, Market
        from core.scan import _query_topic
        from unittest.mock import MagicMock
        m = Market(
            market_id="mkt-rfk",
            outcome_label="Yes",
            url="https://polymarket.com/event/rfk",
            prob_now=0.49,
            prob_7d_ago=0.0,
        )
        event = Event(
            event_id="evt-rfk", event_title="RFK wins nomination",
            markets=[m], volume_usd=500_000, end_date="2026-12-31", tags=[],
        )
        adapter = MagicMock()
        adapter.public_search.return_value = [event]
        topic = {"topic_key": "WL-99", "topic_label": "RFK",
                 "keywords": "RFK wins nomination", "lang": ["en-AU"]}
        result = _query_topic(topic, adapter)
        assert result, "Should return markets"
        for m in result:
            assert m["delta_7d"] is None, (
                f"delta_7d must be None when prob_7d_ago=0.0 (new market), got {m['delta_7d']}"
            )

    def test_delta_populated_when_prob_7d_nonzero(self):
        """prob_7d_ago > 0.0 must still produce a real delta_7d."""
        from core.models import Event, Market
        from core.scan import _query_topic
        from unittest.mock import MagicMock
        m = Market(
            market_id="mkt-test",
            outcome_label="Yes",
            url="https://polymarket.com/event/test",
            prob_now=0.60,
            prob_7d_ago=0.50,
        )
        event = Event(
            event_id="evt-test", event_title="Test event nominal",
            markets=[m], volume_usd=50_000, end_date="2026-12-31", tags=[],
        )
        adapter = MagicMock()
        adapter.public_search.return_value = [event]
        topic = {"topic_key": "WL-1", "topic_label": "Test",
                 "keywords": "Test event nominal", "lang": ["en-AU"]}
        result = _query_topic(topic, adapter)
        assert result
        assert result[0]["delta_7d"] is not None
        assert abs(result[0]["delta_7d"] - 0.10) < 0.001

    def test_build_pool_null_delta_when_prob_7d_zero(self):
        """_build_pool: prob_7d_ago=0.0 on bulk event must produce delta_7d=None."""
        from core.models import Event, Market
        from core.scan import _build_pool
        from unittest.mock import MagicMock
        m = Market(
            market_id="mkt-bulk",
            outcome_label="Yes",
            url="https://polymarket.com/event/bulk",
            prob_now=0.49,
            prob_7d_ago=0.0,
        )
        event = Event(
            event_id="evt-bulk", event_title="New market event",
            markets=[m], volume_usd=500_000, end_date="2026-12-31", tags=[],
        )
        adapter = MagicMock()
        adapter.top_by_volume.return_value = [event]
        adapter.public_search.return_value = []
        pool = _build_pool(adapter, hits_urls=set())
        assert pool, "Should return candidates"
        assert pool[0]["delta_7d"] is None, (
            f"delta_7d must be None when prob_7d_ago=0.0, got {pool[0]['delta_7d']}"
        )
