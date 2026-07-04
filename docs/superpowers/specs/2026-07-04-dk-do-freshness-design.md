# DK/DO Freshness & Why-It-Moved — Design Spec (2026-07-04)

## Goal

Two approved improvements on top of the brushup:

1. **差分レイヤー** — NEW badges for first-seen articles/markets, diff-aware KPI tiles, and a Breaking personal-relevance gate, so the daily read shrinks to what actually changed.
2. **Why-it-moved 強化** — market cards link to that day's related headlines (rule-based token match, no AI) and show a 7-day probability sparkline built from history carried forward inside do_hits.json.

Out of scope: Brier/accuracy footer (predictor resolve wiring is a separate project), email inline digest, dark mode.

## Architecture

```
dear-oracle (Python)                      dear-keyperson (GAS)
┌───────────────────────────┐             ┌─────────────────────────────────┐
│ scan(out_path)            │ do_hits.json│ render:                         │
│  reads PREVIOUS do_hits   │────────────►│  dk_seen.json (exchange folder) │
│  carries prob history     │             │   read prev → NEW badges        │
│  (append prob_now, cap 7) │             │   write today's URL set         │
└───────────────────────────┘             │  sparkline SVG from history[]   │
                                          │  related-headline matcher (JS)  │
        dk_synthesis_prompt.md            └─────────────────────────────────┘
         Breaking relevance gate
```

## Components

### 1. Probability history — dear-oracle `core/scan.py` + `core/market_history.py`

- New module `core/market_history.py`:
  - `load_prev_history(out_path) -> dict[url, list[float]]` — reads existing do_hits.json at `out_path` (both `hits` groups and `pool`), returns `{url: history}` where history is the item's previous `history` list (or `[prob_now]` if absent). Missing/corrupt file → `{}`.
  - `attach_history(items, prev, date_syd, prev_date) -> None` — for each item: `history = prev.get(url, [])`; append today's `prob_now` **only if `date_syd != prev_date`** (idempotent re-runs same day replace last point instead of appending); cap at last 7; set `item["history"]`.
- `scan()` calls `load_prev_history(out_path)` (and reads prev `meta.date_syd`) before building output, applies `attach_history` to all hits markets and pool items.
- Backward compatible: `history` is additive; old GAS ignores it.

### 2. NEW badges + diff KPI — GAS

- `dk_seen.json` in the exchange folder (`DK_CFG.drive.exchangeFolderId`): `{ "date": "YYYY-MM-DD", "urls": ["..."] }`.
- `DK_loadSeen_()` reads it (missing → `{date:'', urls:[]}`); `DK_writeSeen_(today, urls)` overwrites (dedupe by name like dk_output files).
- During Drive render: collect every article URL (breaking, topics, people_briefs, wl sections) + market URL; `isNew = seen.date && seen.urls.indexOf(url) === -1` (first run ever → no badges, since everything would be NEW noise).
- Render: `NEW` chip (`.new-badge`, teal, 9px mono uppercase) on article rows (`DK_renderItem_`), breaking cards, and market cards.
- KPI tiles: "Breaking 3 · 2 new", "People 10 · 4 new briefs" (people NEW = person has ≥1 new article OR person absent from yesterday), "Markets top mover · N new".
- After building HTML, write today's seen file. Guard: writing must not throw the render (try/catch, log).

### 3. Breaking relevance gate — `claude/dk_synthesis_prompt.md`

In the Breaking section add:
- `why` MUST connect the event to Yuji's watchlist interests or situation. "Reported by N wire services" is corroboration, not a why — put corroboration in `source`, never in `why`.
- If no genuine personal connection exists, set `severity: "low"` and omit `why`; renderer shows low-severity items as a compact one-line list (no card).
- GAS `DK_renderBreaking_`: render `severity === 'low'` items as single compact lines under the cards.

### 4. Related coverage on market cards — GAS

- `DK_relatedHeadline_(marketTitle, articleIndex)` — pure JS port of the relevance guard: tokenize (lowercase, non-alnum split), stopword list, acronym set {rba, ai, smsf, fed, fifa, eu, us, uk}; match if acronym overlap OR ≥2 generic tokens (len ≥4) shared. Returns first matching article {title, url} or null.
- `articleIndex` built once per render from output.topics[].articles + people_briefs[].articles (title+url, deduped).
- Market card (note variant only): appends `Related: <linked headline>` line when a match exists.

### 5. Sparkline — GAS

- Market card renders inline SVG (110×24) polyline from `m.history` when `history.length >= 2`; teal stroke, endpoint dot; y-scale min/max of history with 10% pad. Below the prob bar. `history.length < 2` → omit (no placeholder).

## Error handling

- All new GAS reads (seen file, history, related index) are try/catch-wrapped; failure degrades to current rendering, never blocks the edition.
- Python: corrupt previous do_hits.json → history starts fresh; scan must not fail.

## Test plan (TDD)

- Python: `tests/test_market_history.py` — load_prev missing/corrupt/ok; attach appends, caps at 7, same-day idempotence, url-miss starts fresh; scan integration (prev file on disk → pool items carry history).
- GAS (Node shim + registered in DK_runTests): seen-diff badge logic incl. first-run suppression; KPI new-counts; low-severity breaking compact line; related-headline matcher positive/negative; sparkline presence/absence.
- Playwright visual pass at 390px.

## Rollout / rollback

- Ship Python first (additive `history`), GAS second via `deploy-dk.ps1` (confirm before push — HEAD feeds the 05:30 trigger).
- Rollback: git revert; delete `dk_seen.json` to reset diff state; `history` field ignored by old renderer.
