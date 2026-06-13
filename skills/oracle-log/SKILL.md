# oracle-log

> Agent-agnostic skill. Works in Claude Code, Copilot CLI, or any agent that
> can run Bash commands. Requires Python 3.10+ and the dear-oracle repo.

## Status

**Planned — not yet implemented (Sprint 5).**

This skill and its underlying `core/brier.py` module are gated on Spike B
resolving cleanly (see `docs/spike-b-verdict.md`). Spike B passed; Sprint 5
build has not started. No `oracle-log` command exists in the repo yet.

## Planned purpose

Record your own predictions, score them against the market and against resolved
reality, and surface calibration feedback over time.

## Planned features

**Prediction log**
- Record: `oracle-log record "Spain wins World Cup" 0.40` — stores your
  stated probability at the time alongside the current market price.
- Review: `oracle-log list` — shows all open predictions with current market
  price, your stated probability, and days open.
- Resolve: `oracle-log resolve <id> <outcome>` — marks the outcome (1/0) and
  triggers Brier scoring.

**Multi-class Brier scoring**
A question is a basket of binary outcomes; Brier over the basket is
`(1/N) · Σ (p_i − o_i)²` (N=2 special case for binary questions). Baskets are
scored only when all their markets are resolved; partially-resolved baskets stay
`pending` and are re-checked on each daily run.

**Calibration table**
`oracle-log scores` renders a formatted table: question, your probability,
market probability at time of record, outcome, Brier score. No AI narrative on
the log in v1 — deterministic display only.

**Contrarian note (Sprint 5)**
Surfaced per question: counter-arguments the market may be under-weighting,
clearly labelled as commentary (e.g. *"favourites have lost in the knockout
rounds in 3 of the last 4 tournaments"*). Never investment advice.

**Usage-driven interest suggestions (Sprint 5)**
If you repeatedly ask the Predictor about an unlisted topic, `oracle-log` offers
to add it to your `interests.json` profile.

## Sprint 5 gate

Sprint 5 does not start until the Spike B verdict on basket-resolution timing
is confirmed and the MVP fallback is decided (manual `resolved_outcome` entry
via this skill, or Brier deferred). See PRFAQ.md Q19.
