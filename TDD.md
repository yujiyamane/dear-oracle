# Dear Oracle — TDD.md (test specification)

> Tests are written BEFORE code, per standing rule. This file is the authoritative test inventory.
> Hard guarantee: the entire suite runs with **zero Claude calls** — mocked Gamma fixtures, in-memory SQLite, canned `oracle_dryrun` envelopes, and static prompt lint. Live `claude -p` (golden-output) is a manual pre-ship step, never in CI.
> Maps 1:1 to PLAN.md sprints and INTERFACES.md contracts.

---

## Test layout

```
tests/
├── conftest.py            # fixtures: in-memory db, mocked adapter, canned envelopes
├── fixtures/
│   ├── gamma_worldcup.json        # multi-outcome event
│   ├── gamma_election_multi.json  # 3 events for one question
│   ├── gamma_zero.json            # no match
│   ├── signals_one_mover.json     # market_signals[] canned export
│   ├── signals_three_movers.json
│   ├── signals_all_dormant.json
│   ├── envelope_ok.json           # {"html","plaintext"}
│   └── envelope_malformed.txt     # fenced/garbled -> fallback
├── spikes/spike_b.py
├── test_models.py         # Sprint 0
├── test_predictor.py      # Sprint 1
├── test_onboard.py        # Sprint 2
├── test_collector.py      # Sprint 3
├── test_pipeline.py       # Sprint 4 (dryRun)
├── test_prompt_lint.py    # Sprint 4 (static, every commit)
└── test_brier.py          # Sprint 5
```

`conftest.py` provides:
- `db()` -> `sqlite3.connect(":memory:")` with `schema.sql` applied (incl. `PRAGMA journal_mode=WAL`).
- `adapter()` -> a `MarketAdapter` stub reading `fixtures/gamma_*.json`, honouring timeout/empty/retry contracts without network.
- `envelope(name)` -> loads a canned `{"html","plaintext"}` for dryRun.

---

## Sprint 0 — test_models.py

- `test_dataclass_construct`: `Event/Market/Tag/PricePoint/Resolution` build from fixture dicts.
- `test_nullability`: `prob_7d_ago=None` allowed; `delta_7d_pp` then None.
- `test_signals_roundtrip`: serialise a `market_signals[]` object and assert it equals the INTERFACES §2 example (nested `outcomes[]`, `pp` deltas, `coverage_transitions[]`, forward-compat: an unknown extra key is ignored on load).
- Spike B (`spikes/spike_b.py`, manual): asserts CLOB `closed` + final prices on 2–3 real events, basket markets resolve together, `/prices-history` returns keyless. Writes `docs/spike-b-verdict.md`.

## Sprint 1 — test_predictor.py (mocked Gamma only)

- `test_aggregate_sorted_field`: outcomes sorted desc; "Field" remainder so the basket sums to 1.00 ±0.01.
- `test_cold_mode_volume_rank`: no interests.json present -> pure volume order.
- `test_known_user_tag_filter`: interests.json with `australian-politics` present -> AU event ranks above higher-volume US event.
- `test_multi_match`: `gamma_election_multi.json` -> top-volume event is main answer; exactly the other two appear in `Also pricing`.
- `test_zero_result`: `gamma_zero.json` -> returns 3 nearest questions, never empty.
- `test_deck_rotproof`: a deck entry whose stored event ID has resolved re-resolves to a current live event (entry stores tag/query, not frozen ID).

## Sprint 2 — test_onboard.py (temp files)

- `test_tag_mapping`: "AI" -> candidates include `{"slug":"artificial-intelligence","tag_id":...}`; confirmation persists both fields to `resolved_tags`.
- `test_atomic_write`: simulate a crash between tmp-write and rename -> prior `interests.json` intact, `.tmp` present, no corruption.
- `test_mode_by_contents`: an empty/corrupt file does NOT route to First letter -> triggers back-up-and-ask branch (mode read from `schema_version` in contents).
- `test_ps_add_drop`: "P.S. drop surfing" removes; "P.S. add F1" runs coverage check + appends.
- `test_zero_coverage_dormant`: an interest with no tag match is written `status:"dormant"`, empty `resolved_tags`, with `keyword_fallback` set.

## Sprint 3 — test_collector.py (in-memory SQLite + mocked adapter) — the spine

- `test_delta_24h`: two snapshots 24h apart -> correct `delta_24h_pp`.
- `test_delta_7d_null`: <7d history -> `delta_7d_pp` None; `threshold_exceeded` judged on 24h alone.
- `test_horizon_guard`: market with `end_date < now+30d` excluded.
- `test_max_markets_cap`: more than `max_markets` candidates -> capped, volume-sorted.
- `test_tag_degradation`: stored tag returns empty -> keyword fallback -> empty -> interest auto-demoted to dormant AND emits an active->dormant transition.
- `test_reactivation`: a dormant interest gaining coverage emits a dormant->active transition.
- `test_dormant_rescan_trigger`: `days_since_last_successful_dormant_scan>=7` (seeded in `run_log`) triggers a scan; `<7` does not. (Weekday-independent.)
- `test_export_schema`: the exported JSON validates against INTERFACES §2 (nested outcomes, pp deltas, nullability, transitions present).
- `test_standings_built`: from snapshots, `standings[]` includes EVERY watched event (moved or not); multi-outcome events carry top-3 `top_outcomes` with `is_binary:false`, binary events carry the single primary with `is_binary:true`; each `top_outcome` has `prob_now` + nullable `delta_24h_pp`; a dormant interest is absent from standings (rendered from the interest list instead). Reuses `aggregate()`.
- `test_backfill_flag`: backfilled rows carry `backfilled=1`.
- `test_threshold_triggered_by`: when both windows exceed, the larger `|delta|` window is named.

## Sprint 4 — test_pipeline.py (dryRun — ZERO Claude calls) + test_prompt_lint.py

**test_pipeline.py** (inject canned envelopes via `oracle_dryrun`):
- `test_dryrun_one_mover`: `signals_one_mover.json` (now including a `standings[]` array) + `envelope_ok.json` -> HTML+plaintext produced; digest = first 3 plaintext lines; mocked doGet serves the stored HTML.
- `test_fallback_on_malformed`: `envelope_malformed.txt` (fenced/garbled) -> routes to deterministic quiet-seas; `run_log('letter','fallback',...)` written; delivery still emits. (Proves D18 + D10 interplay.)
- `test_all_dormant_shortform`: `signals_all_dormant.json` -> quiet-seas short form, no fabricated movement.
- `test_digest_extraction`: digest is exactly the first 3 plaintext lines.
- `test_deadman_fires`: state "no letter file for today" -> owner ping invoked (mocked), carrying the manual re-auth instruction.
- `test_preflight_auth_log`: a simulated failing smoke test writes `run_log('auth','error',...)` and sends quiet-seas.

**test_prompt_lint.py** (static; runs every commit; reads `prompts/*.md`):
- `test_voice_block_verbatim`: each prompt file contains the conservative-voice block verbatim (byte-for-byte the canonical text).
- `test_no_prohibited_tokens`: no prompt file body contains `/buy|sell|invest|bet|position/i` outside the guardrail itself.

**Manual pre-ship only (NOT CI)** — golden-output: run real `claude -p` against `signals_one_mover/three_movers/all_dormant`; assert output is valid JSON envelope, non-imperative (regex `/buy|sell|invest|bet|position/i` absent in `html`+`plaintext`), correct structure. Run once when the prompt design is finalised and after any prompt edit.

## Sprint 5 — test_brier.py (GATED on Spike B)

- `test_brier_binary`: `my_probs {"Yes":0.7}`, outcome Yes -> `brier_mine == 0.09`.
- `test_brier_multiclass`: basket {Spain:0.30, England:0.20, Field:0.50}, Spain wins -> multi-class `(1/N)Σ(p_i-o_i)^2` correct; `brier_market` computed from market_probs the same way.
- `test_partial_basket_pending`: one constituent market unresolved -> row stays `resolved_at NULL`, not scored.
- `test_log_table_deterministic`: the Brier table renders with no Claude call.

## Sprint 5B item 2 — usage-driven interest suggestions (in test_predictor.py)

All four tests use `election_multi_adapter` (soccer interests = off-profile, au-politics interests = on-profile) and the `db` in-memory fixture (schema includes `query_log`).

- `test_off_profile_query_logged`: soccer interests + election query → one row in `query_log` with `off_profile=1`.
- `test_on_profile_query_not_logged`: au-politics interests + election query (AU election is on-profile) → zero rows in `query_log`.
- `test_suggestion_fires_at_threshold`: `_SUGGESTION_THRESHOLD` off-profile queries → `result.suggestion` is not None and contains the topic text.
- `test_suggestion_absent_below_threshold`: `_SUGGESTION_THRESHOLD - 1` off-profile queries → `result.suggestion is None`.

Storage: `query_log` table in `oracle.db` (`data/schema.sql`). Threshold: `_SUGGESTION_THRESHOLD = 3` (module constant in `core/predictor.py`). Off-profile = event's tags don't overlap any active interest tag_id (cold mode with no interests → never off-profile). `PredictorAnswer.suggestion: str | None` rendered by `_render_answer` when not None.

---

## Definition of done (per sprint)

A sprint is done when its named tests are green AND the prior sprints' suites still pass. The Sprint 4 prompt-lint runs on every commit from the moment `prompts/` exists. "Green = $0" must hold at all times: if any CI test needs a live Claude call, it is mis-designed — move it to the manual golden-output gate.
