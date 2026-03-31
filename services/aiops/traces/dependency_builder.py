"""Dependency builder -- service DAG from trace spans."""
import pandas as pd
from collections import defaultdict
from traces.base import TraceAnalyzer, TraceResult


class DependencyBuilder(TraceAnalyzer):
    name = "dependency_builder"
    version = "1.0"

    def __init__(self):
        self._graph = {"nodes": set(), "edges": set()}

    def analyze(self, spans_df: pd.DataFrame) -> list[TraceResult]:
        """Build dependency graph from spans. Returns one TraceResult with graph in details."""
        self._graph = {"nodes": set(), "edges": set()}
        if spans_df.empty:
            return []

        service_col = "cmdb_id" if "cmdb_id" in spans_df.columns else None
        if service_col is None or "span_id" not in spans_df.columns:
            return []

        # Build span_id -> service mapping
        span_to_service = {}
        for _, row in spans_df.iterrows():
            span_to_service[str(row["span_id"])] = str(row[service_col])
            self._graph["nodes"].add(str(row[service_col]))

        # Build edges from parent-child relationships
        edge_counts = defaultdict(int)
        if "parent_id" in spans_df.columns:
            for _, row in spans_df.iterrows():
                parent_id = str(row.get("parent_id", ""))
                child_service = str(row[service_col])
                if parent_id and parent_id in span_to_service:
                    parent_service = span_to_service[parent_id]
                    if parent_service != child_service:
                        edge = (parent_service, child_service)
                        self._graph["edges"].add(edge)
                        edge_counts[edge] += 1

        return [TraceResult(
            trace_id="dependency_graph",
            is_anomalous=False,
            bottleneck_service="",
            analyzer_name=self.name,
            details={
                "nodes": sorted(self._graph["nodes"]),
                "edges": [{"source": s, "target": t, "call_count": edge_counts[(s, t)]}
                          for s, t in sorted(self._graph["edges"])],
                "node_count": len(self._graph["nodes"]),
                "edge_count": len(self._graph["edges"]),
            },
        )]

    def get_graph(self) -> dict:
        return {
            "nodes": sorted(self._graph["nodes"]),
            "edges": [{"source": s, "target": t} for s, t in sorted(self._graph["edges"])],
        }

    def reset(self) -> None:
        self._graph = {"nodes": set(), "edges": set()}
