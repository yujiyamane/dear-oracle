# oracle-log

> Agent-agnostic skill. Works in Claude Code, Copilot CLI, or any agent that
> can run Bash commands. Requires Python 3.10+ and the dear-oracle repo.

## Status

**LIVE — Sprint 5 Phase A.** Core pipeline (record → list → resolve → scores)
is implemented and fully tested offline. Contrarian notes and usage-driven
interest suggestions are planned for Phase B (see below).

## Usage

```
python oracle.py log record "<question>" <outcome_label> <user_prob> [--market-prob P]
python oracle.py log list
python oracle.py log resolve <id> <yes|no>
python oracle.py log scores
```

### record

Store a binary prediction: your stated probability that `outcome_label` occurs.
`--market-prob` is optional; supply it to enable you-vs-market comparison later.

```
python oracle.py log record "Spain wins the tournament" Spain 0.40 --market-prob 0.35
```

### list

Show all open predictions with days open, your probability, and market probability.

```
python oracle.py log list
```

### resolve

Mark the outcome (`yes` / `no`). Computes and stores the binary Brier score.

```
python oracle.py log resolve 1 yes
```

### scores

Render a calibration table for all resolved predictions.

```
python oracle.py log scores
```

Output columns: `question | your p | mkt p | outcome | Brier`
Followed by mean Brier for you and (where market prob is available) for the
market — lets you see whether you beat the consensus at record time. Plain text,
source-agnostic (no platform names).

## Brier score

**Binary formula**: `(p − o)²` where `p` is your stated probability and
`o = 1` if the outcome occurred, `0` otherwise.

Implemented as the multi-class special case:
`binary_brier(p, occurred) = multiclass_brier([p, 1-p], [1,0] if occurred else [0,1])`
which reduces to `(p − o)²`.

General form: `(1/N) · Σ(p_i − o_i)²`

Lower is better: **0 = perfect calibration, 1 = worst possible for a binary prediction.**

## Planned features (Phase B)

**Contrarian note** — *(still planned)*
Surfaced per question: counter-arguments the market may be under-weighting,
clearly labelled as commentary (e.g. *"favourites have lost in the knockout
rounds in 3 of the last 4 tournaments"*). Never investment advice.

**Usage-driven interest suggestions** — *(still planned)*
If you repeatedly ask the Predictor about an unlisted topic, `oracle-log` offers
to add it to your `interests.json` profile.
