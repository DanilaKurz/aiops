from fastapi import APIRouter, Request
from app.models import IngestRequest

router = APIRouter()


@router.post("/openrca")
async def ingest_openrca(req: IngestRequest, request: Request):
    """Ingest OpenRCA dataset: load logs -> Drain -> anomaly detection -> Keep alerting."""
    import json
    from datetime import datetime, timezone
    from app.drain.anomaly import AnomalyDetector
    from app.db import get_connection

    adapter = request.app.state.openrca
    parser = request.app.state.drain_parser
    settings = request.app.state.settings

    # 1. Load logs from OpenRCA
    logs = adapter.load_logs(req.dataset, req.date)

    # 2. Parse through Drain
    results = []
    for log in logs:
        result = parser.parse(log.message)
        results.append({
            "timestamp": log.timestamp,
            "service": log.service,
            "raw_message": log.message,
            "cluster_id": result["cluster_id"],
            "template": result["template"],
            "dataset": req.dataset,
            "date": req.date,
        })

    # 3. Save to SQLite
    with get_connection() as conn:
        for r in results:
            conn.execute(
                """INSERT INTO log_entries (timestamp, service, raw_message, cluster_id, params, dataset, date)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (r["timestamp"], r["service"], r["raw_message"], r["cluster_id"], "[]", r["dataset"], r["date"])
            )
        # Update cluster counts
        clusters = parser.get_clusters()
        for c in clusters:
            conn.execute(
                """INSERT OR REPLACE INTO clusters (id, template, count, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?)""",
                (c["id"], c["template"], c["count"],
                 datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat())
            )

    # 4. Anomaly detection
    # Build time windows from parsed results
    from collections import defaultdict
    window_size = settings.ANOMALY_WINDOW_SECONDS
    windows_map = defaultdict(lambda: defaultdict(int))
    for r in results:
        # Simple window: group by timestamp prefix (5-min buckets)
        ts = r["timestamp"][:16] + ":00"  # truncate to minute
        windows_map[ts][r["cluster_id"]] += 1

    windows = [
        {"window_start": ws, "template_counts": dict(tc)}
        for ws, tc in sorted(windows_map.items())
    ]

    detector = AnomalyDetector(
        window_seconds=window_size,
        contamination=settings.ANOMALY_CONTAMINATION,
    )
    anomalies = detector.detect(windows) if len(windows) >= 2 else []

    # 5. Save anomalies to SQLite
    with get_connection() as conn:
        for a in anomalies:
            conn.execute(
                """INSERT INTO anomalies (window_start, window_end, score, anomaly_type, service, details, alert_sent)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (a["window_start"], a["window_start"], a["score"], a["anomaly_type"],
                 None, json.dumps(a.get("contributing_templates", {})))
            )

    # 6. Send alerts to Keep (best effort)
    alerts_sent = 0
    if hasattr(request.app.state, "alerter") and request.app.state.alerter:
        alerter = request.app.state.alerter
        for a in anomalies:
            try:
                await alerter.send_alert({
                    "service": "unknown",
                    "template": str(a.get("contributing_templates", {})),
                    "score": a["score"],
                    "anomaly_type": a["anomaly_type"],
                })
                alerts_sent += 1
            except Exception:
                pass

    return {
        "status": "ok",
        "logs_processed": len(logs),
        "clusters": len(clusters),
        "anomalies_detected": len(anomalies),
        "alerts_sent": alerts_sent,
    }


@router.post("/logs")
async def ingest_logs(request: Request, logs: list[str] = []):
    """Ingest raw log lines."""
    parser = request.app.state.drain_parser
    results = parser.batch_parse(logs)
    return {"processed": len(results), "results": results}
