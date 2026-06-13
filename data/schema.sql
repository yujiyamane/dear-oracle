PRAGMA journal_mode=WAL;          -- skills read while the scheduled run writes

CREATE TABLE IF NOT EXISTS run_log (
  run_at   TEXT NOT NULL,
  phase    TEXT NOT NULL,         -- 'auth' | 'collect' | 'letter' | 'dormant_scan' | 'deadman'
  status   TEXT NOT NULL CHECK (status IN ('ok','fallback','error')),
  detail   TEXT                   -- home dir normalised to ~ before insert
);

CREATE TABLE IF NOT EXISTS snapshots (
  snap_date    TEXT NOT NULL,
  market_id    TEXT NOT NULL,
  event_id     TEXT NOT NULL,
  interest     TEXT NOT NULL,
  question     TEXT NOT NULL,
  outcome      TEXT NOT NULL,
  probability  REAL NOT NULL CHECK (probability BETWEEN 0 AND 1),
  volume_usd   REAL,
  end_date     TEXT,
  backfilled   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (snap_date, market_id)
);
CREATE INDEX IF NOT EXISTS idx_snap_market ON snapshots (market_id, snap_date);

CREATE TABLE IF NOT EXISTS alerts (
  alert_date    TEXT NOT NULL,
  market_id     TEXT NOT NULL,
  interest      TEXT NOT NULL,
  delta_24h_pp  REAL,
  delta_7d_pp   REAL,
  letter_date   TEXT,
  PRIMARY KEY (alert_date, market_id)
);

-- one row per QUESTION (event), not per market
CREATE TABLE IF NOT EXISTS prediction_log (
  id            INTEGER PRIMARY KEY,
  asked_at      TEXT NOT NULL,
  question      TEXT NOT NULL,
  event_id      TEXT,
  my_probs      TEXT,             -- JSON {outcome_label: prob} mirroring outcomes[]
  market_probs  TEXT,             -- JSON {outcome_label: prob} at ask time
  resolved_at   TEXT,             -- filled only when ALL basket markets resolved
  outcomes_json TEXT,             -- JSON {outcome_label: 0|1} final
  brier_mine    REAL,             -- multi-class (1/N) sum (p_i - o_i)^2
  brier_market  REAL
);
