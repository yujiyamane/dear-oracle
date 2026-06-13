# oracle-onboard — First Letter + P.S. editor

Agent-agnostic interactive skill.  Multi-turn conversation — never `claude -p`.
The agent drives the dialogue; Python helpers in `core/onboard.py` do all file I/O and coverage lookups.

---

## How to invoke

```
/oracle-onboard
```

Or: ask the assistant to "set up my interests" / "add F1 to my watchlist" / "P.S. drop surfing".

---

## Entry: detect mode

Run from the repo root:

```bash
python - <<'PY'
from core.onboard import load_interests_mode
print(load_interests_mode("config/interests.json"))
PY
```

| Result | Branch |
|--------|--------|
| `first_letter` | → [First Letter flow](#first-letter-flow) |
| `ps`           | → [P.S. mode](#ps-mode) |
| `corrupt`      | → [Corrupt file](#corrupt-file) |

---

## First Letter flow

### 1 — Gather interests

Ask the user in plain words:

> What topics do you want to follow on prediction markets?
> (e.g. "soccer", "AI", "Australian politics", "Formula 1")

Collect a comma-separated or free-text list.  No structure required at this stage.

### 2 — Coverage lookup (one per interest)

For each interest the user named, run:

```bash
python - <<'PY'
from core.adapter_polymarket import PolymarketAdapter
from core.onboard import coverage_for
adapter = PolymarketAdapter()
candidates, count = coverage_for("INTEREST_NAME", adapter)
import json; print(json.dumps({"candidates": candidates, "market_count": count}))
PY
```

Replace `INTEREST_NAME` with the user's free-text entry.

Show the user a summary line per interest, e.g.:

```
  Football  →  3,600+ markets  (top tags: soccer, epl, world-cup)
  AI        →    450 markets   (top tags: artificial-intelligence)
  Surfing   →  none yet        → will be saved as dormant
```

### 3 — Broad-interest drill-down (market_count > 50)

If any interest returns `market_count > 50`, show the top candidate tags (up to 5) and ask which to focus on.  Offer a sensible default:

> Football has 3,600+ markets across tags: soccer (1,200), epl (800), world-cup (600), nfl (400), nba (200).
> Press Enter to track all, or type the tags you want (comma-separated):

If the user presses Enter (blank response), use all returned candidates.

### 4 — Confirm and write

Summarise the resolved interests and ask the user to confirm:

> Ready to save:
>   ✅ Football → soccer, epl, world-cup  (3 tags)
>   ✅ AI → artificial-intelligence       (1 tag)
>   💤 Surfing → dormant (no markets yet; will auto-activate when coverage appears)
>
> OK to save? (Enter = yes)

On confirmation, build and write the profile:

```bash
python - <<'PY'
from core.onboard import write_interests_atomic
import json, datetime

profile = {
    "schema_version": 1,
    "updated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    "interests": [
        # one dict per interest, following INTERFACES.md §5 exactly:
        # {
        #   "name": str,
        #   "status": "active" | "dormant",
        #   "resolved_tags": [{slug, tag_id}, ...],   # [] if dormant
        #   "focus": [],
        #   "keyword_fallback": str,
        #   "max_markets": 5,
        #   "threshold_pp": 5.0,
        #   "added_at": "YYYY-MM-DD",
        # }
    ],
}
write_interests_atomic(profile, "config/interests.json")
print("saved")
PY
```

Rules for each interest entry:

- `status = "active"` when `candidates` is non-empty  
- `status = "dormant"` when `market_count == 0`; `resolved_tags = []`; `keyword_fallback` = user's word  
- `keyword_fallback` is always set (used as search fallback in daily collection)

### 5 — Confirm saved

```bash
python -c "import json; d=json.load(open('config/interests.json')); print(json.dumps(d, indent=2))"
```

Print the saved file for the user to review.  Done — invite the user to run `python oracle.py "<question>"` to test their new profile.

---

## P.S. mode

Triggered when `load_interests_mode` returns `"ps"`.  Also triggered by phrases like "P.S. add…", "P.S. drop…", "show my profile".

### Show profile

```bash
python -c "import json; d=json.load(open('config/interests.json')); print(json.dumps(d, indent=2))"
```

### P.S. drop

Example: "P.S. drop surfing"

```bash
python - <<'PY'
from core.onboard import load_interests_mode, drop_interest, write_interests_atomic
import json

data = json.load(open("config/interests.json"))
updated = drop_interest(data, "surfing")
write_interests_atomic(updated, "config/interests.json")
print("dropped surfing")
PY
```

### P.S. add

Example: "P.S. add F1"

1. Run coverage lookup (same as First Letter step 2) for the new interest name.
2. Show the coverage summary.
3. Let the user confirm tag selection.
4. Append via `add_interest`:

```bash
python - <<'PY'
from core.onboard import add_interest, write_interests_atomic
import json, datetime

data = json.load(open("config/interests.json"))
new_interest = {
    "name": "F1",
    "status": "active",           # or "dormant" if market_count==0
    "resolved_tags": [{"slug": "formula-1", "tag_id": "400"}],
    "focus": [],
    "keyword_fallback": "F1",
    "max_markets": 5,
    "threshold_pp": 5.0,
    "added_at": datetime.date.today().isoformat(),
}
updated = add_interest(data, new_interest)
write_interests_atomic(updated, "config/interests.json")
print("added F1")
PY
```

Always show the final saved file after any edit.

---

## Corrupt file

When `load_interests_mode` returns `"corrupt"`:

1. **Back up first** — do not overwrite without a backup:

```bash
python - <<'PY'
import shutil, datetime, pathlib
src = pathlib.Path("config/interests.json")
if src.exists():
    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    dst = src.with_name(f"interests.corrupt.{ts}.json")
    shutil.copy2(src, dst)
    print(f"backed up to {dst}")
else:
    print("file missing, nothing to back up")
PY
```

2. **Ask the user** what to do — never silently restart First Letter:

> ⚠️ Your interests.json appears corrupted or unreadable.
> I've backed it up to `config/interests.corrupt.TIMESTAMP.json`.
>
> Options:
>   A) Start fresh with First Letter (clears old data)
>   B) Show me the backup so I can try to fix it manually

Wait for the user's choice before proceeding.

---

## interests.json schema reference (INTERFACES.md §5)

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

- `resolved_tags` is the daily-run source of truth; `keyword_fallback` is the fallback when tags return nothing.
- `status` is the truth source for coverage-transition detection (collector diffs today's vs yesterday's file).
- Writes are always atomic via `write_interests_atomic`.
