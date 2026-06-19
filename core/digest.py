"""core/digest.py — Portfolio digest renderer.

Renders a brand-styled HTML summary of do_hits.json for CI artifact and offline review.
Uses no real names or private Notion IDs — safe for public repos.
"""
from __future__ import annotations

import html as _html
from pathlib import Path

# Brand palette (matches DK / DP colour scheme)
_CHARCOAL   = "#264653"
_VERDIGRIS  = "#2a9d8f"
_JASMINE    = "#e9c46a"
_SANDY      = "#f4a261"
_BURNT      = "#e76f51"


def render_digest(do_hits: dict) -> str:
    """Return a brand-styled HTML digest from a do_hits dict."""
    meta = do_hits.get("meta", {})
    hits = do_hits.get("hits", {})
    generated_at = meta.get("generated_at", "—")
    status = meta.get("status", "unknown")
    topics_queried = meta.get("topics_queried", 0)
    topics_with_hits = meta.get("topics_with_hits", 0)

    rows_html = ""
    total_markets = 0
    for topic_key, markets in hits.items():
        for m in markets:
            total_markets += 1
            title = _esc(m.get("title", ""))
            url = _esc(m.get("url", "#"))
            prob = m.get("prob_now")
            delta = m.get("delta_7d")
            vol = m.get("volume_usd")

            prob_str = f"{prob * 100:.0f}%" if prob is not None else "—"
            delta_str = _delta_str(delta)
            delta_colour = _delta_colour(delta)
            vol_str = _vol_str(vol)
            key_str = _esc(topic_key)

            rows_html += f"""
        <tr>
          <td style="padding:8px 12px;font-size:12px;color:{_VERDIGRIS};">{key_str}</td>
          <td style="padding:8px 12px;">
            <a href="{url}" style="color:{_CHARCOAL};text-decoration:none;">{title}</a>
          </td>
          <td style="padding:8px 12px;text-align:center;font-weight:bold;">{prob_str}</td>
          <td style="padding:8px 12px;text-align:center;color:{delta_colour};">{delta_str}</td>
          <td style="padding:8px 12px;text-align:right;font-size:12px;color:#888;">{vol_str}</td>
        </tr>"""

    status_colour = _VERDIGRIS if status == "ok" else _SANDY
    badge = f'<span style="background:{status_colour};color:#fff;border-radius:4px;padding:2px 8px;font-size:12px;">{_esc(status.upper())}</span>'

    no_hits_msg = ""
    if total_markets == 0:
        no_hits_msg = f'<p style="color:{_SANDY};text-align:center;padding:24px;">No Polymarket hits found for current topics.</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Dear Oracle — Portfolio Digest</title>
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #f8f9fa;
      color: {_CHARCOAL};
    }}
    .header {{
      background: {_CHARCOAL};
      color: #fff;
      padding: 24px 32px;
    }}
    .header h1 {{
      margin: 0 0 4px;
      font-size: 22px;
      letter-spacing: -0.3px;
    }}
    .header .sub {{
      font-size: 13px;
      opacity: 0.75;
    }}
    .card {{
      background: #fff;
      border-radius: 8px;
      box-shadow: 0 1px 4px rgba(0,0,0,.08);
      margin: 24px 32px;
      overflow: hidden;
    }}
    .card-header {{
      background: {_VERDIGRIS};
      color: #fff;
      padding: 12px 20px;
      font-size: 14px;
      font-weight: 600;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    tr:nth-child(even) {{ background: #f9f9f9; }}
    th {{
      background: {_CHARCOAL};
      color: #fff;
      padding: 10px 12px;
      font-size: 12px;
      font-weight: 600;
      text-align: left;
    }}
    .meta-bar {{
      display: flex;
      gap: 24px;
      padding: 16px 32px;
      font-size: 13px;
      color: #666;
    }}
    .meta-bar strong {{ color: {_CHARCOAL}; }}
    .accent {{ color: {_BURNT}; font-weight: bold; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>&#x1F52E; Dear Oracle — Portfolio Digest</h1>
    <div class="sub">Generated {_esc(generated_at)} &nbsp;|&nbsp; Status: {badge}</div>
  </div>

  <div class="meta-bar">
    <span>Topics queried: <strong>{topics_queried}</strong></span>
    <span>Topics with hits: <strong class="accent">{topics_with_hits}</strong></span>
    <span>Markets shown: <strong>{total_markets}</strong></span>
  </div>

  <div class="card">
    <div class="card-header">Polymarket Signals</div>
    {no_hits_msg}
    {'<table><thead><tr><th>Topic</th><th>Market</th><th>Prob</th><th>7d &Delta;</th><th>Volume</th></tr></thead><tbody>' + rows_html + '</tbody></table>' if total_markets > 0 else ''}
  </div>

  <div style="text-align:center;padding:16px;font-size:11px;color:#bbb;">
    Dear Oracle &mdash; sample data only &mdash; no real names or private IDs
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(s: str) -> str:
    return _html.escape(str(s))


def _delta_str(delta: float | None) -> str:
    if delta is None:
        return "—"
    pct = delta * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}pp"


def _delta_colour(delta: float | None) -> str:
    if delta is None:
        return "#888"
    return _VERDIGRIS if delta >= 0 else _BURNT


def _vol_str(vol: float | None) -> str:
    if vol is None:
        return "—"
    if vol >= 1_000_000:
        return f"${vol/1_000_000:.1f}M"
    if vol >= 1_000:
        return f"${vol/1_000:.0f}K"
    return f"${vol:.0f}"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(do_hits_path: Path | None = None, out_path: Path | None = None) -> None:
    """Render digest from do_hits.json (or sample) and write to out_path."""
    import json
    from core.scan import scan, load_watchlist
    from core.adapter_polymarket import PolymarketAdapter

    if do_hits_path and do_hits_path.exists():
        data = json.loads(do_hits_path.read_text(encoding="utf-8"))
    else:
        data = scan(watchlist=load_watchlist(), adapter=PolymarketAdapter())

    html = render_digest(data)
    target = out_path or (Path(__file__).parent.parent / "docs" / "digest.sample.html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    print(f"Digest written to {target}")
