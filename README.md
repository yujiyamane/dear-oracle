# Dear Oracle

> Something you read with your coffee.

Ask it a question in plain language — *"Who will win the next World Cup?"* — and it answers with probability-ranked outcomes sourced live from real-money prediction markets. No API key, no wallet, no subscription.

```
$ python oracle.py "Who will win the 2026 World Cup?"
-> Spain     30%   +4pp 7d
-> England   20%   --
-> Argentina 10%   -2pp 7d
-> France     5%   --
-> Field     35%
```

Dear Oracle also watches the markets you care about. Every morning it compares today's odds against its own historical snapshots, and when a probability swings past your threshold, it sends you a letter from the oracle.

## Status

| Component | Status |
|---|---|
| Predictor (NL → ranked probabilities) | ✅ LIVE |
| Full pipeline (collect → letter → Drive → doGet → email) | ✅ LIVE |
| GAS + Task Scheduler automation | ✅ LIVE |
| Deterministic daily letter (fallback path) | ✅ LIVE |
| AI-authored narrative letter (`claude -p`) | Phase 2 |

The deterministic letter (Where-things-stand snapshot + any transitions) is the production path for v1. The AI-narrative path via `claude -p` loads the full Claude Code session on the owner's PC — skills, MCP servers, memory, permission prompts — and blocks for the full 300 s timeout. Phase 2 hypothesis: run the call with a clean `CLAUDE_CONFIG_DIR` (no skills, no MCP) and a non-interactive permission-bypass flag so it completes in seconds.

## Quick start

```
git clone https://github.com/yujiyamane/dear-oracle
cd dear-oracle
python oracle.py "Who will win the 2026 World Cup?"
```

No runtime install needed — Python 3.10+ standard library only. To run the tests: `pip install pytest && python -m pytest`.

## Documentation

- [PRFAQ.md](PRFAQ.md) — the why
- [INTERFACES.md](INTERFACES.md) — the contracts
- [PLAN.md](PLAN.md) — the build
- [docs/setup.md](docs/setup.md) — installation and Task Scheduler setup

> **Privacy**: `data/oracle.db` holds your prediction history and watched interests — never commit or share it. Deleting it resets the system; your `config/interests.json` survives.

What markets are pricing in — never advice.
