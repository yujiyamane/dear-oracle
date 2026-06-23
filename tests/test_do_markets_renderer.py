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
