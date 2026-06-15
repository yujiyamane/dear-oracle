# Dear Oracle (DO) — PRFAQ v0.8

> *Dear Oracle — letters from the crowd*
> Status: v1 SHIPPED — Sprint 5 Phase A complete (oracle-log + Brier, 71 tests green, 2026-06-15); AI narrative implemented (Sprint 4) but best-effort in scheduled context — deterministic letter is the proven production path
> Family: Dear Keyperson (DK) · Dawn Patrol (DP) · **Dear Oracle (DO)**
> Companion: INTERFACES.md (the contract), PLAN.md (the build), prompts/ (the voice)

---

## Press Release

### Dear Oracle: ask the prediction markets anything — and get a letter back when the world's odds shift

**SYDNEY, September 2026** — Today we release Dear Oracle, an open-source, zero-cost prediction-market intelligence toolkit. Ask it a question in plain language — *"Who will win the next World Cup?"* — and it answers with probability-ranked outcomes sourced live from real-money prediction markets: Spain (30%), England (20%), Argentina (10%). No API key, no wallet, no subscription.

Dear Oracle also watches the markets you care about. Every morning it compares today's odds against its own historical snapshots, and when a probability swings past your threshold, it sends you a letter from the oracle: what moved, why it likely moved, and a two-stage scenario — if this outcome becomes reality, here is the immediate impact, and here is the second-order effect that follows.

Unlike the many alert bots that ping you when prices move, Dear Oracle is built around understanding, not notification. It is something you read with your coffee, not another red-dot notification. It keeps a log of every question you ask and what you believed at the time, then scores you against the market and against reality — so over months you learn not just what the world thinks, but how good your own judgement is.

Getting started takes one short letter. Your first letter to the oracle simply names the futures you care about — football, AI, space, anything. The oracle checks live market coverage for each interest and builds your personal watch profile on the spot. Changed your mind later? Add a P.S. — "P.S. add Formula 1" — and the profile updates. Markets come and go as events resolve; your interests persist, and Dear Oracle quietly rotates fresh markets in under each one. Interests with no markets yet stay dormant and re-attach the moment coverage appears.

Everything runs on free infrastructure: a public prediction-market API, your existing Claude subscription for narrative analysis, and a local SQLite store. All probability mathematics is deterministic code; AI touches only the storytelling. The core is fully abstracted — swap the market source, swap email for Discord, or plug in your own data source through a simple JSON contract.

*"I wanted a system that treats market odds as letters from the future — something you read with your coffee,"* said Yuji Yamane, creator of Dear Oracle.

Get started: `git clone github.com/yujiyamane/dear-oracle` — copy the example configs, write your first letter, done.

---

## The correspondence frame (LOCKED)

Bidirectional by design: **you write letters to the oracle; the oracle writes back.**
- Your *first letter* names your interests. A *P.S.* updates them.
- The oracle's *reply* answers a question (Predictor).
- The oracle's *morning letter* reports moved odds (Monitor).
The oracle's voice: calm, brief, never imperative.

---

## Sample morning letter (plaintext reference — the contract for prompts/letter.md)

```
Subject: The crowd moved on AI overnight - Dear Oracle, 13 Jun

Dear Yuji,

One of your futures moved past its threshold.

WILL A FRONTIER LAB DECLARE AGI BY END OF 2027?      interest: ai
18% -> 24%   (+6pp in 24h, threshold 5pp)

Why it likely moved
A major lab teased a reasoning-model announcement, and two prominent
researchers shifted public timelines. Volume tripled overnight -
conviction money, not noise.

If it becomes real - stage 1
Immediate repricing of AI-exposed equities; enterprise adoption
timelines compress sharply.

Then what - stage 2
Labour-market policy responses within 12-18 months; the premium
shifts from building dashboards to orchestrating agents.

Where things stand
World Cup    Spain 30% (+2pp), England 20%, Argentina 10% (-1pp)
Fed cut       Yes 68%
Starship      71% (+3pp)
surfing       the markets are silent

New coverage: surfing markets found - now watching.

Read the full letter: <doGet link>

- The Oracle
What markets are pricing in - never advice.
Your interests: soccer * ai * space * surfing (dormant)
P.S. add [topic] / P.S. drop [topic] - write back any time.
```

---

## External FAQ (customer-facing)

**Q1. What exactly does Dear Oracle do?**
Three things. (1) **Predictor**: answers natural-language questions with probability-ranked outcomes from live prediction markets. (2) **Monitor**: tracks a personal watchlist daily, detects probability swings, and delivers an analysed morning letter explaining the move and its two-stage consequences. (3) **Log**: records your own predictions and scores them against the market and against resolved reality using Brier scores (a Brier score is a number from 0 to 1 measuring how well-calibrated your predictions were — 0 is perfect, 1 is maximally wrong).

A Predictor exchange looks like this:
```
$ oracle "Who will win the 2026 World Cup?"
-> Spain     30%   +4pp 7d
-> England   20%   --
-> Argentina 10%   -2pp 7d
-> France     5%   --
-> Field     35%
```
The Predictor's output, the daily signal export, and the prediction log all share one nested `outcomes[]` shape (a question is a basket of binary outcomes), so the three stay structurally consistent (see INTERFACES.md §2). When a question matches several live events, the oracle answers with the highest-volume one and lists the rest: *"Also pricing: UK general election · Australian federal — ask about either."*

**Q2. Is this investment or betting advice?**
No. Dear Oracle reports *what markets are pricing in* — information, never imperatives. It does not place trades, recommend positions, or connect to any wallet. Conservative voice is a hard design constraint enforced in every AI prompt (see Q13) and checked by an automated guardrail test.

**Q3. What does it cost to run?**
Zero API billing by design. The market data API is public and unauthenticated. AI narrative runs on an existing Claude subscription via the Claude Code CLI (`claude -p`) — consuming subscription quota, not API spend — and can be disabled entirely; the deterministic layers work standalone. Storage is a local SQLite file.

**Q4. What do I need to install?**
Minimum: Python 3.10+ and Claude Code for the interactive skills — that alone runs all three pillars locally (storage is a bundled SQLite file). The Predictor works with or without an interest profile: with one it filters to your interests; cold (no profile yet) it ranks purely by market volume, so `oracle "..."` answers on first clone before any onboarding. Optional: the delivery adapter for the morning-letter link (a small GAS web app + Google Drive, or plain SMTP), and a PC that is on at the scheduled collection time (missed days are backfilled automatically).

**Q5. Can I use markets other than the default source?**
Yes, by design. Data sources sit behind an adapter interface (INTERFACES.md §3). The default adapter is **Polymarket** — the Gamma API for reads/search/tags, and the CLOB API for price history and resolution only. Kalshi is the planned second adapter; any system that emits the documented `market_signals[]` JSON contract can plug in. User-facing copy never names the source — only "the markets" or "the crowd".

**Q6. Can I customise it?**
Everything user-specific lives in config, never code: `interests.example.json` (interests + per-item thresholds), `questions.example.json` (the popular-questions deck), `delivery.example.json` (email default; Discord/Telegram as power-user opt-ins), and the prompt templates in `prompts/` (the oracle's voice and scenario depth are editable; default scenario depth is two stages).

**Q7. How accurate are the answers?**
As accurate as the market — Dear Oracle adds no opinion of its own to the numbers. Prices are implied probabilities backed by real money. A planned *Contrarian note* (NOT in v1 — Sprint 5) will surface counter-arguments the market may be under-weighting, clearly labelled as commentary, e.g. *"favourites have lost in the knockout rounds in 3 of the last 4 tournaments."*

**Q8. What languages does it speak?**
v1 is English end-to-end: docs, prompts, and the oracle's replies. You may *ask* in any language Claude understands (a Japanese question is translated into a market-search query), but the reply and the morning letter come back in English. A `locale` config for reply language is deferred to v2.

**Q9. How does it know what I care about?**
Through your first letter — a one-time onboarding exchange. You name your interests in plain words ("soccer, surfing, AI, space"); an AI step maps each to candidate market tags, shows you real coverage ("Football: 3,600+ markets / Surfing: none yet — registered as dormant"), you confirm, and the confirmed tags are written to `interests.json`. Interests, not markets, are the unit of personalisation: markets attached to each interest rotate automatically as events resolve, and dormant interests are re-scanned (see Q9c).

If an interest is broad, the first letter narrows by discovery, not interrogation — it shows what it found and offers a default: *"Soccer has thousands of markets. The most-watched types: [World Cup outright] [Premier League title] [All championships]. Press enter for championship markets across all competitions."*

**Q9b. Can I change my interests later?**
Yes — write a P.S. Four channels. (1) The `oracle-onboard` skill is also the editor: if a valid `interests.json` exists it starts in P.S. mode — "P.S. add F1", "P.S. drop surfing", "show my profile". (2) Usage-driven suggestions (Sprint 5): repeatedly ask the Predictor about an unlisted topic and it offers to add it. (3) Edit `interests.json` directly — plain JSON. (4) The morning-letter footer itself is the standing reminder and reply channel (see sample letter).

**Q9c. What happens when there is nothing to show? (zero-states + transitions, LOCKED)**
- *Predictor, no matching market*: "The crowd hasn't priced this yet. The closest questions they have answered: [top 3 nearest matches]."
- *All interests dormant*: you still receive a short letter — a "Where things stand" snapshot is the spine of every letter, so even on a fully calm day it shows the current standing of each watched event (and notes which interests are silent), with an invitation to browse live categories.
- *First days of Monitor*: a Day-1 confirmation letter — "Letter received — your first morning letter arrives tomorrow." 24h deltas work from day 2; 7d deltas from day 8.
- *Dormant → active* (new coverage appeared): announced once in the letter footer — "New coverage: surfing markets found — now watching" — then treated as normal from the next day.
- *Active → dormant* (coverage ended): announced once — "Coverage ended: [interest] has no live markets — now dormant, I'll keep listening." The oracle reports both directions of the silence.

---

## Internal FAQ (design decisions)

**Q10. Why standalone instead of integrating into Dear Keyperson? (LOCKED 2026-06-11)**
Option C. DK's engine stays untouched; DO is a clean, publishable unit. A future bridge into DK's `dk_input` via the `market_signals[]` contract remains on the table but is OUT OF SCOPE for v1.

**Q11. What is the runtime architecture? (LOCKED v0.7)**
Local-first, three layers, one runtime (Python on the owner's PC) plus an optional delivery adapter:

```
LAYER 1  DATA       (Task Scheduler, daily ~05:00)
         core/collector.py: resolve interests' tags -> fetch markets
         -> append snapshots to SQLite (data/oracle.db, WAL mode)
         -> compute 24h/7d deltas in SQL -> threshold check
         -> compute coverage transitions vs yesterday's interests.json
         -> weekly dormant re-scan piggybacks here (days_since >= 7)
         -> export the day's market_signals[] JSON
         Missed days (PC off): backfilled from CLOB /prices-history.

LAYER 2  ANALYSIS   (same scheduled run, immediately after)
         deterministic: deltas, rotation, Brier (all SQL/Python)
         AI: ONE `claude -p prompts/letter.md` call (web search
         enabled for why-research) consuming the market_signals[]
         export -> JSON envelope {"html","plaintext"}

LAYER 3  UX         letter delivery + conversation
         GAS adapter: Python writes letter HTML to the Drive-for-Desktop
         synced folder -> doGet?date= reads it and serves it rendered;
         MailApp sends a 3-line digest + "Read the full letter" link.
         SMTP adapter: full HTML inlined into the email (server-less).
         Interactive skills talk to the same SQLite DB.
```

GAS cannot spawn subprocesses; the `claude -p` step runs on the owner's PC via Task Scheduler — the same proven pattern as Dawn Patrol and Dear Keyperson (PC must be on; documented in docs/setup.md).

Output handoff (LOCKED): `claude -p` emits a single JSON envelope `{"html":...,"plaintext":...}` (raw JSON only, no code fences). Python `json.loads` splits it; the handoff is unit-testable with a mocked envelope (no live Claude call). HTML reaches GAS via the Drive-for-Desktop synced folder (Python writes a local file, the OS syncs it, doGet reads it) — no Drive-API code, no POST endpoint, no re-deploy. doGet stays read-only.

Failure envelope (LOCKED, two layers):
- *Preflight*: before the real call, a `claude -p` smoke test captures the exit code and writes `('auth', ok|error)` to `run_log`.
- *Fallback*: any AI-step failure (auth expiry, model unavailable, context overflow, malformed/unparseable JSON) -> the pipeline falls back to a deterministic plaintext built from the signals export (the Where-things-stand snapshot + any transitions, with no AI narrative), logs `('letter','fallback', <error>)`, and delivery proceeds. The oracle never goes silent without a trace.
- *Dead-man's switch*: a separate check at delivery-time + 30 min verifies a letter exists for today; if not, it pings the owner regardless of cause (token / API / DNS / CLI contamination) — this catches whole-process death that the fallback cannot. Re-auth in a headless context is manual (OAuth needs a browser); the ping carries the human instruction "re-auth required: run `claude` interactively". Expected cost: a manual re-login roughly monthly, accepted under the $0 constraint and proven in Dawn Patrol operation.

Granularity: ONE `claude -p` call assembles the whole letter; the prompt caps analysis at the top 3 movers by |delta|. Expected movers at default 5pp thresholds: 0–3/day.

Delivery channel (LOCKED, a UX decision): email is the default because it is the only channel that preserves the letter experience. Discord/Telegram are opt-in adapters sharing the digest+link shape, documented but never promoted.

**Q12. Why SQLite for storage? (LOCKED v0.6)**
The `claude -p` analysis step always required the owner's PC; once that constraint is accepted, cloud scheduling buys nothing, and storage should sit next to the analysis. SQLite wins on every axis: indexed `(market_id, date)` lookups make delta queries one SQL statement; Brier is a `JOIN`; TDD runs against in-memory databases; and — decisive for an open-source portfolio piece — the core has **zero Google dependency**: clone, install, run. WAL mode lets interactive skills read while the scheduled run writes. Continuity gap (PC off at collection time) is closed by backfilling missed days from CLOB `/prices-history` on the next run (rows marked `backfilled=1`). Self-owned snapshots remain the source of record and the dataset that later powers macro correlation.

**Q13. What is deterministic code vs AI? (LOCKED)**
Deterministic: market search/fetch, probability aggregation and sorting (internal float 0.00–1.00; display percent; deltas in percentage points, `pp`), snapshot writes, delta calculation, threshold checks, interest->market resolution, coverage-transition detection, Brier scoring AND its display (formatted table only in v1 — no AI narrative on the log).

Multi-outcome Brier (LOCKED): a question is a basket of binary outcomes; Brier over the basket is `(1/N) · Σ (p_i − o_i)²`, with binary questions the N=2 special case of the same code path. A basket is scored only when *all* its markets are resolved; partially-resolved baskets stay `pending` and are re-checked next day.

AI (`claude -p`, pipeline prompt files): interpreting free-text questions, the why-research (runs with web search tool enabled — one search round-trip per moved market, ~5–10s each), the two-stage scenario, and letter prose.

Conservative-voice prompt block — this exact text prefixes every pipeline prompt and every interactive skill's system instructions:

> You report what the market is pricing. You do not recommend positions,
> you do not predict outcomes yourself, and you never use imperative
> language about money, trades, or bets. Probabilities belong to the
> crowd; you are the messenger.
> If web search returns no credible reporting for a movement, SKIP the
> why-section for that market and say so plainly ("the crowd moved;
> no reliable reporting found") — never fabricate an explanation.

**Q14. Skill taxonomy (LOCKED)**
Two distinct categories — never conflate them:

*Interactive skills* (user-invocable Claude Code sessions, multi-turn):
| Skill | Required tools | Purpose |
|---|---|---|
| oracle-predictor | Bash (core/predictor.py) or WebFetch | question -> ranked % |
| oracle-onboard | Bash (write interests.json) + WebFetch | First letter / P.S. mode |
| oracle-monitor | Bash (read state) | `/oracle-monitor status`: last run, last delta, last error, next schedule |
| oracle-log | Read/Write | prediction log + Brier table |

*Pipeline prompt files* (non-interactive, invoked via `claude -p` from Task Scheduler): `prompts/why.md`, `prompts/scenario.md`, `prompts/letter.md` (assembly). These are NOT skills.

Onboarding is inherently multi-turn (state interests -> see coverage -> refine -> confirm) and therefore an interactive skill, never a `-p` call. Resolver calls inside skills wrap the market API with a timeout and degrade gracefully: an error or empty result reports "no markets found for [interest]" and continues — never aborts.

**Q14b. Why an Interest Profile layer instead of a static market watchlist? (LOCKED)**
Markets resolve and close; interests persist. `interests.json` (with `schema_version`, written atomically via tmp-then-rename; mode detection reads the version field, never mere file existence) is the stable layer; the effective watchlist is a generated cache, refreshed daily by resolving each interest's stored tags to its top-N live markets (volume-sorted, capped at 5 per interest, per-interest `max_markets` override). **Broad-interest guard**: markets must have `end_date >= now + 30 days` at resolution time — single-match and short-horizon markets never qualify, because DO reads futures, not tonight's fixtures. Interests resolving to >50 candidates trigger the first-letter drill-down with a sensible default. Dormant interests re-scan when `days_since_last_successful_dormant_scan >= 7` (not a fixed weekday — survives a PC being off that day).

**Q14c. How are interests elicited and resolved? (LOCKED)**
Onboarding uses **AI mapping** (interactive only): free-text interest -> candidate `{slug, tag_id}` tags -> live coverage shown -> user confirms -> stored. Daily collection is **deterministic**: it runs the stored `tag_id`s directly (tag-first), with keyword fallback for interests that had no tag match. Degradation path: stored tag returns nothing (tag retired/renamed) -> keyword fallback -> if that is also empty, the interest auto-demotes to dormant and is offered for re-mapping next onboarding. The same `resolve(tags)->events` function backs both the Predictor and the collector. Optional adapter (off by default): mine interests from a personal knowledge base — used in the author's instance, documented as an extension point.

**Q14d. Why does the UI never name the data source? (LOCKED)**
Brand independence. All user-facing copy says "the markets" or "the crowd"; the source is an adapter named only in technical docs and INTERFACES.md. Adapter swaps require zero UI copy changes, and the oracle keeps its own voice.

**Q15. Differentiation vs prior art? (verified 2026-06-11, re-swept 2026-06-13)**
Existing tools are dashboards and alert bots. None offer: (a) NL question -> ranked-probability oracle, (b) two-stage scenario reasoning, (c) personal Brier-scored prediction log, (d) interest-driven auto-rotating watchlists, (e) a $0, config-driven, agent-agnostic skill package. Those five are the product.

**Q16. Repo layout (LOCKED)**
```
dear-oracle/
├── README.md         # hero: "Something you read with your coffee."
├── LICENSE           # MIT
├── PRFAQ.md
├── PLAN.md
├── INTERFACES.md     # market_signals[] contract, adapter, SQLite schema,
│                     # rate limits, price representation, spikes
├── .gitignore        # see INTERFACES.md / D37
├── core/             # python LAYER 1+2: adapter client, collector,
│                     # resolver, deltas, brier (SQL), signals export,
│                     # oracle_dryrun  -- zero Google deps, fully testable
├── data/             # oracle.db (SQLite, gitignored) + schema.sql
│   ├── exports/      # daily market_signals[] JSON (gitignored)
│   └── letters/      # generated letter html/txt (gitignored)
├── skills/           # interactive skills only (see Q14)
│   ├── oracle-predictor/SKILL.md
│   ├── oracle-onboard/SKILL.md
│   ├── oracle-monitor/SKILL.md
│   └── oracle-log/SKILL.md
├── prompts/          # pipeline prompt files + letter voice (DISTRIBUTED,
│                     # user-editable; scenario depth default 2 stages)
│   ├── why.md
│   ├── scenario.md
│   └── letter.md
├── delivery/         # OPTIONAL adapters
│   ├── gas/          # 01_dear_oracle.js + 99_test.js (doGet + MailApp)
│   └── smtp/         # pure-python alternative (inline HTML)
├── docs/
│   ├── setup.md      # Task Scheduler, auth, delivery adapter, doGet access
│   └── brand.md      # the palette — single source of truth for all HTML/SVG colour
├── tests/            # pytest: in-memory SQLite + fixtures + dryrun + lint
└── config/
    ├── interests.example.json
    ├── questions.example.json
    └── delivery.example.json
```
All SKILL.md files agent-agnostic. Personal configs gitignored; examples sanitised. Single public repo under `yujiyamane`.

**Q17. Success metrics**
v1 internal: Predictor answers a free-text question end-to-end in <60s (with web search; <30s without); Monitor produces its Day-1 confirmation immediately and its first delta letter from day 2; zero API billing confirmed over 30 days; the full pytest suite (deterministic core + dryRun E2E + prompt lint) runs green with **zero Claude calls**. Portfolio: a stranger reaches a first answer in under 5 minutes from the README; GitHub stars as a lagging signal.

**Q18. Out of scope for v1**
Trading or order placement of any kind. Real-time/intraday alerting. Macro Correlation View (Phase 2). Kalshi adapter (Phase 2). Static-page live-demo deck (Phase 2 showcase — requires a browser CORS check against the market API first). DK bridge (future). Reply-language locales (v2). Contrarian note + usage-driven interest suggestions (Sprint 5 Phase B — not yet built). Mobile app.

Note: Brier-scored prediction log (`oracle-log`: record/resolve/scores) is **LIVE** as of Sprint 5 Phase A.

**Q19. Build order (LOCKED)**
- **Sprint 0** — placement + contracts + spike. **First action: place PRFAQ.md + INTERFACES.md in the repo** (reviews assume both are on disk). Finalise INTERFACES.md. **Spike B** (the only remaining spike): verify CLOB exposes resolution cleanly (`closed` + final outcome prices) for Brier, AND that `/prices-history` works keyless for missed-day backfill — basket-resolution timing is the real test, not field existence. (Spike A — browser CORS — was killed when v0.6 went local-first; no browser calls the API in v1.)
- **Sprint 1** — `oracle-predictor` (interactive skill; zero infra; works cold without interests.json).
- **Sprint 2** — `oracle-onboard` (First letter + P.S. mode; AI tag-mapping; interest resolver in core/).
- **Sprint 3** — Layer 1: SQLite schema + collector + deltas + rotation + coverage-transition detection + backfill + signals export (pure code, TDD against in-memory DB), Day-1 letter.
- **Sprint 4** — Layer 2 AI + Layer 3: prompt files, Task Scheduler `claude -p` step, JSON-envelope split, `oracle_dryrun`, delivery adapter (doGet renderer + digest email / SMTP inline), deterministic fallback form.
- **Sprint 5** — GATED on Spike B verdict: `oracle-log` + Brier + Contrarian note + usage-driven interest suggestions. Spike B FAIL on resolution -> MVP fallback decided before sprint start (manual `resolved_outcome` via `/oracle-log resolve`, or Brier deferred). The sprint does not begin with this undecided.
Gate: PRFAQ ✅ -> UX mocks ✅ -> Grill Me ✅ (D1–D40) -> PLAN.md -> sub-agent re-review -> TDD build.

**Q20. Former open questions — all resolved**
1. Delivery channel: email default (UX decision), digest + doGet link (GAS) or inline HTML (SMTP). LOCKED.
2. Popular-questions deck: rot-proof by construction — entries store a tag/query, not a frozen event ID; the deck resolves each to the current top-volume live event at load time (deterministic, no AI). `questions.example.json` ships 10 curated entries. LOCKED.
3. Friend's-system contract: `market_signals[]` defined in INTERFACES.md §2 — the spine of every component. LOCKED.
4. Letter cadence: guaranteed daily letter; every letter carries the Where-things-stand snapshot, so calm days still show current standings. LOCKED.

---

---

## Phase 2 — AI-authored narrative letter (best-effort, not guaranteed)

**What was built (Sprint 4):** The `claude -p prompts/letter.md` step is implemented and wired into the pipeline. The JSON-envelope contract (`{"html":…,"plaintext":…}`), the headless flags (`--output-format json`, `--permission-mode dontAsk`, `--tools ""`, `--disable-slash-commands`), and the deterministic fallback on any failure are all in place and tested.

**Known constraint:** In a scheduled (Task Scheduler) context, invoking `claude` loads the complete personal Claude Code session — skills, MCP servers, memory system — before the model call begins. This makes the step unreliable: the pipeline falls back to the deterministic letter most of the time. The **deterministic daily letter is the proven production path**; AI narrative is a best-effort enhancement that fires when the environment allows.

**Why it is hard to fix in the current architecture:** The personal `claude` binary shares the user's `CLAUDE_CONFIG_DIR`. Isolating the call requires either (a) a clean throwaway config dir with no skills/MCP, or (b) bypassing the CLI entirely and calling the Anthropic API directly with `requests` + an API key — which would trade the $0 subscription-quota model for metered API spend. Both are valid future approaches; neither is the right trade-off for v1.

**What remains the same:** The prompt files (`prompts/letter.md`, `prompts/why.md`, `prompts/scenario.md`), the JSON-envelope contract, and the fallback logic are correct and unchanged. If the AI step does complete (e.g. in an interactive session or a cleaner environment), the full narrative letter is delivered. If it does not, the oracle never goes silent — the deterministic letter goes out instead and the fallback is logged.

**Sprint 5 Phase B (not yet built):** Contrarian note per prediction (one web search, clearly labelled commentary) and usage-driven interest suggestions remain planned work — not the AI-narrative reliability problem above.

---

*v1 shipped — 2026-06-13. Sprint 4 complete: full pipeline live (collect → letter → Drive → doGet → email), GAS+Scheduler automation running, deterministic fallback proven. Sprint 5 Phase A complete (2026-06-15): oracle-log LIVE (record/resolve/scores, Brier scoring, 71 tests green). AI narrative implemented but best-effort in a scheduled context — deterministic letter is the proven production path (see Phase 2 section). Sprint 5 Phase B next: Contrarian note + usage-driven interest suggestions.*
