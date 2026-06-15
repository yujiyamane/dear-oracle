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
| Deterministic daily letter | ✅ LIVE — reliable production path |
| Brier-scored prediction log (`oracle-log`) | ✅ LIVE |
| AI-authored narrative letter (`claude -p`) | Best-effort (experimental) |

**The deterministic daily letter is the reliable production path.** The AI-narrative path via `claude -p` is implemented and wired in, but unreliable in a scheduled context: invoking `claude` loads the full personal session (skills, MCP servers, memory) which blocks or times out before the model call begins. The pipeline falls back to the deterministic letter automatically whenever the AI step fails or times out. A robust AI-narrative path would require an isolated config (`CLAUDE_CONFIG_DIR` with no skills/MCP) or direct Anthropic API use — future work.

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
