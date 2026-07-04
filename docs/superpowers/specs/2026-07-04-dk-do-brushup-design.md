# DK/DO Brush-up — Design Spec (2026-07-04)

## Goal

Dear KeyPerson daily edition is hard to use and hard to read. Redesign to a dashboard-style layout, eliminate hollow people briefs, turn DO Market Signals from a bare bullet list into annotated cards, and retire the near-empty DO letters.

User-confirmed requirements:

1. **People briefs**: every person gets a mandatory one-line hook, even redirect-only people (Harmeet, Marcus, シューさん, ジュンさん, ヒロキ, Jerry Corpus).
2. **DO Market Signals**: each market gets a one-line note (why it moved / what it means for Yuji); interest areas (RBA, property, AI, AU-relevant politics) pinned first, then by |delta|.
3. **Layout**: dashboard type — KPI tiles up top, section nav, details below; mobile-first readability.
4. **DO letters**: deprecated; DO's value is consolidated into DK's Market Signals section.

## Architecture (Approach A — approved)

No infrastructure change. GAS keeps rendering DK to Drive HTML; dear-oracle (Python) keeps producing `do_hits.json`; the Dawn Patrol email link flow is untouched.

```
dear-oracle (Python)                     dear-keyperson (GAS)
┌──────────────────────┐   do_hits.json  ┌──────────────────────────┐
│ core/scan.py         │ ──────────────► │ DK_renderHtmlDrive_      │
│  + note (rule-based) │  (Drive)        │  + dashboard header      │
│  + relevance tag     │                 │  + people cards          │
│ letters: REMOVED     │                 │ DK_renderDoMarketsSection_│
└──────────────────────┘                 │  + annotated cards       │
                                         └──────────────────────────┘
                        claude/dk_synthesis_prompt.md (Phase 2b)
                         + mandatory one-line hook per person
```

## Components

### 1. Dashboard header — GAS `01_dear_keyperson.js`

- Replace header/keyrow with a KPI tile row: 2×2 grid under 560px, 4 columns on desktop.
  - Tile 1: Breaking — count + highest severity (e.g. "3 · Medium").
  - Tile 2: People — count of people with fresh briefs.
  - Tile 3: Top mover — market outcome label + delta (e.g. "RFK Jr. +47pp").
  - Tile 4: Volume — N stories · M briefs · edition no.
- Each tile is an anchor link to its section (`#breaking`, `#people`, `#tree`, `#do-markets`).
- Sticky section nav bar (Breaking / People / Topics / Markets) below the tiles.
- Legend ("▲ up = in your favour" etc.) moves to the footer.
- Existing view toggle (By topic / By people) and Collapse-all button retained, restyled into the nav bar.

### 2. People briefs — `claude/dk_synthesis_prompt.md` (Phase 2b) + GAS

- Prompt change: Phase 2b MUST output `one_liner` for every person. For redirect-only people, synthesize from the topics they are mapped to ("今週この人に効く話題: RBA holds + Townsville listings tightening").
- Render change (`DK_renderPeopleBranch_`): card shows name + role chip + one-liner always visible; `So what` / `Then what` / sources inside the existing `details` collapse; `→ See 🌐 topic` redirects become small topic chips on one row, never the card body.
- Backward compatible: if `one_liner` is absent (old payloads), fall back to current rendering.

### 3. DO Market Signals — dear-oracle Python + GAS

- `core/scan.py` (pool build): add to each pool item
  - `relevance`: one of `rba | property | ai | au_politics | none`, from a static keyword map against title/WL topic id.
  - `note`: one-line template output, rule-based (no AI — ecosystem-first): direction phrase from `delta_7d` magnitude bands (firmed / jumped / collapsed etc.) + a relevance-specific implication clause from a static map; generic clause when `relevance = none`.
- Sort order in `do_hits.json` pool: relevance ≠ none first, then |delta_7d| desc.
- GAS `DK_renderDoMarketsSection_`: card per market — title, outcome, probability bar (CSS width %), delta arrow chip (green/red), note line, volume in muted mono. Falls back to current line rendering when `note` missing.

### 4. Letters deprecation — dear-oracle

- Stop writing `G:\My Drive\dear-oracle-letters\*` (remove the letter-writing code path from the daily pipeline; delete dead code rather than flag it off).
- Remove `drive_letters_path` from `config/delivery.json`.
- Existing letter files stay on Drive (no deletion).

## Error handling

- GAS renderers are null-safe: missing `note`/`relevance`/`one_liner` → current-style fallback, never a blank section.
- do_hits.json remains backward/forward compatible during rollout (Python can ship first; GAS second).

## Test plan (TDD)

- Python: unit tests first for `relevance` mapping, `note` template bands, pool sort order, and letters-path removal (pipeline no longer references it). Run existing `tests/` suite clean.
- GAS: extend `99_test.js` with render smoke tests (tiles present, people card contains one-liner, DO card contains note; fallback paths with legacy payloads).
- Visual: render sample HTML, inspect at 390px width.

## Rollout / rollback

- Ship order: dear-oracle first (additive fields), then GAS via `.\gas\deploy-dk.ps1` (fixed deployment ID — never bare `clasp deploy`).
- Rollback: redeploy previous GAS version to the same deployment ID; do_hits.json extra fields are ignored by old renderer.

## Out of scope

- Prediction/Brier features, letter redesign (letters are retired), Dawn Patrol email itself, Notion surfaces.
