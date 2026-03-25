import json
from fastapi import APIRouter
from app.db import get_connection

router = APIRouter()


@router.get("")
async def get_anomalies(limit: int = 100):
    """List detected anomalies (default limit 100)."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM anomalies ORDER BY score DESC LIMIT ?", (limit,)).fetchall()
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
