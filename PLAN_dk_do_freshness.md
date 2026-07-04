# PLAN — DK/DO Freshness & Why-It-Moved

**Goal:** NEW-badge diff layer + Breaking relevance gate (approved proposal #1) and related-headline matcher + prob sparkline (approved proposal #2).
**Spec:** `docs/superpowers/specs/2026-07-04-dk-do-freshness-design.md`
**Architecture:** Python carries `history[]` forward inside do_hits.json (no DB); GAS keeps `dk_seen.json` in the exchange folder for URL diffing; all matching rule-based (no AI).

## Tasks & acceptance criteria

| # | Task | Files | Acceptance |
|---|---|---|---|
| 1 | `core/market_history.py` (load_prev_history, attach_history) — TDD | core/market_history.py, tests/test_market_history.py | missing/corrupt prev → {}; append, cap 7, same-day replace; tests PASS |
| 2 | Wire into `scan()` for hits + pool | core/scan.py | integration test: prev file on disk → items carry history; full suite green |
| 3 | GAS seen-diff: DK_loadSeen_/DK_writeSeen_, NEW badges (articles/breaking/markets), KPI new-counts | gas/01_dear_keyperson.js | shim tests: first-run suppression, badge on unseen URL only, KPI "N new" |
| 4 | Breaking gate: prompt rule + low-severity compact render | claude/dk_synthesis_prompt.md, gas/01_dear_keyperson.js | prompt lints (no "wire services" why); low severity renders as one-liner |
| 5 | Related-headline matcher on market cards | gas/01_dear_keyperson.js | shim tests: RBA market ↔ RBA headline match; unrelated → no line |
| 6 | Sparkline SVG from history (≥2 points) | gas/01_dear_keyperson.js | shim test: svg present with history, absent without |
| 7 | Verify: full pytest, shim suite, Playwright 390px; manual scan → Drive do_hits has history; deploy after confirmation | — | 全緑 + 目視 |

## Test plan
Python: tests/test_market_history.py (unit + scan integration). GAS: new DK_test_freshness_* registered in DK_runTests, run via Node shim; Playwright interaction/visual pass.

## Rollback
git revert per repo; delete dk_seen.json to reset diff state; `history` ignored by old renderer; GAS redeploy via deploy-dk.ps1 fixed ID.
