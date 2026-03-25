import json
from fastapi import APIRouter
from app.db import get_connection

router = APIRouter()


@router.get("")
async def get_anomalies():
    """List all detected anomalies."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM anomalies ORDER BY score DESC").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get("details"):
                try:
                    d["details"] = json.loads(d["details"])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(d)
        return result
