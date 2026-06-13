# Dear Oracle — PLAN.md (v1.0)

> The build plan. Reads against PRFAQ.md (the why) and INTERFACES.md (the contracts).
> Methodology: PRFAQ-first Working Backwards -> this PLAN -> sub-agent re-review -> TDD build (一気通貫), frontend before backend, tests first.
> Every sprint lists scope, the TDD acceptance test, and the done-gate. No sprint starts before the prior gate is green.

---

## Global build rules (inherited standing rules)

- **TDD always**: write the failing test first, then the code. The deterministic core is the bulk of the test surface.
- **Ecosystem-first**: deterministic code over AI calls; minimise tokens; AI only where language is the product.
- **Determinism / AI split** is law: odds maths, resolution, deltas, Brier, transitions = pure code; why-research, scenario, letter prose = AI.
- **Zero Claude calls in CI**: the entire pytest suite runs against in-memory SQLite + canned fixtures (`oracle_dryrun`) + static prompt lint. Golden-output (live `claude -p`) is a manual pre-ship gate only.
- **English** for all code/docs. **PowerShell** for terminal examples. **MIT** licence.
- **Palette** for ALL HTML/SVG surfaces is defined once in `docs/brand.md` (the single source of truth — letter, doGet, standings, deck all read from it; never hardcode colour elsewhere). Core: Charcoal Blue #264653, Verdigris #2A9D8F, Jasmine #E9C46A, Sandy Brown #F4A261, Burnt Peach #E76F51. Semantic (separate): up #2D8659, down #C0392B, neutral #8FA3AC.

---

## Sprint 0 — placement, contracts, spike

**Scope**
1. **Place `PRFAQ.md` + `INTERFACES.md` in the repo root first** (reviews and sub-agents assume both are on disk — this was a repeated false-negative in review).
2. Scaffold the repo tree (PRFAQ Q16) with empty modules + `LICENSE` (MIT) + `.gitignore` (INTERFACES §10) + example configs.
3. Finalise the dataclasses in `core/models.py`: `Event, Market, Tag, PricePoint, Resolution` + field nullability.
4. **Spike B** (the only live spike): a throwaway script `tests/spikes/spike_b.py` that, against 2–3 real multi-outcome Polymarket events:
   - confirms CLOB exposes `closed` + final outcome prices,
   - confirms all constituent markets of one event flip `resolved` together (basket timing),
   - confirms `/prices-history` returns data keyless.

**TDD acceptance**
- `pytest tests/test_models.py` green (dataclass construction, nullability, JSON round-trip of `market_signals[]` against the INTERFACES §2 example).
- Spike B writes a verdict file `docs/spike-b-verdict.md` (PASS/FAIL on resolution; PASS on prices-history).

**Gate**: repo scaffolds, models tested, Spike B verdict recorded. If Spike B fails on resolution, record the Sprint 5 fallback decision now.

---

## Sprint 1 — oracle-predictor (the first thing a stranger runs)

**Scope** (interactive skill; zero infra; works cold)
- `core/adapter_polymarket.py`: `search`, `events_by_tag`, `markets_for_event`, `tags` against Gamma. Timeout + single retry + graceful empty.
- `core/resolve.py`: `resolve(tags) -> events` and `aggregate(event) -> outcomes[]` (sorts outcomes by prob desc, computes the "Field" remainder for multi-outcome).
- `core/predictor.py`: question -> (cold) volume-ranked events / (known-user, if interests.json present) interest-tag-filtered then volume-ranked. Multi-match = highest-volume main answer + `Also pricing:` line. Zero-result = "closest questions" path.
- `skills/oracle-predictor/SKILL.md`: agent-agnostic; calls `core/predictor.py` via Bash; renders the ranked-% block; pre-loads the rot-proof deck from `questions.example.json` (tag/query -> live top-volume event at load time).

**TDD acceptance** (all against mocked Gamma JSON fixtures — no live calls)
- `aggregate` produces correctly sorted `outcomes[]` with a Field remainder summing to 1.00 (±0.01).
- Cold mode ranks by volume; known-user mode filters by interest tag first (fixture with interests.json present vs absent).
- Multi-match fixture ("next election" -> 3 events) returns the top-volume event as main + exactly the other 2 in `Also pricing`.
- Zero-result fixture returns 3 nearest questions, never an empty answer.
- Deck entry with a resolved event ID re-resolves to a live event (rot-proof).

**Gate**: `oracle "Who will win the 2026 World Cup?"` returns a ranked block on a fresh clone with **no interests.json present**. Pillar 1 is independently complete.

---

## Sprint 2 — oracle-onboard (First letter + P.S.)

**Scope** (interactive skill, multi-turn — never `claude -p`)
- AI tag-mapping step: free-text interest -> candidate `{slug, tag_id}` -> show live coverage counts -> user confirms.
- Broad-interest drill-down when >50 candidates, with a sensible default (press-enter path).
- Writes `interests.json` atomically (tmp -> fsync -> rename) with `schema_version`, `resolved_tags`, `keyword_fallback`, `status`.
- P.S. mode: detect a valid existing file by reading `schema_version` from contents; support "add / drop / show". Corrupt file -> back up + ask, never silent restart.
- Dormant registration for zero-coverage interests.

**TDD acceptance**
- Mapping fixture: "AI" -> candidate tags incl. `artificial-intelligence`; confirmation writes both `slug` and `tag_id`.
- Atomic write: a simulated crash mid-write leaves the prior file intact (tmp present, real untouched).
- Mode detection reads contents not existence: an empty/corrupt file triggers the back-up-and-ask branch, not First letter.
- P.S. "drop surfing" removes the interest; "add F1" runs coverage check and appends.
- Zero-coverage interest is written `status: dormant` with empty `resolved_tags`.

**Gate**: a full First-letter run produces a valid `interests.json` that Sprint 3's collector can consume; a P.S. edits it correctly.

---

## Sprint 3 — Layer 1 collector (pure code, the data spine)

**Scope** (zero AI)
- `data/schema.sql` (INTERFACES §6) incl. `PRAGMA journal_mode=WAL`, `run_log`.
- `core/collector.py`: for each interest, resolve `resolved_tags` (tag-first) with keyword fallback and the degradation->dormant path; append snapshots; apply the `end_date >= now+30d` guard; cap `max_markets`.
- Delta computation in SQL (24h/7d) over `idx_snap_market`; null when history short.
- `threshold_exceeded` + `threshold_triggered_by` (larger |delta|).
- Coverage-transition detection: diff today's vs yesterday's interest statuses -> `coverage_transitions[]`.
- Standings build: assemble `standings[]` for EVERY watched event (reuse `aggregate()`; top-3 for multi-outcome, primary for binary; per-outcome `prob_now` + `delta_24h_pp`).
- Dormant re-scan piggyback: trigger when `days_since_last_successful_dormant_scan >= 7` (from `run_log`); demote/promote interests.
- Backfill missed days from CLOB `/prices-history`, mark `backfilled=1`.
- Export the day's `market_signals[]` JSON (INTERFACES §2) to `data/exports/<date>.signals.json`.
- Day-1 confirmation letter content (deterministic).

**TDD acceptance** (in-memory SQLite + mocked adapter)
- Two snapshots 24h apart yield the correct `delta_24h_pp`; 7d-absent yields null and `threshold_exceeded` judged on 24h alone.
- `end_date < now+30d` market is excluded.
- Tag returning empty -> keyword fallback -> empty -> interest auto-demoted to dormant; emits an active->dormant transition.
- A previously dormant interest gaining coverage emits a dormant->active transition.
- `days_since >= 7` triggers a dormant scan; `< 7` does not.
- Exported JSON validates against the INTERFACES §2 shape (nested outcomes, pp deltas, nullability, transitions).
- Backfilled rows carry `backfilled=1`.

**Gate**: a simulated multi-day run produces a correct `market_signals[]` export and correct transitions, entirely in code, all green.

---

## Sprint 4 — Layer 2 AI + Layer 3 delivery

**Scope**
- `prompts/letter.md` (+ composed `why.md`, `scenario.md`): conservative-voice block prefix; consume the signals export; cap top-3 movers by |delta|; render the `standings[]` Where-things-stand snapshot (deterministic data, colours from docs/brand.md); 2-stage scenario; emit a single JSON envelope `{"html","plaintext"}` (raw JSON, no fences). Web search only in the why-section, with the skip-if-no-credible-source rule.
- Python pipeline wrapper: preflight `claude -p "ping"`; run the real call; `json.loads` split; on any failure -> deterministic quiet-seas plaintext + `run_log('letter','fallback',...)`.
- `oracle_dryrun()`: bypass AI, inject canned envelope fixtures, run Layer 1->3, assert structure.
- Delivery — gas adapter: write HTML to the Drive-for-Desktop synced folder; `doGet?date=` read-only renderer + `?list=1`; MailApp digest (first 3 plaintext lines + link); deploy "Only me".
- Delivery — smtp adapter: inline full HTML (server-less), inline CSS only.
- Dead-man's switch: a check at delivery+30min that a letter exists for today; else ping the owner with the manual re-auth instruction.
- Letter HTML uses the standard palette + semantic signal colours.

**TDD acceptance** (zero Claude calls)
- **Prompt lint (static, every commit)**: each `prompts/*.md` contains the conservative-voice block verbatim and contains no prohibited tokens `/buy|sell|invest|bet|position/i`.
- **dryRun E2E**: canned envelope (1 mover) -> HTML+plaintext produced, digest = first 3 plaintext lines, doGet serves the stored HTML (mock Drive read).
- **Fallback**: a canned "AI error" / malformed-JSON fixture routes to quiet-seas and writes `run_log('letter','fallback',...)`; delivery still emits.
- **All-dormant** fixture -> quiet-seas short form.
- **Envelope split**: a mocked `{"html","plaintext"}` parses; a fenced/garbled output triggers the fallback branch (proves D18 + D10 interplay).
- Dead-man's switch: "no letter for today" state triggers the owner ping (mocked).

**Manual pre-ship gate (not CI)**: golden-output — run the real `claude -p` against 3 fixtures, eyeball + regex for non-imperative voice, correct format, no financial-advice language.

**Gate**: a scheduled run produces and delivers a real letter; killing the AI step still delivers quiet-seas; the dead-man's switch fires on induced silence.

---

## Sprint 5 — oracle-log + Brier (GATED on Spike B)

**Pre-condition**: Spike B verdict read. If resolution FAILED, the MVP fallback (manual `/oracle-log resolve` or Brier deferred) is already decided (Sprint 0).

**Scope**
- `oracle-log` skill: "Log my prediction" records a row keyed by event (`my_probs` JSON mirroring outcomes); list/show.
- Resolution poll: when all basket markets resolve, fill `outcomes_json` + `resolved_at`; partial baskets stay pending.
- Multi-class Brier `(1/N) Σ (p_i - o_i)^2` for `brier_mine` and `brier_market`; binary = N=2 special case.
- Deterministic table display (no AI narrative on the log in v1).
- Contrarian note (commentary-labelled) added to `oracle-predictor` output.
- Usage-driven interest suggestion: repeated off-profile questions -> offer a P.S.

**TDD acceptance**
- Binary basket: `my_probs {Yes:0.7}`, outcome Yes -> `brier_mine = 0.09`.
- Multi-outcome basket (Spain/England/Field): Spain wins -> correct multi-class Brier; market vs mine both computed.
- Partial basket (one market unresolved) stays `pending`, not scored.
- Brier table renders deterministically; no Claude call.

**Gate**: a resolved prediction shows a correct Brier vs the market; partial baskets never mis-score.

---

## Cross-sprint test inventory (what guarantees "green = $0")

| Layer | Test kind | Claude calls |
|---|---|---|
| models, resolve, aggregate, predictor | pytest + mocked Gamma fixtures | 0 |
| onboard write/mode/atomicity | pytest + temp files | 0 |
| collector deltas/guard/transitions/backfill/export | pytest + in-memory SQLite | 0 |
| pipeline split/fallback/digest/doGet | pytest + `oracle_dryrun` canned envelopes | 0 |
| prompt guardrail | static lint on `prompts/*.md` | 0 |
| Brier | pytest fixtures | 0 |
| voice quality | golden-output, **manual pre-ship only** | small set |

---

## Handoff order for local Claude Code (VS Code)

```powershell
# 1. place PRFAQ.md, INTERFACES.md, PLAN.md, prompts/*.md in the repo
mkdir C:\Users\Admin\Documents\Life\Repos\dear-oracle
cd C:\Users\Admin\Documents\Life\Repos\dear-oracle

# 2. one sprint at a time, tests first
claude "Read PRFAQ.md, INTERFACES.md, PLAN.md. Execute Sprint 0 exactly:
scaffold the repo tree, write LICENSE (MIT) and .gitignore per INTERFACES section 10,
define core/models.py dataclasses, and run Spike B writing docs/spike-b-verdict.md.
TDD: write tests/test_models.py first. Do not start Sprint 1."
```
Run each sprint as its own prompt; do not let one run cross a gate. After each: confirm the sprint's TDD acceptance is green before the next.
