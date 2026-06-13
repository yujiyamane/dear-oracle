# Dear Oracle — INTERFACES.md (v0.2)

> The contract document. No code is written against assumptions not recorded here.
> Companion to PRFAQ v0.7. Reflects Grill Me deltas D1–D40.
> **Sprint 0 first action: this file + PRFAQ.md must be physically placed in the repo before any review or code.**

---

## 0. Default adapter (D1)

Default = **Polymarket**. Two API surfaces, kept separate:
- **Gamma** (`gamma-api.polymarket.com`) — reads/search/tags/events. Unauthenticated. The primary surface; satisfies the "zero API key" promise.
- **CLOB** (`clob.polymarket.com`) — `/prices-history` (missed-day backfill) and resolution fields only. Also keyless for reads. Limited, well-bounded use.

User-facing copy never names either (D14d). Adapter name appears only in technical docs.

## 1. Price representation (LOCKED)

- **Internal**: probability as float `0.00–1.00`.
- **Display**: percent (`24%`).
- **Deltas**: percentage points, suffix `pp` (`+6pp`), computed as `(p_now − p_then) * 100`. The float->pp conversion boundary is Layer 1; AI never sees raw 0–1 deltas.
- Source APIs may display cents (0–99¢); the adapter normalises to float at the boundary. Representations never mix past the adapter.

## 2. market_signals[] contract — THE SPINE (D13–D16, D29)

Nested `outcomes[]` so a multi-outcome basket (e.g. World Cup) is native. Layer 1 pre-computes everything; Layer 2 never re-evaluates thresholds.

```json
{
  "schema_version": 1,
  "source": "polymarket-gamma",
  "generated_at": "2026-06-13T05:00:00+10:00",
  "coverage_transitions": [
    { "interest": "surfing", "from": "dormant", "to": "active" }
  ],
  "signals": [
    {
      "event_id": "16085",
      "event_title": "Will a frontier lab declare AGI by end of 2027?",
      "interest_tag": "ai",
      "outcomes": [
        {
          "outcome_label": "Yes",
          "market_id": "0xabc",
          "url": "https://polymarket.com/event/...",
          "prob_now": 0.24,
          "prob_24h_ago": 0.18,
          "prob_7d_ago": null,
          "delta_24h_pp": 6.0,
          "delta_7d_pp": null
        }
      ],
      "threshold_pp": 5.0,
      "threshold_exceeded": true,
      "threshold_triggered_by": "delta_24h",
      "volume_usd": 450000,
      "end_date": "2027-12-31"
    }
  ]
}
```

Field rules:
- `prob_*`: float 0–1; `prob_7d_ago`/`prob_24h_ago` nullable when snapshot history is shorter than the window (then the matching `delta_*_pp` is null and `threshold_exceeded` is judged on available deltas only) (D15).
- `delta_*_pp`: percentage points (D14).
- `threshold_exceeded`: deterministic — `max(abs(available delta_pp)) >= threshold_pp`.
- `threshold_triggered_by`: the single window with the larger `|delta_pp|` (`"delta_24h"` or `"delta_7d"`) — gives the letter a deterministic headline choice (D16).
- `url`: per outcome — powers the letter's "read more" and P.S. routing (D16).
- `volume_usd`: included so the AI judges conviction-vs-noise without a second API call.
- `coverage_transitions[]`: deterministically computed from yesterday's vs today's interest statuses; the letter renders these as fixed phrases, AI does not decide them (D29).
- **Forward compatibility**: consumers MUST ignore unknown extra fields.

The Predictor output and the prediction log mirror this `outcomes[]` shape, so Predictor / signals / log are one structure (D8, D17).

## 3. Adapter interface (D21, D24)

```python
class MarketAdapter(Protocol):
    def search(self, query: str, limit: int = 10) -> list[Event]: ...
    def events_by_tag(self, tag_id: str, limit: int = 20) -> list[Event]: ...
    def markets_for_event(self, event_id: str) -> list[Market]: ...
    def tags(self) -> list[Tag]: ...           # Tag = {"slug": str, "tag_id": str}
    def prices_history(self, market_id: str, since: str) -> list[PricePoint]: ...
    def resolution(self, market_id: str) -> Resolution | None: ...
```

- `tags()` returns `{slug, tag_id}` pairs. `tag_id` is adapter-specific (Polymarket numeric); the *shape* is common, so a Kalshi adapter fills it from its own taxonomy. `slug` is human-readable for display; `tag_id` is the API key.
- All methods: timeout 10s, single retry with backoff, then return empty + log. Skills degrade gracefully ("no markets found for [interest]") — never abort.
- The same `resolve(tags) -> events` helper backs both `oracle-predictor` and `core/collector.py` (D33).

## 4. Rate limits (documented 2026-06-13)

Gamma published limits: general 4,000 req/10s; `/events` 500/10s; `/markets` 300/10s; `/public-search` 350/10s. Worst case (onboarding burst ~20 calls; daily monitor ≈ interests×5 + overhead ≈ 60 calls) is three orders of magnitude under limit. Courtesy: 250ms spacing between onboarding calls.

## 5. interests.json schema (D22, D30)

```json
{
  "schema_version": 1,
  "updated_at": "2026-06-13T07:10:00+10:00",
  "interests": [
    {
      "name": "soccer",
      "status": "active",
      "resolved_tags": [
        { "slug": "world-cup", "tag_id": "204" },
        { "slug": "epl", "tag_id": "118" }
      ],
      "focus": ["world cup", "premier league title"],
      "keyword_fallback": "soccer",
      "max_markets": 5,
      "threshold_pp": 5.0,
      "added_at": "2026-06-13"
    },
    {
      "name": "surfing",
      "status": "dormant",
      "resolved_tags": [],
      "focus": [],
      "keyword_fallback": "surfing",
      "max_markets": 5,
      "threshold_pp": 5.0,
      "added_at": "2026-06-13"
    }
  ]
}
```

- `resolved_tags` is the source of truth for daily resolution (stored at onboarding as `{slug, tag_id}` so daily runs need no ID re-lookup). `focus` is a human-readable note only.
- `keyword_fallback` used when `resolved_tags` is empty or a tag returns nothing.
- `status` (active/dormant) is the truth source for coverage-transition detection; the collector diffs today's vs yesterday's file.
- Writes are atomic: write `interests.json.tmp`, fsync, rename. Mode detection (First letter vs P.S.) reads `schema_version` from CONTENTS; unparseable/missing field = treat as corrupt, back up, ask the user — never silently restart onboarding.
- Eligibility at resolution time: `end_date >= now + 30 days` (broad-interest guard).

## 6. SQLite schema (data/schema.sql — D5, D17, plus WAL/run_log)

Database: `data/oracle.db`. Timestamps ISO-8601 local (+10:00).

```sql
PRAGMA journal_mode=WAL;          -- skills read while the scheduled run writes

CREATE TABLE run_log (
  run_at   TEXT NOT NULL,
  phase    TEXT NOT NULL,         -- 'auth' | 'collect' | 'letter' | 'dormant_scan' | 'deadman'
  status   TEXT NOT NULL CHECK (status IN ('ok','fallback','error')),
  detail   TEXT                   -- home dir normalised to ~ before insert (D40)
);

CREATE TABLE snapshots (
  snap_date    TEXT NOT NULL,
  market_id    TEXT NOT NULL,
  event_id     TEXT NOT NULL,
  interest     TEXT NOT NULL,
  question     TEXT NOT NULL,
  outcome      TEXT NOT NULL,
  probability  REAL NOT NULL CHECK (probability BETWEEN 0 AND 1),
  volume_usd   REAL,
  end_date     TEXT,
  backfilled   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (snap_date, market_id)
);
CREATE INDEX idx_snap_market ON snapshots (market_id, snap_date);

CREATE TABLE alerts (
  alert_date    TEXT NOT NULL,
  market_id     TEXT NOT NULL,
  interest      TEXT NOT NULL,
  delta_24h_pp  REAL,
  delta_7d_pp   REAL,
  letter_date   TEXT,
  PRIMARY KEY (alert_date, market_id)
);

-- one row per QUESTION (event), not per market (D5, D17)
CREATE TABLE prediction_log (
  id            INTEGER PRIMARY KEY,
  asked_at      TEXT NOT NULL,
  question      TEXT NOT NULL,
  event_id      TEXT,
  my_probs      TEXT,             -- JSON {outcome_label: prob} mirroring outcomes[]
  market_probs  TEXT,             -- JSON {outcome_label: prob} at ask time
  resolved_at   TEXT,             -- filled only when ALL basket markets resolved
  outcomes_json TEXT,             -- JSON {outcome_label: 0|1} final
  brier_mine    REAL,             -- multi-class (1/N) Σ (p_i - o_i)^2
  brier_market  REAL
);
```

- Deltas in one statement: window/self-join over `idx_snap_market`.
- Backfilled rows carry `backfilled=1` (provenance).
- Partial resolution: a basket is scored only when every constituent market is resolved; until then `resolved_at` stays NULL and it is re-checked next run.
- TDD: the full suite runs against `sqlite3 ':memory:'`.

## 7. claude -p invocation contract (Layer 2 — D18, D9, D10, D25, D26)

One call per day, immediately after collection, on the owner's PC:

```
claude -p prompts/letter.md \
  --allowedTools web_search \
  < data/exports/2026-06-13.signals.json \
  > stdout
```

- **Output = a single JSON envelope** `{"html": "...", "plaintext": "..."}` — raw JSON only, NO code fences. Python `json.loads(stdout)` splits it.
- Input: the day's `market_signals[]` export. The prompt caps analysis at top 3 movers by `|delta_24h_pp|`; scenario depth defaults to 2 stages (`then -> and then`), configurable in `prompts/scenario.md`.
- The why-section is the only step using web search (~1 search per mover, 5–10s each). If no credible source is found, the section is skipped honestly (voice block).
- Every prompt file begins with the conservative-voice block (PRFAQ Q13).
- **Preflight**: a `claude -p "ping"` smoke test runs first; on failure -> `run_log('auth','error',...)` and the quiet-seas form is sent.
- **Failure / fallback**: non-zero exit, 300s timeout, or unparseable JSON -> deterministic quiet-seas plaintext from the signals export, `run_log('letter','fallback',<error>)`, delivery proceeds. (JSON-parse failure is covered here — not a new failure mode.)
- **oracle_dryrun()** (test entry point, port of DP_dryRun): bypasses the AI call entirely, injects a canned JSON envelope fixture, runs Layer 1->3, asserts structure. Three fixtures: one mover / three movers / all-dormant. Zero Claude calls.

## 8. Delivery adapter contract (Layer 3 — D19, D20, D34, D35)

Input: `(letter_html, letter_txt, date)`. Obligation: make the full letter readable and send a digest.

- **gas adapter** (default, author's instance):
  - Python writes `letter_html` to the **Drive-for-Desktop synced folder** (e.g. `G:\My Drive\dear-oracle\letters\<date>.html`); the OS syncs it. No Drive-API code, no POST, no re-deploy.
  - `doGet?date=YYYY-MM-DD` reads the file by name and serves it via HtmlService (no param = latest; `?list=1` = archive index). **Read-only; no doPost.**
  - MailApp sends the digest: first 3 plaintext lines + "Read the full letter" link.
  - **Access model = "Only me"** Google-auth deployment (D34): one settings click, costs nothing, and an enumerable date URL is harmless because unauthenticated requests hit Google sign-in. (Preferred over a URL token — no token to manage.)
- **smtp adapter** (server-less, no Google account):
  - There is no doGet and no server, so the "authenticate the URL" question dissolves. The **full HTML is inlined into the email body** (digest + inline, not digest + link). Attack surface: none (no endpoint exists). Inline CSS only (no `<style>` reliance).

README privacy note (D36) is scoped to **only** the case of a GAS adapter deployed as "Anyone": "Use Only me; if you deploy Anyone, forwarding your digest exposes your interests." SMTP users get no such note (irrelevant — server-less).

## 9. Technical spike (Sprint 0 gate — D2, D7)

- **Spike A — KILLED.** v0.6 went local-first; no browser component calls the market API in v1. (Revisit only if the Phase-2 static-demo deck is built — it would need a browser CORS check first.)
- **Spike B — the only live spike (dual purpose).**
  1. Does CLOB expose resolution cleanly (`closed` + final outcome prices) for Brier? The *real* test is **basket-resolution timing** — confirming all constituent markets of a multi-outcome event flip `resolved` together and `o_i` is extractable.
  2. Confirm `/prices-history` works keyless for missed-day backfill.
  FAIL on (1) -> Sprint 5 MVP fallback: manual `resolved_outcome` via `/oracle-log resolve`, or Brier deferred from v1.

## 10. Distribution (D37, D38, D39, D40)

- **LICENSE: MIT** (matches pbi-ai-skills; required by the clone-and-run promise).
- **.gitignore**:
```
data/oracle.db
data/*.db-wal
data/*.db-shm
data/exports/
data/letters/
config/interests.json
config/delivery.json
config/questions.json
.claude/
```
  `prompts/letter.md` (and the other prompts) are **distributed**, not ignored — the oracle's voice is a shipped artefact; a user who customises it forks/edits locally.
- **Example configs**: `delivery.example.json` placeholders — `"webapp_url": "https://script.google.com/macros/s/YOUR_SCRIPT_ID/exec"`, `"to": "your@email.com"`. (webapp_url is low-sensitivity under "Only me" but kept a placeholder to avoid enumeration.) `questions.example.json` stores tag/query entries (resolves live, so no dead-ID note needed). `interests.example.json` ships generic interests + placeholder thresholds.
- **PII (3-layer defence)**: `oracle.db` holds prediction history (raw question text + your probabilities), watched interests, and — in `run_log.detail` — local paths. No financial/health/credential data exists (no trading, no wallet, no API key). Defence: (1) whole DB gitignored; (2) README states "oracle.db is personal — never commit or share; deleting it resets the system, your interests.json survives"; (3) `run_log.detail` normalises the home directory to `~` before insert, so a gitignore slip never leaks a username.

---
*v0.2 — 2026-06-13. Finalise Tag/Event/Market/PricePoint/Resolution dataclasses and field nullability in Sprint 0.*
