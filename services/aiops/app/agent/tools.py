"""
Agent tool definitions and registry for the AI RCA investigator.

Provides 6 tools in OpenAI Responses API format (flat structure):
  - query_metrics
  - query_logs
  - query_traces
  - get_topology
  - get_recent_changes
  - search_knowledge_base
"""

import sqlite3
from typing import Any, Callable, Optional


TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "name": "query_metrics",
        "description": "Query KPI metrics with anomaly analysis for a service in a time range",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name"},
                "metric_type": {
                    "type": "string",
                    "enum": ["cpu", "memory", "network", "disk", "latency", "error_rate", "all"],
                    "description": "Type of metric to query",
                },
                "from_time": {"type": "string", "description": "ISO timestamp start"},
                "to_time": {"type": "string", "description": "ISO timestamp end"},
            },
            "required": ["service", "metric_type", "from_time", "to_time"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "query_logs",
        "description": "Query structured log clusters for a service in a time range, with baseline deviation analysis",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name"},
                "from_time": {"type": "string", "description": "ISO timestamp start"},
                "to_time": {"type": "string", "description": "ISO timestamp end"},
            },
            "required": ["service", "from_time", "to_time"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "query_traces",
        "description": "Query distributed traces with critical-path analysis for a time range",
        "parameters": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Dataset name (e.g. Bank)"},
                "date": {"type": "string", "description": "Date folder (e.g. 2024_01_15)"},
                "from_time": {"type": "string", "description": "ISO timestamp start"},
                "to_time": {"type": "string", "description": "ISO timestamp end"},
            },
            "required": ["dataset", "date", "from_time", "to_time"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_topology",
        "description": "Retrieve the service dependency graph (nodes and edges) for a dataset",
        "parameters": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Dataset name (e.g. Bank)"},
            },
            "required": ["dataset"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_recent_changes",
        "description": "List recent deployments, config changes, and rollbacks from ground truth records",
        "parameters": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Dataset name (e.g. Bank)"},
                "date": {"type": "string", "description": "Date folder (e.g. 2024_01_15)"},
            },
            "required": ["dataset", "date"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "search_knowledge_base",
        "description": "Search past incident reports and runbooks for relevant knowledge",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language search query"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


def _error(msg: str) -> dict:
    """Return a standardised error envelope."""
    return {"error": msg}


def _make_query_metrics(openrca_adapter: Any) -> Callable:
    """Create the query_metrics callable."""

    def query_metrics(*, service: str, metric_type: str, from_time: str, to_time: str) -> dict:
        if openrca_adapter is None:
            return _error("openrca_adapter is not configured")
        metric = None if metric_type == "all" else metric_type
        time_range = {"start": from_time, "end": to_time}
        # The adapter needs dataset/date which are derived from the incident
        # context; however, because the adapter is pre-bound to its data_dir
        # we use a convention: iterate available datasets or the caller
        # pre-configures the adapter.  For now we pass generic values and
        # let the adapter resolve from its cache.
        try:
            result = openrca_adapter.load_metrics(
                dataset=getattr(openrca_adapter, "_current_dataset", ""),
                date=getattr(openrca_adapter, "_current_date", ""),
                service=service,
                metric=metric,
                time_range=time_range,
            )
            return result
        except Exception as exc:
            return _error(f"query_metrics failed: {exc}")

    return query_metrics


def _make_query_logs(db_path: Optional[str]) -> Callable:
    """Create the query_logs callable that queries the SQLite clusters table."""

    def query_logs(*, service: str, from_time: str, to_time: str) -> dict:
        if db_path is None:
            return _error("db_path is not configured")
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row

            # Fetch log entries for the service in the time window
            rows = conn.execute(
                """
                SELECT le.timestamp, le.raw_message, le.cluster_id, c.template, c.count
                FROM log_entries le
                JOIN clusters c ON le.cluster_id = c.id
                WHERE le.service = ?
                  AND le.timestamp >= ?
                  AND le.timestamp <= ?
                ORDER BY le.timestamp
                """,
                (service, from_time, to_time),
            ).fetchall()

            # Compute baseline: average count per cluster across all data
            baseline_rows = conn.execute(
                "SELECT id, count FROM clusters"
            ).fetchall()
            conn.close()

            baseline_map: dict[int, int] = {}
            total_count = 0
            for br in baseline_rows:
                baseline_map[br["id"]] = br["count"]
                total_count += br["count"]
            avg_count = total_count / len(baseline_map) if baseline_map else 1

            # Build per-cluster summary in the window
            cluster_summary: dict[int, dict] = {}
            for row in rows:
                cid = row["cluster_id"]
                if cid not in cluster_summary:
                    cluster_summary[cid] = {
                        "cluster_id": cid,
                        "template": row["template"],
                        "window_count": 0,
                        "baseline_count": baseline_map.get(cid, 0),
                        "sample_messages": [],
                    }
                cluster_summary[cid]["window_count"] += 1
                if len(cluster_summary[cid]["sample_messages"]) < 3:
                    cluster_summary[cid]["sample_messages"].append(row["raw_message"])

            # Compute deviation from baseline
            clusters_out = []
            for cs in cluster_summary.values():
                deviation = cs["window_count"] / avg_count if avg_count else 0.0
                cs["deviation_from_baseline"] = round(deviation, 4)
                clusters_out.append(cs)

            # Sort by deviation descending so the most anomalous clusters appear first
            clusters_out.sort(key=lambda x: x["deviation_from_baseline"], reverse=True)

            return {
                "service": service,
                "from_time": from_time,
                "to_time": to_time,
                "total_entries": len(rows),
                "clusters": clusters_out,
            }
        except Exception as exc:
            return _error(f"query_logs failed: {exc}")

    return query_logs


def _make_query_traces(openrca_adapter: Any) -> Callable:
    """Create the query_traces callable."""

    def query_traces(*, dataset: str, date: str, from_time: str, to_time: str) -> dict:
        if openrca_adapter is None:
            return _error("openrca_adapter is not configured")
        try:
            time_range = {"start": from_time, "end": to_time}
            result = openrca_adapter.load_traces(
                dataset=dataset,
                date=date,
                time_range=time_range,
            )
            return result
        except Exception as exc:
            return _error(f"query_traces failed: {exc}")

    return query_traces


def _make_get_topology(openrca_adapter: Any) -> Callable:
    """Create the get_topology callable."""

    def get_topology(*, dataset: str) -> dict:
        if openrca_adapter is None:
            return _error("openrca_adapter is not configured")
        try:
            result = openrca_adapter.load_topology(dataset=dataset)
            return result
        except Exception as exc:
            return _error(f"get_topology failed: {exc}")

    return get_topology


def _make_get_recent_changes(openrca_adapter: Any) -> Callable:
    """Create the get_recent_changes callable."""

    def get_recent_changes(*, dataset: str, date: str) -> dict:
        if openrca_adapter is None:
            return _error("openrca_adapter is not configured")
        try:
            result = openrca_adapter.load_ground_truth(dataset=dataset, date=date)
            return result
        except Exception as exc:
            return _error(f"get_recent_changes failed: {exc}")

    return get_recent_changes


def _make_search_knowledge_base(rag_manager: Any) -> Callable:
    """Create the search_knowledge_base callable."""

    def search_knowledge_base(*, query: str) -> dict:
        if rag_manager is None:
            return _error("rag_manager is not configured")
        try:
            results = rag_manager.search(query=query)
            return {"query": query, "results": results}
        except Exception as exc:
            return _error(f"search_knowledge_base failed: {exc}")

    return search_knowledge_base


def get_tool_registry(
    openrca_adapter: Any = None,
    db_path: Optional[str] = None,
    rag_manager: Any = None,
) -> dict[str, Callable]:
    """Build and return a dict mapping tool name -> callable.

    Each callable accepts **kwargs matching the tool's parameter schema and
    returns a dict (JSON-serialisable) with the tool's result or an error
    envelope when its backing dependency is None.
    """
    return {
        "query_metrics": _make_query_metrics(openrca_adapter),
        "query_logs": _make_query_logs(db_path),
        "query_traces": _make_query_traces(openrca_adapter),
        "get_topology": _make_get_topology(openrca_adapter),
        "get_recent_changes": _make_get_recent_changes(openrca_adapter),
        "search_knowledge_base": _make_search_knowledge_base(rag_manager),
    }
