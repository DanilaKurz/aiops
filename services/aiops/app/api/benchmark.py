import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from pydantic import BaseModel
from app.db import get_connection

router = APIRouter()


class BenchmarkRequest(BaseModel):
    dataset: str
    dates: list[str]


@router.post("/run")
async def run_benchmark(req: BenchmarkRequest, request: Request):
    """Run full benchmark: ingest -> drain -> anomaly -> investigate -> compare with ground truth."""
    from app.api.ingest import ingest_openrca
    from app.models import IngestRequest, InvestigateRequest
    from app.api.investigate import investigate as run_investigate

    results = []

    for date in req.dates:
        # 1. Ingest
        ingest_req = IngestRequest(dataset=req.dataset, date=date)
        await ingest_openrca(ingest_req, request)

        # 2. Investigate
        inv_req = InvestigateRequest(
            incident_id=f"bench-{req.dataset}-{date}",
            dataset=req.dataset,
            date=date,
        )
        report = await run_investigate(inv_req, request)

        # 3. Compare with ground truth
        adapter = request.app.state.openrca
        gt = adapter.load_ground_truth(req.dataset, date)

        predicted = report.get("root_cause", {}).get("component", "unknown")
        actual = gt.get("component", "unknown")
        correct = predicted.lower() == actual.lower()

        # Update report with correctness
        if report.get("id"):
            with get_connection() as conn:
                conn.execute(
                    "UPDATE reports SET correct = ? WHERE id = ?",
                    (1 if correct else 0, report["id"])
                )

        results.append({
            "date": date,
            "predicted": predicted,
            "actual": actual,
            "correct": correct,
            "confidence": report.get("root_cause", {}).get("confidence", 0),
            "tool_calls": report.get("investigation_quality", {}).get("total_tool_calls", 0),
        })

    correct_count = sum(1 for r in results if r["correct"])
    total = len(results)

    return {
        "total_incidents": total,
        "correct_root_cause": correct_count,
        "accuracy": round(correct_count / max(total, 1), 4),
        "baseline_openrca": 0.1134,
        "per_incident": results,
    }


@router.get("/results")
async def get_benchmark_results():
    """Get latest benchmark results from reports table."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM reports WHERE correct IS NOT NULL ORDER BY created_at DESC"
        ).fetchall()

    if not rows:
        return {"total_incidents": 0, "correct_root_cause": 0, "accuracy": 0, "baseline_openrca": 0.1134, "per_incident": []}

    results = []
    for row in rows:
        d = dict(row)
        root_cause = json.loads(d["root_cause"]) if d.get("root_cause") else {}
        quality = json.loads(d["quality"]) if d.get("quality") else {}
        results.append({
            "date": d.get("date", ""),
            "predicted": root_cause.get("component", "unknown"),
            "correct": d["correct"] == 1,
            "confidence": root_cause.get("confidence", 0),
            "tool_calls": quality.get("total_tool_calls", 0),
        })

    correct_count = sum(1 for r in results if r["correct"])
    return {
        "total_incidents": len(results),
        "correct_root_cause": correct_count,
        "accuracy": round(correct_count / max(len(results), 1), 4),
        "baseline_openrca": 0.1134,
        "per_incident": results,
    }
