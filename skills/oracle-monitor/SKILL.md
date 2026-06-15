# oracle-monitor

> Agent-agnostic skill. Works in Claude Code, Copilot CLI, or any agent that
> can run Bash commands. Requires Python 3.10+ and the dear-oracle repo.

## Purpose

Run the daily Monitor pipeline: collect market snapshots, compute 24h/7d deltas,
check per-interest thresholds, and send the morning letter via the configured
delivery adapter (GAS or SMTP).

**Status: LIVE (v1)** — deterministic daily letter is the reliable production path.
AI-authored narrative (`claude -p`) is best-effort: generated when the environment
allows, falls back to the deterministic letter automatically otherwise.

## What the Monitor does

1. Resolves each interest in `config/interests.json` to its top-N live markets
   (volume-sorted, capped at 5 per interest, `end_date >= now + 30 days`).
2. Fetches current prices and appends snapshots to `data/oracle.db`.
3. Computes 24h and 7d deltas in SQL; flags any market whose delta exceeds the
   per-interest threshold.
4. Detects coverage transitions (dormant → active, active → dormant).
5. Exports `data/exports/YYYY-MM-DD.signals.json` — the `market_signals[]`
   contract (see INTERFACES.md §2).
6. Builds the morning letter: v1 deterministic form (Where-things-stand snapshot
   + any movers + transitions). Writes HTML and plaintext to `data/letters/`.
7. Delivers via the adapter set in `config/delivery.json` (`gas` or `smtp`).

Missed days (PC was off at collection time) are backfilled automatically from
the CLOB `/prices-history` endpoint on the next run; backfilled rows are marked
`backfilled=1` in the DB and do not trigger threshold alerts retroactively.

## Running the pipeline

```bash
# Single manual run from the repo root
python core/run_daily.py

# Check last run status, last delta, next scheduled time
# (requires config/delivery.json to be set up)
python -c "from core.pipeline import last_run_status; last_run_status()"
```

For automated daily delivery, schedule `scripts/run_daily_hidden.vbs` in
Windows Task Scheduler (daily, ~05:00). See [docs/setup.md](../../docs/setup.md)
for the full Task Scheduler wiring.

## Config

```
cp config/delivery.example.json config/delivery.json
# Set adapter: "gas" or "smtp" and fill in the relevant block.
```

The `drive_letters_path` key (GAS adapter) must point to a folder synced by
Drive for Desktop — the pipeline writes the letter HTML there; the GAS `doGet`
endpoint reads it.

## Output

Daily letter HTML and plaintext land in `data/letters/YYYY-MM-DD.{html,txt}`.
Logs go to `data/logs/dear-oracle.log`.

## v1 vs Phase 2

| Feature | v1 status |
|---|---|
| Deterministic daily letter (Where-things-stand + movers) | ✅ LIVE |
| GAS + Task Scheduler automation | ✅ LIVE |
| SMTP delivery | ✅ LIVE |
| Missed-day backfill | ✅ LIVE |
| AI-authored narrative (`claude -p prompts/letter.md`) | Best-effort (falls back to deterministic) |

The AI path is implemented but unreliable in a scheduled context: invoking `claude`
loads the full personal session (skills, MCP servers, memory), which blocks or times
out before the model call begins. The oracle falls back to the deterministic letter
automatically. A robust implementation would use a clean `CLAUDE_CONFIG_DIR` (no
skills/MCP) or the Anthropic API directly — future work.
