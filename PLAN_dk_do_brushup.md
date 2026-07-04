# DK/DO Brush-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dashboard-style DK daily edition, mandatory one-line hook per person, annotated DO market cards, DO letters retired.

**Architecture:** dear-oracle (Python) gains a rule-based `note`/`relevance` annotator on the do_hits pool and drops the letter pipeline. dear-keyperson (GAS) gets a KPI-tile dashboard header, people cards that always show the brief, and DO market cards that render the new note. Ship Python first (additive JSON fields), GAS second.

**Tech Stack:** Python 3.11 + pytest (dear-oracle), Google Apps Script via clasp (dear-keyperson), Claude synthesis prompt (Phase 2b).

**Spec:** `docs/superpowers/specs/2026-07-04-dk-do-brushup-design.md`

## Global Constraints

- dear-oracle repo: commit to `master`; commit bodies follow git-session-handoff format (`git commit -F <utf-8 tmpfile>`, never inline `-m` for multi-line).
- dear-keyperson lives in the Life monorepo (`C:\Users\Admin\Documents\Life\dear-keyperson\`): commit to `main`.
- GAS deploy ONLY via `.\gas\deploy-dk.ps1 '<desc>'` — never bare `clasp deploy`. Deploy is a **production write: confirm with Yuji before running it**.
- do_hits.json stays backward compatible: GAS must render legacy payloads (no `note`/`relevance`) unchanged.
- No AI calls for market notes — rule-based templates only.
- Existing letter files in `G:\My Drive\dear-oracle-letters\` are NOT deleted.
- Do not use `data/do_hits.json` for verification — production target is `G:\My Drive\DawnPatrol\do_hits.json`.

---

## Part 1 — dear-oracle (Python), repo `C:\Users\Admin\Documents\Life\repos\dear-oracle`

### Task 1: Market note annotator module

**Files:**
- Create: `core/market_notes.py`
- Test: `tests/test_market_notes.py`

**Interfaces:**
- Produces: `classify_relevance(title: str) -> str` (one of `"rba" | "property" | "ai" | "au_politics" | "none"`); `build_note(item: dict) -> str`; `annotate_pool(pool: list[dict]) -> list[dict]` (returns NEW list, each item copied with added `note: str` and `relevance: str`, sorted relevance≠none first, then `abs(delta_7d or 0)` desc). Task 2 consumes `annotate_pool`.

- [ ] **Step 1: Write the failing tests**

```python
"""tests/test_market_notes.py"""
from core.market_notes import annotate_pool, build_note, classify_relevance


def test_classify_rba():
    assert classify_relevance("Reserve Bank of Australia Decision in August") == "rba"
    assert classify_relevance("RBA cash rate August") == "rba"


def test_classify_ai_word_boundary():
    assert classify_relevance("OpenAI releases new model") == "ai"
    assert classify_relevance("Will AI pass the bar exam") == "ai"
    assert classify_relevance("Ukraine ceasefire by September") == "none"


def test_classify_property_and_politics():
    assert classify_relevance("Sydney house prices to fall 10%") == "property"
    assert classify_relevance("Australian federal election winner") == "au_politics"


def test_classify_none():
    assert classify_relevance("World Cup Winner") == "none"


def test_build_note_bands():
    base = {"outcome_label": "France", "relevance": "none"}
    assert "steady" in build_note({**base, "delta_7d": None})
    assert "steady" in build_note({**base, "delta_7d": 0.004})
    assert "firmed" in build_note({**base, "delta_7d": 0.02})
    assert "slipped" in build_note({**base, "delta_7d": -0.02})
    assert "jumped" in build_note({**base, "delta_7d": 0.09})
    assert "surged" in build_note({**base, "delta_7d": 0.47})
    assert "collapsed" in build_note({**base, "delta_7d": -0.20})


def test_build_note_mentions_pp_and_implication():
    note = build_note({"outcome_label": "No change", "relevance": "rba", "delta_7d": 0.01})
    assert "+1pp" in note
    assert "mortgage" in note


def test_annotate_pool_adds_fields_and_sorts():
    pool = [
        {"title": "World Cup Winner", "outcome_label": "France", "delta_7d": 0.14},
        {"title": "RBA Decision in August", "outcome_label": "No change", "delta_7d": 0.01},
    ]
    out = annotate_pool(pool)
    assert out[0]["relevance"] == "rba"
    assert out[1]["relevance"] == "none"
    assert all("note" in m and "relevance" in m for m in out)
    assert pool[0].get("note") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_market_notes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.market_notes'`

- [ ] **Step 3: Implement `core/market_notes.py`**

```python
"""core/market_notes.py — rule-based note/relevance annotation for the do_hits pool.

classify_relevance(title) -> 'rba' | 'property' | 'ai' | 'au_politics' | 'none'
build_note(item)          -> one-line note: delta phrase + personal implication
annotate_pool(pool)       -> new list with note/relevance, relevance-first mover sort
"""
from __future__ import annotations

import re

_RULES: list[tuple[str, re.Pattern]] = [
    ("rba", re.compile(r"\brba\b|reserve bank|cash rate", re.I)),
    ("property", re.compile(r"propert|housing|house price|mortgage|real estate|smsf", re.I)),
    ("ai", re.compile(r"\bai\b|artificial intelligence|anthropic|openai|\bclaude\b|nvidia|\bagi\b", re.I)),
    ("au_politics", re.compile(r"\baustralia", re.I)),
]

_IMPLICATION = {
    "rba": "feeds straight into your mortgage and Townsville cashflow assumptions.",
    "property": "worth checking against your next-purchase timing.",
    "ai": "signal for your AI work and client conversations.",
    "au_politics": "policy backdrop for your AU investments.",
    "none": "no direct AU angle — context only.",
}

_BANDS = [(15, "surged", "collapsed"), (5, "jumped", "dropped"), (1, "firmed", "slipped")]


def classify_relevance(title: str) -> str:
    for tag, pattern in _RULES:
        if pattern.search(title or ""):
            return tag
    return "none"


def _delta_phrase(delta_7d: float | None, outcome: str) -> str:
    pp = round((delta_7d or 0.0) * 100)
    if delta_7d is None or abs(pp) < 1:
        return f"{outcome} steady over 7d"
    for floor, up, down in _BANDS:
        if abs(pp) >= floor:
            verb = up if pp > 0 else down
            return f"{outcome} {verb} {'+' if pp > 0 else ''}{pp}pp over 7d"
    return f"{outcome} steady over 7d"


def build_note(item: dict) -> str:
    outcome = (item.get("outcome_label") or "").strip() or "Lead outcome"
    relevance = item.get("relevance") or classify_relevance(item.get("title", ""))
    return f"{_delta_phrase(item.get('delta_7d'), outcome)} — {_IMPLICATION[relevance]}"


def annotate_pool(pool: list[dict]) -> list[dict]:
    out = []
    for item in pool:
        relevance = classify_relevance(item.get("title", ""))
        enriched = {**item, "relevance": relevance}
        enriched["note"] = build_note(enriched)
        out.append(enriched)
    out.sort(key=lambda m: (m["relevance"] == "none", -abs(m.get("delta_7d") or 0.0)))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_market_notes.py -v`
Expected: all PASS

- [ ] **Step 5: Commit (git-session-handoff format, `-F` tmpfile)**

Subject: `feat: market_notes — rule-based note/relevance for do_hits pool`

### Task 2: Wire annotator into scan pool

**Files:**
- Modify: `core/scan.py:276-339` (`_build_pool`)
- Test: `tests/test_market_notes.py` (add integration test)

**Interfaces:**
- Consumes: `annotate_pool` from Task 1.
- Produces: `do_hits.json` pool items now carry `note` and `relevance`; ordering is relevance-first then |delta|. GAS Task 7 consumes these fields.

- [ ] **Step 1: Write the failing test (append to `tests/test_market_notes.py`)**

```python
def test_build_pool_returns_annotated(monkeypatch):
    from core import scan as scan_mod

    class _M:
        url = "https://polymarket.com/event/rba-august/m1"
        prob_now = 0.88
        prob_7d_ago = 0.87
        outcome_label = "No change"

    class _E:
        event_title = "Reserve Bank of Australia Decision in August"
        volume_usd = 50_000.0
        markets = [_M()]

    class _Adapter:
        def top_by_volume(self, limit=50):
            return [_E()]

        def public_search(self, q, limit=5):
            return [_E()]

    pool = scan_mod._build_pool(_Adapter(), hits_urls=set())
    assert pool[0]["relevance"] == "rba"
    assert "note" in pool[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_market_notes.py::test_build_pool_returns_annotated -v`
Expected: FAIL — `KeyError: 'relevance'`

- [ ] **Step 3: Modify `_build_pool` tail in `core/scan.py`**

Add import at top of file: `from core.market_notes import annotate_pool`
Replace the last two lines of `_build_pool` (currently `enriched.sort(...)` / `return enriched[:limit]`) with:

```python
    enriched.sort(key=lambda x: abs(x.get("delta_7d") or 0.0), reverse=True)
    return annotate_pool(enriched[:limit])
```

- [ ] **Step 4: Run full suite**

Run: `python -m pytest tests/ -q`
Expected: all PASS (test_scan pool assertions are field-additive-safe; if any test asserts exact pool dict keys, extend the expected dict with `note`/`relevance`).

- [ ] **Step 5: Commit**

Subject: `feat: scan pool — annotate with note/relevance, relevance-first sort`

### Task 3: Retire the letter pipeline

**Files:**
- Modify: `core/run_daily.py` (drop `_drive_path`, `_copy_to_drive`, `run_letter` block, Drive sync block)
- Modify: `config/delivery.json` (remove `drive_letters_path`)
- Delete: `core/pipeline.py`, `core/oracle_dryrun.py`, `prompts/letter.md`, `tests/test_pipeline.py`
- Modify (conditional): `core/digest.py`, `tests/test_prompt_lint.py`, `tests/test_run_daily_imports.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (independent).
- Produces: `core.run_daily.main` no longer imports `core.pipeline`; `delivery.json` has no `drive_letters_path` key.

- [ ] **Step 1: Grep-guard the deletion set**

Run: `grep -rn "pipeline\|oracle_dryrun\|digest\|letter" --include=*.py core oracle.py scripts | grep -v "core/pipeline.py\|core/oracle_dryrun.py\|core/digest.py"`
Expected: only `core/run_daily.py` hits. If `core/digest.py` has no importer, include it and any of its tests in the deletion set; if something else imports a target, STOP and report instead of deleting.

- [ ] **Step 2: Update tests first**

In `tests/test_run_daily_imports.py`: remove/replace any assertion that `core.run_daily` imports `run_letter`; add:

```python
def test_run_daily_has_no_letter_pipeline():
    import inspect
    from core import run_daily
    src = inspect.getsource(run_daily)
    assert "run_letter" not in src
    assert "drive_letters_path" not in src
```

In `tests/test_prompt_lint.py`: drop cases targeting `prompts/letter.md` (keep `scenario.md` / `why.md`).
Delete `tests/test_pipeline.py`.

- [ ] **Step 3: Run to verify the new test fails**

Run: `python -m pytest tests/test_run_daily_imports.py -v`
Expected: FAIL — `run_letter` still present.

- [ ] **Step 4: Apply removals**

- `core/run_daily.py`: delete `_drive_path()`, `_copy_to_drive()`, the `from core.pipeline import run_letter` import, the "Layer 2: letter" block (lines ~140-150), and the "Drive sync" block (lines ~152-158). `main()` ends after the collect step.
- `config/delivery.json`: remove the `drive_letters_path` line.
- Delete files: `core/pipeline.py`, `core/oracle_dryrun.py`, `prompts/letter.md` (plus `core/digest.py` if Step 1 cleared it).

- [ ] **Step 5: Full suite + smoke**

Run: `python -m pytest tests/ -q` → all PASS.
Smoke: `python -c "from core import run_daily; print('import ok')"` → `import ok`.

- [ ] **Step 6: Commit**

Subject: `feat!: retire DO letter pipeline — DK Market Signals is the sole surface`
Body must note: existing Drive letters retained; rollback = git revert.

---

## Part 2 — dear-keyperson (prompt + GAS), dir `C:\Users\Admin\Documents\Life\dear-keyperson`, Life repo `main`

### Task 4: Phase 2b prompt — mandatory one-liner per person

**Files:**
- Modify: `claude/dk_synthesis_prompt.md` (§ "Phase 2b — People Briefs", lines ~144-198)

**Interfaces:**
- Produces: `people_briefs[]` entries for EVERY watchlist person, each with non-empty `brief` (≤30 words); `articles` may be `[]`. GAS Task 5 consumes `person.brief` unconditionally.

- [ ] **Step 1: Replace the "Omit if empty" section (lines 171-173) with:**

```markdown
### Mandatory coverage — no empty people

Every person in the watchlist gets a `people_briefs` entry with a non-empty `brief`, every day.

- Person has pool articles → brief references a specific finding (existing rule).
- Person has NO pool articles but maps to watchlist topics (roundup `person_deltas`) →
  synthesize the brief from those topics' headlines: one sentence on which topic move
  matters to this person this week and why, from Yuji's POV. Set `articles: []`.
- Person has neither → one-sentence fallback from persona context:
  "No fresh signal this week — <standing hook from persona, e.g. next natural check-in topic>."
  Set `articles: []`.

Never output an entry whose only content is a pointer to another section.
```

- [ ] **Step 2: Lint check**

Run: `grep -n "Omit if empty\|omit them" claude/dk_synthesis_prompt.md`
Expected: no matches.

- [ ] **Step 3: Commit (Life repo, main)**

Subject: `feat: DK Phase 2b — mandatory per-person one-liner, no empty briefs`

### Task 5: GAS people cards — brief always visible, redirects become chips

**Files:**
- Modify: `gas/01_dear_keyperson.js:1435-1472` (`DK_renderPeopleBranch_`)

**Interfaces:**
- Consumes: `person.brief` (Task 4 guarantees non-empty going forward; render must still survive empty for legacy payloads).
- Produces: card layout — brief always in `.synth-text`; roundup links as `.topic-chip` row; chain + sources unchanged.

- [ ] **Step 1: Replace the `bodyHtml` branch (lines 1442-1455) with:**

```javascript
  var chainHtml = '';
  if (chain && (chain.so_what || chain.then_what)) {
    chainHtml = DK_renderChainV2_(chain);
  }
  var chipsHtml = '';
  if (links.length > 0) {
    chipsHtml = '<div class="splits">' + links.map(function(l) {
      return '<a class="split" href="#wl-' + DK_esc_(l.wl_id || '') + '" style="text-decoration:none;color:#2A9D8F">&#127760; ' +
        DK_esc_(DK_stripLeadingGlobe_(l.topic_label || '')) + '</a>';
    }).join('') + '</div>';
  }
  var briefHtml = person.brief
    ? '<div class="synth-text">' + DK_esc_(person.brief) + '</div>'
    : (links.length ? '' : '<div class="synth-text" style="color:#8FA3AC">No brief today</div>');
  var bodyHtml = briefHtml + chipsHtml + chainHtml;
```

(The old `if (links.length > 0) {...} else {...}` block is removed entirely; the rest of the function is unchanged.)

- [ ] **Step 2: Verify with test render (see Task 8) before deploy.**

- [ ] **Step 3: Commit (Life repo, main)**

Subject: `fix: DK people cards — brief always shown, roundup links demoted to chips`

### Task 6: GAS dashboard header — KPI tiles + section nav

**Files:**
- Modify: `gas/01_dear_keyperson.js:1191-1391` (`DK_renderHtmlDrive_`), new helper `DK_renderKpiTiles_`

**Interfaces:**
- Consumes: `output.breaking`, `output.people_briefs`, `doHitsData.pool` (with Task 1 `note` optional), `storyCount`, `topics.length`, `editionNo`.
- Produces: `#kpi-row` tile grid + `#section-nav` sticky bar; legend moved to footer.

- [ ] **Step 1: Add helper above `DK_renderHtmlDrive_`:**

```javascript
function DK_renderKpiTiles_(output, doHitsData, storyCount, briefCount) {
  var breaking = output.breaking || [];
  var sevRank = { high: 2, medium: 1 };
  var topSev = breaking.reduce(function(best, b) {
    var s = (b.severity || '').toLowerCase();
    return (sevRank[s] || 0) > (sevRank[best] || 0) ? s : best;
  }, '');
  var people = output.people_briefs || [];
  var pool = (doHitsData && doHitsData.pool) || [];
  var mover = pool.reduce(function(best, m) {
    return Math.abs(m.delta_7d || 0) > Math.abs((best && best.delta_7d) || 0) ? m : best;
  }, null);
  var moverTxt = mover && mover.delta_7d != null
    ? DK_esc_(mover.outcome_label || mover.title || '') + ' ' + (mover.delta_7d >= 0 ? '+' : '') + Math.round(mover.delta_7d * 100) + 'pp'
    : '&mdash;';
  function tile(href, label, value, sub) {
    return '<a class="kpi" href="' + href + '"><span class="kpi-label">' + label + '</span>' +
      '<span class="kpi-value">' + value + '</span><span class="kpi-sub">' + sub + '</span></a>';
  }
  return '<div id="kpi-row">' +
    tile('#breaking', 'Breaking', String(breaking.length), topSev ? 'max ' + DK_esc_(topSev) : 'last 24h') +
    tile('#tree-people', 'People', String(people.length), 'briefs updated') +
    tile('#do-markets', 'Top mover', moverTxt, 'market signals') +
    tile('#tree', 'Coverage', storyCount + ' stories', briefCount + ' briefs') +
    '</div>' +
    '<nav id="section-nav">' +
    '<a href="#breaking">Breaking</a><a href="#tree-people">People</a>' +
    '<a href="#tree">Topics</a><a href="#do-markets">Markets</a></nav>';
}
```

- [ ] **Step 2: Add CSS inside the `<style>` block of `DK_renderHtmlDrive_`:**

```css
#kpi-row{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0 8px}
@media (max-width:560px){#kpi-row{grid-template-columns:repeat(2,1fr)}}
.kpi{display:flex;flex-direction:column;gap:3px;padding:14px 16px;border:1px solid #E2EAEC;border-radius:14px;background:#F5F7FA;text-decoration:none;color:#264653}
.kpi:hover{border-color:#2A9D8F}
.kpi-label{font-family:"SF Mono",ui-monospace,Consolas,monospace;font-size:10px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#8FA3AC}
.kpi-value{font-family:Futura,"Avenir Next",sans-serif;font-size:22px;font-weight:700;line-height:1.15}
.kpi-sub{font-size:11.5px;color:#5B707B}
#section-nav{position:sticky;top:0;z-index:10;display:flex;gap:6px;padding:10px 0;background:rgba(255,255,255,.95);backdrop-filter:blur(4px);margin-bottom:14px}
#section-nav a{font-family:"SF Mono",ui-monospace,Consolas,monospace;font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;padding:6px 14px;border-radius:999px;border:1.5px solid #E2EAEC;color:#5B707B;text-decoration:none}
#section-nav a:hover{border-color:#264653;color:#264653}
```

- [ ] **Step 3: Rewire the body**

- After `</header>`, replace the `.keyrow` div with `${DK_renderKpiTiles_(output, doHitsData, storyCount, topics.length)}`.
- Move the legend spans (`▲ up = in your favour` etc.) into the `<footer>` as a third `<span>`.
- Keep `.toolbar` (view toggle / collapse-all) directly under `#section-nav`.
- `DK_renderKpiTiles_` needs `doHitsData` — it is already a parameter of `DK_renderHtmlDrive_`.

- [ ] **Step 4: Commit (Life repo, main)**

Subject: `style: DK dashboard header — KPI tiles + sticky section nav, legend to footer`

### Task 7: GAS DO market cards with notes

**Files:**
- Modify: `gas/01_dear_keyperson.js:2324-2395` (`DK_renderDoMarketsSection_`)

**Interfaces:**
- Consumes: pool item fields `note`, `relevance` (Task 2; both optional for legacy payloads).
- Produces: card per market — title link, outcome + %, probability bar, delta chip, note line, muted volume. Legacy items (no `note`) keep the current single-line rendering.

- [ ] **Step 1: Replace the `linesHtml` map body (lines 2370-2384) with:**

```javascript
  var linesHtml = allMarkets.map(function(m, idx) {
    var prob = Math.round((m.prob_now || 0) * 100);
    var delta = m.delta_7d != null ? (m.delta_7d >= 0 ? '+' : '') + Math.round(m.delta_7d * 100) + 'pp' : '';
    var vol = m.volume_usd != null ? '$' + (m.volume_usd >= 1000000000 ? (m.volume_usd / 1000000000).toFixed(2) + 'B' : m.volume_usd >= 1000000 ? (m.volume_usd / 1000000).toFixed(1) + 'M' : Math.round(m.volume_usd / 1000) + 'K') : '';
    var tier = idx < tierALen ? 'relevance' : 'general';
    var href = DK_safeHref_(m.url || '');
    var rawLabel = (m.outcome_label || '').trim();
    var outcomeLabel = rawLabel && rawLabel !== (m.title || '').trim() ? rawLabel : '';
    if (!m.note) {
      return '<div class="do-market-line" data-tier="' + tier + '" style="margin:6px 20px;font-size:12px;color:#5B707B;font-family:\'SF Mono\',monospace">' +
        '&#127914; <a href="' + href + '" target="_blank" rel="noopener" style="color:#2A9D8F;text-decoration:none">' + DK_esc_(m.title || '') + '</a>' +
        ' &mdash; ' + (outcomeLabel ? '<span style="color:#264653;font-weight:600">' + DK_esc_(outcomeLabel) + '</span> ' : '') +
        '<b style="color:#264653">' + prob + '%</b>' +
        (delta ? ' <span style="color:' + (m.delta_7d >= 0 ? '#2D8659' : '#C0392B') + '">' + delta + '</span>' : '') +
        (vol ? ' · ' + vol : '') + '</div>';
    }
    var deltaChip = delta
      ? '<span style="font-weight:800;font-size:12px;color:' + (m.delta_7d >= 0 ? '#2D8659' : '#C0392B') + '">' + (m.delta_7d >= 0 ? '&#9650; ' : '&#9660; ') + delta + '</span>'
      : '';
    var relChip = m.relevance && m.relevance !== 'none'
      ? '<span style="font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#2A9D8F;border:1px solid #2A9D8F;border-radius:6px;padding:2px 7px">' + DK_esc_(m.relevance) + '</span>'
      : '';
    return '<div class="do-market-card" data-tier="' + tier + '" style="margin:0 0 10px;padding:12px 14px;background:#fff;border:1px solid #E2EAEC;border-radius:12px">' +
      '<div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap">' +
      '<a href="' + href + '" target="_blank" rel="noopener" style="color:#264653;font-size:14px;font-weight:600;text-decoration:none">' + DK_esc_(m.title || '') + '</a>' + relChip + '</div>' +
      '<div style="display:flex;align-items:center;gap:10px;margin-top:7px;flex-wrap:wrap">' +
      (outcomeLabel ? '<span style="font-size:13px;color:#5B707B">' + DK_esc_(outcomeLabel) + '</span>' : '') +
      '<b style="font-size:15px;color:#264653">' + prob + '%</b>' + deltaChip +
      '<span style="font-family:\'SF Mono\',monospace;font-size:11px;color:#8FA3AC;margin-left:auto">' + vol + '</span></div>' +
      '<div style="height:5px;border-radius:999px;background:#E2EAEC;margin-top:8px;overflow:hidden">' +
      '<div style="height:100%;width:' + prob + '%;background:#2A9D8F"></div></div>' +
      '<div style="font-size:12.5px;line-height:1.5;color:#5B707B;margin-top:8px">' + DK_esc_(m.note) + '</div></div>';
  }).join('');
```

- [ ] **Step 2: Widen the section wrapper padding** — in the returned `<section id="do-markets">`, change inner card margins already handled above; section style stays as is.

- [ ] **Step 3: Commit (Life repo, main)**

Subject: `feat: DK Market Signals — annotated cards with prob bar, delta chip, note`

### Task 8: GAS render smoke tests, verify, deploy

**Files:**
- Modify: `gas/99_test.js` (append tests)

**Interfaces:**
- Consumes: all Task 5-7 renderers.

- [ ] **Step 1: Append smoke tests to `99_test.js`:**

```javascript
function DK_test_brushup_renderSmoke() {
  var output = {
    breaking: [{ severity: 'medium', headline: 'x', url: 'https://e.com', why: 'w', source: 's', age: '1h' }],
    people_briefs: [
      { name: 'Marcus', role: 'Accountant', brief: 'RBA held — ask about pre-approval.', articles: [] },
      { name: 'Harmeet', role: '', brief: 'AI rehiring wave is his week.', articles: [] }
    ],
    topics: []
  };
  var doHits = { ok: true, hits: {}, pool: [{
    title: 'Reserve Bank of Australia Decision in August', url: 'https://polymarket.com/event/rba',
    prob_now: 0.88, delta_7d: 0.01, volume_usd: 5000, outcome_label: 'No change',
    note: 'No change firmed +1pp over 7d — feeds straight into your mortgage.', relevance: 'rba'
  }] };
  var html = DK_renderHtmlDrive_(output, '2026-07-04', doHits);
  if (html.indexOf('kpi-row') === -1) throw new Error('KPI tiles missing');
  if (html.indexOf('section-nav') === -1) throw new Error('section nav missing');
  if (html.indexOf('RBA held') === -1) throw new Error('person brief not rendered');
  if (html.indexOf('do-market-card') === -1) throw new Error('DO card missing');
  if (html.indexOf('feeds straight into') === -1) throw new Error('DO note missing');
  Logger.log('DK_test_brushup_renderSmoke PASS');
}

function DK_test_brushup_legacyFallback() {
  var doHits = { ok: true, hits: {}, pool: [{
    title: 'World Cup Winner', url: 'https://polymarket.com/event/wc',
    prob_now: 0.33, delta_7d: 0.14, volume_usd: 3790000000, outcome_label: 'France'
  }] };
  var html = DK_renderDoMarketsSection_(doHits, '');
  if (html.indexOf('do-market-line') === -1) throw new Error('legacy line fallback missing');
  if (html.indexOf('do-market-card') !== -1) throw new Error('legacy item wrongly got card');
  Logger.log('DK_test_brushup_legacyFallback PASS');
}
```

- [ ] **Step 2: Push and run tests**

Run: `npx clasp push` (from `gas/`), then execute `DK_test_brushup_renderSmoke` and `DK_test_brushup_legacyFallback` in the Apps Script editor (or `npx clasp run` if configured).
Expected: both log PASS. `clasp push` alone does NOT publish — safe.

- [ ] **Step 3: Visual check**

Trigger the render test function that writes a Drive HTML (`DK_renderHtmlDrive_` output via existing debug path) or paste smoke-test HTML into a local file; open at 390px width. Verify: tiles 2×2, nav sticky, person one-liners visible, DO cards readable.

- [ ] **Step 4: CONFIRM WITH YUJI, then deploy**

Production write gate — ask before running:
`.\gas\deploy-dk.ps1 'brushup: dashboard tiles, people one-liners, DO note cards'`
Then verify the fix is live on DK_EXEC_URL in browser.

- [ ] **Step 5: Commit (Life repo, main)**

Subject: `test: DK brushup render smoke + legacy fallback; deploy`

---

## Verification (end-to-end)

1. `python -m pytest tests/ -q` in dear-oracle → clean.
2. Manual scan per CLAUDE.md → confirm `G:\My Drive\DawnPatrol\do_hits.json` `meta.generated_at` advanced AND pool items carry `note`/`relevance`.
3. Next morning's DK render (or manual GAS run) shows tiles, one-liners, note cards.
4. Confirm no new files appear in `G:\My Drive\dear-oracle-letters\` after the daily run.

## Rollback

- Python: `git revert` the commits on dear-oracle master; restore `drive_letters_path` key.
- GAS: redeploy previous version via `.\gas\deploy-dk.ps1` (fixed deployment ID).
- Old renderer ignores `note`/`relevance` — data format rollback unnecessary.
