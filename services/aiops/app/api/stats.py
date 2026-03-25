from fastapi import APIRouter
from app.db import get_connection
from app.models import StatsResponse

router = APIRouter()


@router.get("", response_model=StatsResponse)
async def get_stats():
    """Aggregate statistics for Grafana."""
    with get_connection() as conn:
        total_logs = conn.execute("SELECT COUNT(*) FROM log_entries").fetchone()[0]
        unique_templates = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
        anomaly_count = conn.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0]
        last_entry = conn.execute("SELECT MAX(timestamp) FROM log_entries").fetchone()[0]

    anomaly_rate = anomaly_count / max(total_logs, 1)
    return StatsResponse(
        total_logs=total_logs,
        unique_templates=unique_templates,
        anomaly_count=anomaly_count,
        anomaly_rate=round(anomaly_rate, 4),
        last_ingest=last_entry,
    )
