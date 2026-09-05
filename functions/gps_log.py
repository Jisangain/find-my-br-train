# gps_log.py - SQLite log of every /sendupdate ping (accepted or rejected).
#
# This is raw training data for a future small ML fake-GPS classifier, not a
# app-facing feature - so it deliberately stores every ping, including the
# ones the heuristic filter rejects (those are the negative examples). The
# "accepted"/"reject_reason" columns are the *current heuristic's* verdict,
# not ground truth - keep that distinction in mind when using this for
# training later; it's a bootstrap label, not a guarantee.
#
# Writes are synchronous and best-effort: logging must never be the reason a
# real request fails, so every call site wraps this in a try/except and just
# prints a warning on failure.

import os
import sqlite3
import threading
from typing import Optional

DB_PATH = os.getenv("GPS_LOG_DB_PATH", "gps_updates.db")

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gps_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at INTEGER NOT NULL,      -- server wall-clock time.time() at receipt
    train_id TEXT NOT NULL,
    user_id TEXT,
    is_bot INTEGER NOT NULL DEFAULT 0,
    position REAL NOT NULL,            -- raw reported position (station-index units)
    timestamp INTEGER NOT NULL,        -- client-reported timestamp, normalized to seconds
    scheduled_position REAL,           -- timetable-implied position at this timestamp
    position_km REAL,                  -- position converted to cumulative route km
    scheduled_km REAL,                 -- scheduled_position converted to cumulative route km
    reference_km REAL,                 -- last-known accepted position (km) this ping was checked against
    reference_age_seconds REAL,        -- how old that reference was, in seconds
    implied_speed_kmh REAL,            -- km moved / time elapsed vs. the reference
    delay_minutes REAL,                -- schedule deviation implied by this position (+ = late)
    accepted INTEGER NOT NULL,         -- 1 = passed the heuristic filter, 0 = rejected
    reject_reason TEXT
);
"""

_INDEX = "CREATE INDEX IF NOT EXISTS idx_gps_updates_train_ts ON gps_updates(train_id, timestamp);"

# Columns added after the table's first release. SQLite has no
# "ADD COLUMN IF NOT EXISTS", so each is attempted and a "duplicate column"
# failure (already applied, e.g. against an already-deployed gps_updates.db)
# is silently ignored - this keeps old databases working without a separate
# migration step.
_MIGRATIONS = [
    "ALTER TABLE gps_updates ADD COLUMN teleport_enforced INTEGER",  # 1=enforced, 0=relaxed (unconfirmed reference), NULL=no route data
    "ALTER TABLE gps_updates ADD COLUMN backward_streak INTEGER",    # consecutive backward-trending reports from this same source, NULL=no route data
    "ALTER TABLE gps_updates ADD COLUMN delay_zscore REAL",          # delay_minutes vs. this train's own historical mean/stddev, NULL if too little history yet
]


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_SCHEMA)
        conn.execute(_INDEX)
        for migration in _MIGRATIONS:
            try:
                conn.execute(migration)
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()
        _conn = conn
    return _conn


def log_update(
    received_at: int,
    train_id: str,
    user_id: Optional[str],
    is_bot: bool,
    position: float,
    timestamp: int,
    accepted: bool,
    reject_reason: str = "",
    scheduled_position: Optional[float] = None,
    position_km: Optional[float] = None,
    scheduled_km: Optional[float] = None,
    reference_km: Optional[float] = None,
    reference_age_seconds: Optional[float] = None,
    implied_speed_kmh: Optional[float] = None,
    delay_minutes: Optional[float] = None,
    teleport_enforced: Optional[bool] = None,
    backward_streak: Optional[int] = None,
    delay_zscore: Optional[float] = None,
) -> None:
    """Record one /sendupdate ping. Best-effort - never raises."""
    try:
        with _lock:
            conn = _get_conn()
            conn.execute(
                """
                INSERT INTO gps_updates (
                    received_at, train_id, user_id, is_bot, position, timestamp,
                    scheduled_position, position_km, scheduled_km, reference_km,
                    reference_age_seconds, implied_speed_kmh, delay_minutes,
                    teleport_enforced, backward_streak, delay_zscore, accepted, reject_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    received_at, str(train_id), str(user_id) if user_id is not None else None,
                    1 if is_bot else 0, position, timestamp,
                    scheduled_position, position_km, scheduled_km, reference_km,
                    reference_age_seconds, implied_speed_kmh, delay_minutes,
                    None if teleport_enforced is None else (1 if teleport_enforced else 0),
                    backward_streak, delay_zscore,
                    1 if accepted else 0, reject_reason or None,
                ),
            )
            conn.commit()
    except Exception as e:
        print(f"Warning: failed to log GPS update to {DB_PATH}: {e}")
