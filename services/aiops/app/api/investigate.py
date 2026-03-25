import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from app.models import InvestigateRequest
from app.db import get_connection

router = APIRouter()


@router.post("/investigate")
async def investigate(req: InvestigateRequest, request: Request):
    """Run AI investigation on an incident."""
    from app.agent.investigator import Investigator
    from app.agent.tools import TOOL_DEFINITIONS, get_tool_registry
    from app.agent.prompts import SYSTEM_PROMPT

    settings = request.app.state.settings

    tool_registry = get_tool_registry(
        openrca_adapter=request.app.state.openrca,
        db_path=settings.SQLITE_PATH,
        rag_manager=request.app.state.rag,
    )

    investigator = Investigator(
        api_key=settings.OPENAI_API_KEY,
        model=settings.OPENAI_MODEL,
        tool_registry=tool_registry,
        tool_definitions=TOOL_DEFINITIONS,
        max_iterations=settings.AGENT_MAX_ITERATIONS,
        fallback_model=settings.OPENAI_FALLBACK_MODEL,
    )

    context = f"""Investigate incident {req.incident_id}.
Dataset: {req.dataset}, Date: {req.date}
Time range: {req.time_range or 'full period'}

Use your tools to query metrics, logs, traces, topology, and knowledge base for this dataset and date."""

    prompt = SYSTEM_PROMPT.format(incident_context=context)
    report = investigator.investigate(context, system_prompt=prompt)

    # Save report to SQLite
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO reports (incident_id, dataset, date, created_at, root_cause, causal_chain, evidence, data_coverage, quality)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                req.incident_id, req.dataset, req.date,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(report.get("root_cause", {})),
                json.dumps(report.get("causal_chain", [])),
                json.dumps(report.get("evidence", [])),
                json.dumps(report.get("data_coverage", {})),
                json.dumps(report.get("investigation_quality", {})),
            )
        )
        report_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    report["id"] = report_id
    return report


@router.get("/reports")
async def get_reports():
    """List all investigation reports."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM reports ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            for field in ["root_cause", "causal_chain", "evidence", "data_coverage", "quality"]:
                if d.get(field):
                    try:
                        d[field] = json.loads(d[field])
                    except (json.JSONDecodeError, TypeError):
                        pass
            result.append(d)
        return result


@router.get("/reports/{report_id}")
async def get_report(report_id: int):
    """Get single report detail."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            return {"error": "Report not found"}
        d = dict(row)
        for field in ["root_cause", "causal_chain", "evidence", "data_coverage", "quality"]:
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
