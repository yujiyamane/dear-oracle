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


def _drive_path() -> Path | None:
    """Return Drive sync folder from env var or config/delivery.json."""
    env = os.environ.get("DEAR_ORACLE_DRIVE_PATH")
    if env:
        return Path(env)
    cfg_file = PROJECT_ROOT / "config" / "delivery.json"
    if cfg_file.exists():
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        raw = cfg.get("drive_letters_path")
        if raw:
            return Path(raw)
    return None


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


def _copy_to_drive(drive_dir: Path, today: str) -> bool:
    """Copy today's html/txt letters to Drive folder; returns True if both land."""
    letters_dir = PROJECT_ROOT / "data" / "letters"
    drive_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("html", "txt"):
        src = letters_dir / f"{today}.{ext}"
        if src.exists():
            shutil.copy2(src, drive_dir / f"{today}.{ext}")
        else:
            log.warning("Letter source not found: %s", src)
    # Dead-man's switch
    missing = [ext for ext in ("html", "txt") if not (drive_dir / f"{today}.{ext}").exists()]
    if missing:
        log.warning("DEAD-MAN: %s not confirmed in Drive folder %s", missing, drive_dir)
        return False
    return True


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    today = date.today().isoformat()
    log.info("── dear-oracle START %s ──", today)

    from core.adapter_polymarket import PolymarketAdapter
    from core.collector import collect
    from core.onboard import write_interests_atomic
    from core.pipeline import run_letter
    from core.scan import scan, load_watchlist

    db = _open_db()
    profile, interests_path = _load_profile()
    adapter = PolymarketAdapter()
    exports_dir = PROJECT_ROOT / "data"

    # DK Watchlist scan → do_hits.json
    log.info("scan start")
    do_hits_out = _do_hits_path()
    scan(watchlist=load_watchlist(), adapter=adapter, out_path=do_hits_out)
    log.info("scan done (output=%s)", do_hits_out or "none")

    # Layer 1: collect
    log.info("collect start")
    collect(profile, adapter, db, today, exports_dir=exports_dir)
    write_interests_atomic(profile, interests_path)
    log.info("collect done")

    # Layer 2: letter
    signals_path = exports_dir / f"{today}.signals.json"
    log.info("run_letter start (signals: %s)", signals_path.name)
    result = run_letter(
        signals_path=signals_path,
        prompts_dir=PROJECT_ROOT / "prompts",
        exports_dir=exports_dir,
        db=db,
        today=today,
    )
    log.info("run_letter done (fallback=%s)", result.get("fallback", False))

    # Drive sync
    drive_dir = _drive_path()
    if drive_dir is None:
        log.warning("No Drive path configured — skipping sync (set DEAR_ORACLE_DRIVE_PATH or delivery.json)")
    else:
        ok = _copy_to_drive(drive_dir, today)
        log.info("Drive sync %s → %s", today, "ok" if ok else "WARN (dead-man triggered)")

    db.close()
    log.info("── dear-oracle END %s ──", today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
