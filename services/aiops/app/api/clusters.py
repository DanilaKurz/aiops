from fastapi import APIRouter, Request
from app.db import get_connection

router = APIRouter()


@router.get("")
async def get_clusters(request: Request):
    """List all Drain template clusters."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM clusters ORDER BY count DESC").fetchall()
        return [dict(row) for row in rows]


@router.get("/timeline")
async def get_cluster_timeline(request: Request, window: int = 300):
    """Template counts per time window."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT timestamp, cluster_id, COUNT(*) as count
               FROM log_entries
               GROUP BY substr(timestamp, 1, 16), cluster_id
               ORDER BY timestamp"""
        ).fetchall()

    from collections import defaultdict
    windows = defaultdict(list)
    for row in rows:
        ts = dict(row)["timestamp"][:16] + ":00"
        windows[ts].append({
            "cluster_id": dict(row)["cluster_id"],
            "count": dict(row)["count"],
        })

    return [
        {"window_start": ws, "window_end": ws, "clusters": cl}
        for ws, cl in sorted(windows.items())
    ]


@router.get("/{cluster_id}")
async def get_cluster(cluster_id: int, request: Request):
    """Get single cluster detail."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        if row:
            return dict(row)
        return {"error": "Cluster not found"}
