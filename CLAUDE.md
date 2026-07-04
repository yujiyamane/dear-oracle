# dear-oracle — Development notes

## Production output paths

| Artifact | Path |
|---|---|
| `do_hits.json` | `G:\My Drive\DawnPatrol\do_hits.json` (Drive folder `14RNcLAHrDxJ8S-frsiPJsbRXFGiUjGxr`) |
| Letters | `G:\My Drive\dear-oracle-letters\` |

Configured in `config/delivery.json` → `do_hits_path` / `drive_letters_path`.

**Do NOT use `data/do_hits.json` as the verification target** — that is the local repo copy and is not what DK (GAS) reads. After any scan run, confirm `generated_at` advanced in the Drive file:

```powershell
(Get-Content "G:\My Drive\DawnPatrol\do_hits.json" -Raw | ConvertFrom-Json).meta
```

## Running scan manually

```powershell
cd C:\Users\Admin\Documents\Life\05_systems\dear-oracle
python -c "
from pathlib import Path; from core.scan import scan
result = scan(out_path=Path('G:/My Drive/DawnPatrol/do_hits.json'))
print(result['meta']); print('pool:', len(result.get('pool',[])))
"
```

## Git

- Remote `origin` → public GitHub repo (dear-oracle). Check with `git remote -v` before pushing.
- Never push secrets (`config/.env` is in `.gitignore`).
