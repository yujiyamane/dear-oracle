"""core/run_daily.py — Morning orchestration: collect → letter → Drive sync.

Task Scheduler calls scripts/run_daily.bat which invokes this script.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Logging ──────────────────────────────────────────────────────────────────

_log_dir = PROJECT_ROOT / "data" / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)

log = logging.getLogger("dear-oracle")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.FileHandler(_log_dir / "dear-oracle.log", encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_h)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _do_hits_path() -> Path | None:
    """Return do_hits.json output path from env var or config/delivery.json."""
    env = os.environ.get("DEAR_ORACLE_DO_HITS_PATH")
    if env:
        return Path(env)
    cfg_file = PROJECT_ROOT / "config" / "delivery.json"
    if cfg_file.exists():
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        raw = cfg.get("do_hits_path")
        if raw:
            return Path(raw)
    return None


def _open_db() -> sqlite3.Connection:
    db_path = PROJECT_ROOT / "data" / "oracle.db"
    db = sqlite3.connect(db_path)
    db.executescript((PROJECT_ROOT / "data" / "schema.sql").read_text(encoding="utf-8"))
    db.commit()
    return db


def _load_profile() -> tuple[dict, Path]:
    interests_path = PROJECT_ROOT / "config" / "interests.json"
    if not interests_path.exists():
        example = PROJECT_ROOT / "config" / "interests.example.json"
        shutil.copy(example, interests_path)
        log.info("Seeded config/interests.json from interests.example.json")
    return json.loads(interests_path.read_text(encoding="utf-8")), interests_path


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    today = date.today().isoformat()
    log.info("── dear-oracle START %s ──", today)

    from core.adapter_polymarket import PolymarketAdapter
    from core.collector import collect
    from core.onboard import write_interests_atomic
    from core.scan import scan

    db = _open_db()
    profile, interests_path = _load_profile()
    adapter = PolymarketAdapter()
    exports_dir = PROJECT_ROOT / "data"

    # DK Watchlist scan → do_hits.json
    # Pass notion_token so Notion failure returns error status and skips the write
    log.info("scan start")
    do_hits_out = _do_hits_path()
    do_hits_result = scan(adapter=adapter, out_path=do_hits_out, notion_token=os.environ.get("NOTION_TOKEN"))
    log.info("scan done (output=%s)", do_hits_out or "none")

    # Render deterministic markets fragment alongside do_hits.json → do_markets.html
    if do_hits_out is not None:
        from core.do_markets_renderer import write_markets_fragment
        markets_out = do_hits_out.parent / "do_markets.html"
        try:
            write_markets_fragment(do_hits_result, markets_out)
            log.info("do_markets.html written to %s", markets_out)
        except Exception as exc:
            log.warning("do_markets.html render failed (non-fatal): %s", exc)

    # Layer 1: collect
    log.info("collect start")
    collect(profile, adapter, db, today, exports_dir=exports_dir)
    write_interests_atomic(profile, interests_path)
    log.info("collect done")

    db.close()
    log.info("── dear-oracle END %s ──", today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
