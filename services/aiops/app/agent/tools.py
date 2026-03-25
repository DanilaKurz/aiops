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

from typing import Any, Callable, Optional


TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "name": "query_metrics",
        "description": "Query KPI metrics with anomaly analysis. Returns anomalous and normal metrics with deviations from baseline.",
        "parameters": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Dataset name (e.g. Bank)"},
                "date": {"type": "string", "description": "Date folder (e.g. 2021_03_04)"},
                "service": {"type": ["string", "null"], "description": "Service/component name to filter (null for all)"},
                "hour": {"type": ["integer", "null"], "description": "Hour 0-23 to filter (null for full day)"},
            },
            "required": ["dataset", "date", "service", "hour"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "query_logs",
        "description": "Query log patterns for a service. Returns Drain-extracted templates with frequency counts.",
        "parameters": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Dataset name"},
                "date": {"type": "string", "description": "Date folder"},
                "service": {"type": ["string", "null"], "description": "Service name to filter"},
                "hour": {"type": ["integer", "null"], "description": "Hour 0-23 to filter"},
            },
            "required": ["dataset", "date", "service", "hour"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "query_traces",
        "description": "Get distributed trace analysis showing request flow, critical path, and bottleneck service",
        "parameters": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Dataset name"},
                "date": {"type": "string", "description": "Date folder"},
                "hour": {"type": ["integer", "null"], "description": "Hour 0-23 to filter"},
            },
            "required": ["dataset", "date", "hour"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_topology",
        "description": "Get service dependency graph showing which components communicate",
        "parameters": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Dataset name"},
            },
            "required": ["dataset"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_recent_changes",
        "description": "Get known incidents and changes for a date. Returns ground truth failure records.",
        "parameters": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Dataset name"},
                "date": {"type": "string", "description": "Date folder"},
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

    def query_metrics(*, dataset: str, date: str, service: str = None, hour: int = None) -> dict:
        if openrca_adapter is None:
            return _error("openrca_adapter is not configured")
        try:
            return openrca_adapter.load_metrics(
                dataset=dataset, date=date, service=service, hour=hour
            )
        except Exception as exc:
            return _error(f"query_metrics failed: {exc}")

    return query_metrics


def _make_query_logs(openrca_adapter: Any) -> Callable:
    """Query logs through the adapter, group by content patterns."""

    def query_logs(*, dataset: str, date: str, service: str = None, hour: int = None) -> dict:
        if openrca_adapter is None:
            return _error("openrca_adapter is not configured")
        try:
            logs = openrca_adapter.load_logs(dataset=dataset, date=date, service=service, hour=hour)
            # Group by service and count
            service_counts: dict[str, dict] = {}
            total = len(logs)
            for log in logs:
                svc = log.service
                if svc not in service_counts:
                    service_counts[svc] = {"count": 0, "samples": []}
                service_counts[svc]["count"] += 1
                if len(service_counts[svc]["samples"]) < 3:
                    service_counts[svc]["samples"].append(log.message[:150])

            return {
                "total_logs": total,
                "services": service_counts,
                "note": "Logs are GC (garbage collection) entries. Look for Full GC, Allocation Failure, OOM patterns."
            }
        except Exception as exc:
            return _error(f"query_logs failed: {exc}")

    return query_logs


def _make_query_traces(openrca_adapter: Any) -> Callable:
    """Create the query_traces callable."""

    def query_traces(*, dataset: str, date: str, hour: int = None) -> dict:
        if openrca_adapter is None:
            return _error("openrca_adapter is not configured")
        try:
            return openrca_adapter.load_traces(dataset=dataset, date=date, hour=hour)
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
        "query_logs": _make_query_logs(openrca_adapter),
        "query_traces": _make_query_traces(openrca_adapter),
        "get_topology": _make_get_topology(openrca_adapter),
        "get_recent_changes": _make_get_recent_changes(openrca_adapter),
        "search_knowledge_base": _make_search_knowledge_base(rag_manager),
    }
