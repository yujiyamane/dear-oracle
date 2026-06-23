"""core/do_markets_renderer.py — Deterministic HTML fragment renderer for market data.

Reads do_hits.json structure → produces a self-contained <section> fragment
suitable for injection at the bottom of the DK morning page.

Rules:
- No AI. Deterministic only.
- Inline styles throughout (no external CSS dependencies).
- Source-agnostic: never names the data source.
- Empty hits or all-resolved hits → returns '' so DK can omit the section cleanly.
- Never raises on malformed input.

Curation (applied before rendering):
1. Drop resolved: prob_now <= RESOLVED_THRESHOLD or >= (1 - RESOLVED_THRESHOLD)
2. Drop below min_volume_usd (default 0 = no filter)
3. Deduplicate by normalised title within each WL key → keep highest prob_now
4. Sort all survivors by |delta_7d| descending (None treated as 0)
5. Cap at max_markets rows
"""
from __future__ import annotations

import html as _html
import os
from pathlib import Path

_CHARCOAL = "#264653"
_VERDIGRIS = "#2A9D8F"
_JASMINE = "#E9C46A"
_SANDY = "#F4A261"
_BURNT = "#E76F51"
_UP_GREEN = "#2D8659"
_DN_RED = "#C0392B"
_MUTED = "#5B707B"
_LIGHT_BG = "#F5F7FA"
_BORDER = "#E2EAEC"

RESOLVED_THRESHOLD: float = 0.01
MAX_MARKETS: int = 5
MIN_VOLUME_USD: float = 0.0


def render_markets_fragment(
    do_hits: dict | None,
    *,
    max_markets: int = MAX_MARKETS,
    min_volume_usd: float = MIN_VOLUME_USD,
    resolved_threshold: float = RESOLVED_THRESHOLD,
) -> str:
    """Return a curated, self-contained <section> HTML fragment, or '' when nothing survives."""
    if not do_hits or not isinstance(do_hits, dict):
        return ""
    hits = do_hits.get("hits") or {}
    if not isinstance(hits, dict) or not hits:
        return ""

    curated = _curate(hits, max_markets=max_markets, min_volume_usd=min_volume_usd,
                      resolved_threshold=resolved_threshold)
    if not curated:
        return ""

    rows_html = "".join(_render_row(m) for m in curated)

    return f"""<section style="margin-top:32px;border-top:1px solid {_BORDER};padding-top:24px">
  <div style="font-family:'SF Mono',ui-monospace,Consolas,monospace;font-size:11px;font-weight:700;letter-spacing:.18em;color:{_BURNT};text-transform:uppercase;margin-bottom:14px">Market Signals</div>
  <div style="border:1px solid {_BORDER};border-radius:14px;overflow:hidden">
    <div style="display:grid;grid-template-columns:1fr auto auto auto;background:{_LIGHT_BG};border-bottom:1px solid {_BORDER};padding:8px 16px;font-family:'SF Mono',ui-monospace,Consolas,monospace;font-size:10px;font-weight:700;letter-spacing:.1em;color:{_MUTED};text-transform:uppercase">
      <span>Event</span><span style="text-align:right;padding-left:16px">Odds</span><span style="text-align:right;padding-left:16px">7d</span><span style="text-align:right;padding-left:16px">Vol</span>
    </div>
    {rows_html}
  </div>
</section>"""


def _curate(
    hits: dict,
    *,
    max_markets: int,
    min_volume_usd: float,
    resolved_threshold: float,
) -> list[dict]:
    """Return a sorted, deduped, capped list of market dicts ready for rendering."""
    candidates: list[dict] = []

    for markets in hits.values():
        if not isinstance(markets, list):
            continue
        # Dedup within this WL key by normalised title → keep highest prob_now
        best: dict[str, dict] = {}
        for m in markets:
            if not isinstance(m, dict):
                continue
            prob = m.get("prob_now")
            if prob is None:
                continue
            if prob <= resolved_threshold or prob >= (1.0 - resolved_threshold):
                continue
            vol = m.get("volume_usd") or 0.0
            if min_volume_usd > 0 and vol < min_volume_usd:
                continue
            key = (m.get("title") or "").strip().lower()
            existing = best.get(key)
            if existing is None or prob > (existing.get("prob_now") or 0.0):
                best[key] = m
        candidates.extend(best.values())

    candidates.sort(key=lambda m: abs(m.get("delta_7d") or 0.0), reverse=True)
    return candidates[:max_markets]


def _render_row(m: dict) -> str:
    raw_title = m.get("title") or ""
    label = m.get("outcome_label") or ""
    title = _esc(f"{raw_title} — {label}" if label else raw_title)
    url = _safe_href(m.get("url") or "")
    prob = m.get("prob_now")
    delta = m.get("delta_7d")
    vol = m.get("volume_usd")

    prob_str = f"{round(prob * 100)}%" if prob is not None else "—"
    delta_str, delta_colour = _fmt_delta(delta)
    vol_str = _fmt_vol(vol)

    title_html = (
        f'<a href="{url}" target="_blank" rel="noopener" style="color:{_CHARCOAL};text-decoration:underline;text-decoration-color:{_BORDER};text-underline-offset:3px;font-size:14px;font-weight:600">{title}</a>'
        if url else
        f'<span style="color:{_CHARCOAL};font-size:14px;font-weight:600">{title}</span>'
    )

    return f"""    <div style="display:grid;grid-template-columns:1fr auto auto auto;padding:10px 16px;border-bottom:1px solid {_BORDER};align-items:center">
      <div>{title_html}</div>
      <div style="text-align:right;padding-left:16px;font-family:'SF Mono',ui-monospace,Consolas,monospace;font-size:13px;font-weight:700;color:{_CHARCOAL}">{prob_str}</div>
      <div style="text-align:right;padding-left:16px;font-family:'SF Mono',ui-monospace,Consolas,monospace;font-size:12px;color:{delta_colour}">{delta_str}</div>
      <div style="text-align:right;padding-left:16px;font-family:'SF Mono',ui-monospace,Consolas,monospace;font-size:11px;color:{_MUTED}">{vol_str}</div>
    </div>
"""


def write_markets_fragment(do_hits: dict | None, out_path: Path) -> None:
    """Write render_markets_fragment output to out_path atomically."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = render_markets_fragment(do_hits)
    tmp = out_path.with_suffix(".html.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, out_path)


def _fmt_delta(delta: float | None) -> tuple[str, str]:
    if delta is None:
        return "—", _MUTED
    pct = round(delta * 100)
    sign = "+" if pct >= 0 else ""
    colour = _UP_GREEN if pct >= 0 else _DN_RED
    return f"{sign}{pct}pp", colour


def _fmt_vol(vol: float | None) -> str:
    if vol is None:
        return "—"
    if vol >= 1_000_000:
        return f"${vol / 1_000_000:.1f}M"
    if vol >= 1_000:
        return f"${round(vol / 1_000)}K"
    return f"${round(vol)}"


def _esc(s: str) -> str:
    return _html.escape(str(s))


def _safe_href(url: str) -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return _esc(url)
    return ""
