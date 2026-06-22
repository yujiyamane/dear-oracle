# oracle-predictor

> Agent-agnostic skill. Works in Claude Code, Copilot CLI, or any agent that
> can run Bash commands. Requires Python 3.10+ and the dear-oracle repo.

## Purpose

Answer any natural-language question about the future with probability-ranked
outcomes sourced live from real-money prediction markets.

## Usage

Invoke the skill with a plain-language question:

```
oracle "Who will win the 2026 World Cup?"
oracle "Will AGI be declared by end of 2027?"
oracle "Who wins the next Australian federal election?"
```

Running `oracle "…"` executes:

```bash
python oracle.py "<question>"
```

from the repo root.  No API key, no wallet, no subscription.

## Output format

```
2026 FIFA World Cup Winner
-> Spain          30%   +4pp 7d
-> England        20%   --
-> Argentina      10%   -2pp 7d
-> France          5%   --
-> Field          35%

Also pricing: 2028 US Presidential Election Winner · 2028 UK General Election
Ask about either for a full breakdown.
```

Column layout: `-> {outcome_label:<14} {prob:>3}%   {delta}`

Delta tokens:
- `+4pp 7d` / `-2pp 7d` — 7-day percentage-point swing
- `+6pp 24h` — 24-hour swing (shown when 7d delta is absent)
- `--` — no significant delta or data not yet available

Zero-result (market not yet priced):
```
The crowd hasn't priced this yet.
The closest questions they have answered:
  - Who will win the 2026 World Cup?
  - Who will win the US Presidential election?
  - Will AGI be declared by end of 2027?
```

## Behaviour modes

**Cold mode** (no `config/interests.json` present): ranks all matching events
by market volume.  Works on first clone with no onboarding required.

**Known-user mode** (`config/interests.json` present): filters candidates to
events whose tags match the user's active interest tags first, then ranks by
volume within that set.  A higher-volume off-profile event is ranked below a
lower-volume on-profile event.

**Multi-match**: when more than one live event matches the question, the
highest-volume event is the full ranked answer; the others are listed as
`Also pricing: …` for the user to follow up on.

## Rot-proof popular-questions deck

At invocation time, this skill pre-loads `config/questions.example.json`.
Each entry stores a `tag_id` and `query` — **never a frozen event ID**.
The current top-volume live event for each tag is resolved on the spot, so
the deck always reflects live markets regardless of which events have resolved
since the file was last edited.

## Running the skill

```bash
# From the repo root — cold mode (no interests.json)
python oracle.py "Who will win the 2026 World Cup?"

# With interests profile auto-loaded from config/interests.json
python oracle.py "Who wins the next election?"

# Module invocation (equivalent)
python -m core.predictor "Who will win the 2026 World Cup?"
```

The skill calls `core/predictor.py` via Bash and renders the ranked-% block
exactly as shown above.  All probability mathematics is deterministic code;
no AI is invoked for the Predictor output itself.

## Contrarian note (Sprint 5B)

After rendering the ranked-probability block, perform **one web search** to
surface a credible counter-argument to the market's leading outcome:

Search query: `{main_event_title} prediction market overconfident counter-argument`

Present any credible counter-argument under this exact header:

```
Commentary (not advice): {1–2 sentences of the strongest counter-argument found}
```

Rules:
- The label **must** be `Commentary (not advice):` — never omit or alter it.
- If web search returns no credible counter-argument, **SKIP this section entirely**. Never fabricate or speculate.
- One web search only — do not loop.
- Conservative voice applies: the same imperative-financial-language prohibition from `prompts/letter.md` holds here — you are the messenger, not an adviser.
