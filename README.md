# Dear Oracle

> Something you read with your coffee.

Ask it a question in plain language — *"Who will win the next World Cup?"* — and it answers with probability-ranked outcomes sourced live from real-money prediction markets. No API key, no wallet, no subscription.

```
$ oracle "Who will win the 2026 World Cup?"
-> Spain     30%   +4pp 7d
-> England   20%   --
-> Argentina 10%   -2pp 7d
-> France     5%   --
-> Field     35%
```

Dear Oracle also watches the markets you care about. Every morning it compares today's odds against its own historical snapshots, and when a probability swings past your threshold, it sends you a letter from the oracle.

## Quick start

```
git clone https://github.com/yujiyamane/dear-oracle
cd dear-oracle
pip install -r requirements.txt
oracle "Who will win the 2026 World Cup?"
```

## Documentation

- [PRFAQ.md](PRFAQ.md) — the why
- [INTERFACES.md](INTERFACES.md) — the contracts
- [PLAN.md](PLAN.md) — the build
- [docs/setup.md](docs/setup.md) — installation and Task Scheduler setup

> **Privacy**: `data/oracle.db` holds your prediction history and watched interests — never commit or share it. Deleting it resets the system; your `config/interests.json` survives.

What markets are pricing in — never advice.
