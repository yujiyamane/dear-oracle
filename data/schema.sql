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

-- prediction log (oracle-log) — one row per binary prediction
CREATE TABLE IF NOT EXISTS prediction_log (
  id            INTEGER PRIMARY KEY,
  question      TEXT NOT NULL,
  outcome_label TEXT NOT NULL,
  user_prob     REAL NOT NULL,
  market_prob   REAL,             -- market's prob at record time; NULL if not provided
  recorded_at   TEXT NOT NULL,    -- ISO-8601 local
  status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
  occurred      INTEGER,          -- 1=yes 0=no NULL=open
  brier_score   REAL,             -- binary_brier(user_prob, occurred) after resolve
  resolved_at   TEXT              -- ISO-8601 local; NULL until resolved
);
CREATE INDEX IF NOT EXISTS idx_pred_status ON prediction_log (status);
