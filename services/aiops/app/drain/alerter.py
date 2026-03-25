import json
import sqlite3
from datetime import datetime, timezone
import httpx


class KeepAlerter:
    def __init__(self, keep_api_url: str, keep_api_key: str, db_path: str = ":memory:"):
        self.keep_api_url = keep_api_url
        self.keep_api_key = keep_api_key
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._init_pending_table()

    def _get_conn(self) -> sqlite3.Connection:
        return self._conn

    def _init_pending_table(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                retry_count INTEGER DEFAULT 0
            )
        """)
        conn.commit()

    async def send_alert(self, anomaly: dict) -> bool:
        """Send alert to Keep API. Queue in SQLite on failure."""
        alert_payload = {
            "name": f"Log anomaly: {anomaly.get('template', 'unknown')}",
            "severity": "critical" if anomaly.get("score", 0) > 0.8 else "warning",
            "source": ["log-processor"],
            "service": anomaly.get("service", "unknown"),
            "description": (
                f"Template '{anomaly.get('template', '')}' anomaly detected. "
                f"Score: {anomaly.get('score', 0):.2f}. "
                f"Type: {anomaly.get('anomaly_type', 'unknown')}"
            ),
            "labels": {
                "anomaly_type": anomaly.get("anomaly_type", ""),
                "anomaly_score": str(anomaly.get("score", 0)),
            },
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.keep_api_url}/alerts/event/log-processor",
                    json=alert_payload,
                    headers={"x-api-key": self.keep_api_key},
                    timeout=10.0,
                )
                return response.status_code in (200, 201, 202)
        except Exception:
            # Queue for retry
            self._queue_alert(alert_payload)
            return False

    def _queue_alert(self, payload: dict):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO pending_alerts (created_at, payload, retry_count) VALUES (?, ?, 0)",
            (datetime.now(timezone.utc).isoformat(), json.dumps(payload)),
        )
        conn.commit()

    def get_pending_count(self) -> int:
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM pending_alerts")
        count = cursor.fetchone()[0]
        return count
