import sqlite3
from contextlib import contextmanager

_db_path: str = ""

SCHEMA = """
CREATE TABLE IF NOT EXISTS log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    service TEXT NOT NULL,
    raw_message TEXT NOT NULL,
    cluster_id INTEGER NOT NULL,
    params TEXT,
    dataset TEXT NOT NULL,
    date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    template TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    first_seen TEXT,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    score REAL NOT NULL,
    anomaly_type TEXT NOT NULL,
    service TEXT,
    details TEXT,
    alert_sent INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT,
    dataset TEXT,
    date TEXT,
    created_at TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    causal_chain TEXT,
    evidence TEXT,
    data_coverage TEXT,
    quality TEXT,
    correct INTEGER
);

CREATE TABLE IF NOT EXISTS pending_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    retry_count INTEGER DEFAULT 0
);
"""


def get_db_path() -> str:
    return _db_path


def init_db(path: str) -> None:
    global _db_path
    _db_path = path
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.close()


@contextmanager
def get_connection():
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
