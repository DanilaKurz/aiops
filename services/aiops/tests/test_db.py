import sqlite3
import tempfile
import os
from app.db import init_db


def test_init_db_creates_tables():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert "log_entries" in tables
        assert "clusters" in tables
        assert "anomalies" in tables
        assert "reports" in tables
        assert "pending_alerts" in tables


def test_init_db_idempotent():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)
        init_db(db_path)  # should not raise
