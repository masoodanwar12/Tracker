# database.py — SQLite setup and helper functions
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "workpulse.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            email       TEXT    UNIQUE NOT NULL,
            password    TEXT    NOT NULL,
            role        TEXT    NOT NULL DEFAULT 'employee',
            designation TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id             INTEGER NOT NULL,
            project             TEXT,
            notes               TEXT,
            check_in            TEXT    NOT NULL,
            check_out           TEXT,
            total_work_seconds  INTEGER DEFAULT 0,
            total_idle_seconds  INTEGER DEFAULT 0,
            status              TEXT    DEFAULT 'active',
            last_heartbeat_at   TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS screenshots (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id          INTEGER NOT NULL,
            user_id             INTEGER NOT NULL,
            file_name           TEXT    NOT NULL,
            captured_at         TEXT    NOT NULL,
            active_window_title TEXT,
            capture_type        TEXT    DEFAULT 'auto',
            viewed_by_owner     INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (user_id)    REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS activity_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL,
            event_type  TEXT    NOT NULL,
            occurred_at TEXT    NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ss_user    ON screenshots(user_id);
        CREATE INDEX IF NOT EXISTS idx_ss_session ON screenshots(session_id);
        CREATE INDEX IF NOT EXISTS idx_sess_user  ON sessions(user_id);
    """)

    conn.commit()

    # --- Safe migration for databases created before this column existed ---
    existing_cols = [row[1] for row in c.execute("PRAGMA table_info(sessions)").fetchall()]
    if "last_heartbeat_at" not in existing_cols:
        c.execute("ALTER TABLE sessions ADD COLUMN last_heartbeat_at TEXT")
        conn.commit()

    conn.close()
