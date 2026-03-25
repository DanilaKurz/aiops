import os
from typing import Optional

import pandas as pd

from app.models import LogEntry


class OpenRCAAdapter:
    """Reads OpenRCA dataset CSV files with caching."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._cache: dict = {}

    def _read_csv(self, path: str, cache_key: tuple) -> pd.DataFrame:
        """Read a CSV file with caching."""
        if cache_key not in self._cache:
            self._cache[cache_key] = pd.read_csv(path)
        return self._cache[cache_key]

    def _base_path(self, dataset: str, date: str) -> str:
        return os.path.join(self.data_dir, dataset, date)

    def load_logs(self, dataset: str, date: str, service: Optional[str] = None) -> list:
        """Read log/*.csv files, return List[LogEntry]."""
        log_dir = os.path.join(self._base_path(dataset, date), "log")
        entries: list = []

        if not os.path.isdir(log_dir):
            return entries

        csv_files = [f for f in os.listdir(log_dir) if f.endswith(".csv")]

        for csv_file in sorted(csv_files):
            svc_name = csv_file.replace(".csv", "")
            if service is not None and svc_name != service:
                continue

            cache_key = (dataset, date, "log", svc_name)
            filepath = os.path.join(log_dir, csv_file)
            df = self._read_csv(filepath, cache_key)

            for _, row in df.iterrows():
                entries.append(
                    LogEntry(
                        timestamp=str(row["timestamp"]),
                        service=svc_name,
                        message=str(row["message"]),
                    )
                )

        return entries

    def load_metrics(
        self,
        dataset: str,
        date: str,
        service: str,
        metric: Optional[str] = None,
        time_range: Optional[dict] = None,
    ) -> dict:
        """Read metric/*.csv, compute baseline + deviation.

        Returns: {service, anomalies: [...], normal_metrics: [...], earliest_anomaly: str}
        Baseline = mean of all values per metric. Anomaly if value > 2x baseline.
        """
        metric_dir = os.path.join(self._base_path(dataset, date), "metric")
        filepath = os.path.join(metric_dir, f"{service}.csv")

        if not os.path.isfile(filepath):
            return {
                "service": service,
                "anomalies": [],
                "normal_metrics": [],
                "earliest_anomaly": None,
            }

        cache_key = (dataset, date, "metric", service)
        df = self._read_csv(filepath, cache_key)

        if metric is not None:
            df = df[df["metric_name"] == metric]

        if time_range is not None:
            start = time_range.get("start")
            end = time_range.get("end")
            if start:
                df = df[df["timestamp"] >= start]
            if end:
                df = df[df["timestamp"] <= end]

        anomalies = []
        normal_metrics = []
        earliest_anomaly = None

        for metric_name, group in df.groupby("metric_name"):
            values = group["value"].astype(float)
            baseline = values.mean()

            for _, row in group.iterrows():
                val = float(row["value"])
                deviation = val / baseline if baseline != 0 else 0.0
                entry = {
                    "metric": metric_name,
                    "value": val,
                    "baseline": round(baseline, 4),
                    "deviation": round(deviation, 4),
                    "timestamp": str(row["timestamp"]),
                }

                if val > 2 * baseline:
                    entry["onset"] = str(row["timestamp"])
                    anomalies.append(entry)
                    if earliest_anomaly is None or str(row["timestamp"]) < earliest_anomaly:
                        earliest_anomaly = str(row["timestamp"])
                else:
                    normal_metrics.append(entry)

        return {
            "service": service,
            "anomalies": anomalies,
            "normal_metrics": normal_metrics,
            "earliest_anomaly": earliest_anomaly,
        }

    def load_traces(self, dataset: str, date: str, time_range: Optional[dict] = None) -> dict:
        """Read trace/*.csv, build critical path.

        Returns: {critical_path: [...], bottleneck: str,
                  anomalous_spans_count: int, total_spans_analyzed: int}
        """
        trace_dir = os.path.join(self._base_path(dataset, date), "trace")

        if not os.path.isdir(trace_dir):
            return {
                "critical_path": [],
                "bottleneck": None,
                "anomalous_spans_count": 0,
                "total_spans_analyzed": 0,
            }

        all_dfs = []
        csv_files = [f for f in os.listdir(trace_dir) if f.endswith(".csv")]

        for csv_file in sorted(csv_files):
            cache_key = (dataset, date, "trace", csv_file)
            filepath = os.path.join(trace_dir, csv_file)
            df = self._read_csv(filepath, cache_key)
            all_dfs.append(df)

        if not all_dfs:
            return {
                "critical_path": [],
                "bottleneck": None,
                "anomalous_spans_count": 0,
                "total_spans_analyzed": 0,
            }

        df = pd.concat(all_dfs, ignore_index=True)
        total_spans = len(df)

        # Count anomalous spans (non-ok status)
        anomalous_spans = len(df[df["status"] != "ok"]) if "status" in df.columns else 0

        # Build critical path: find root spans and follow the chain
        # Root span has empty/NaN parent_span_id
        root_spans = df[df["parent_span_id"].isna() | (df["parent_span_id"] == "")]

        critical_path = []
        bottleneck_service = None
        max_duration = -1

        if not root_spans.empty:
            # Take the first root span and build the chain
            root = root_spans.iloc[0]
            span_map = {}
            children_map = {}

            for _, row in df.iterrows():
                span_id = str(row["span_id"])
                span_map[span_id] = row
                parent = str(row["parent_span_id"]) if pd.notna(row["parent_span_id"]) and row["parent_span_id"] != "" else None
                if parent:
                    if parent not in children_map:
                        children_map[parent] = []
                    children_map[parent].append(span_id)

            # Walk the chain from root
            current_span_id = str(root["span_id"])
            visited = set()

            while current_span_id and current_span_id not in visited:
                visited.add(current_span_id)
                if current_span_id not in span_map:
                    break
                span = span_map[current_span_id]
                duration = float(span["duration_ms"])
                path_entry = {
                    "service": str(span["service"]),
                    "duration_ms": duration,
                    "baseline_ms": duration,
                    "status": str(span["status"]),
                }
                critical_path.append(path_entry)

                if duration > max_duration:
                    max_duration = duration
                    bottleneck_service = str(span["service"])

                # Move to child with longest duration
                child_ids = children_map.get(current_span_id, [])
                if child_ids:
                    best_child = None
                    best_dur = -1
                    for cid in child_ids:
                        if cid in span_map:
                            d = float(span_map[cid]["duration_ms"])
                            if d > best_dur:
                                best_dur = d
                                best_child = cid
                    current_span_id = best_child
                else:
                    break

        # Compute exclusive time (own - max child) to find real bottleneck
        if len(critical_path) > 1:
            bottleneck_service = None
            max_exclusive = -1
            for i, entry in enumerate(critical_path):
                child_duration = critical_path[i + 1]["duration_ms"] if i + 1 < len(critical_path) else 0
                exclusive = entry["duration_ms"] - child_duration
                if exclusive > max_exclusive:
                    max_exclusive = exclusive
                    bottleneck_service = entry["service"]

        return {
            "critical_path": critical_path,
            "bottleneck": bottleneck_service,
            "anomalous_spans_count": anomalous_spans,
            "total_spans_analyzed": total_spans,
        }

    def load_topology(self, dataset: str) -> dict:
        """Parse traces to build service dependency graph.

        Returns: {nodes: [service_names], edges: [{source, target}]}
        """
        nodes = set()
        edges = set()

        dataset_dir = os.path.join(self.data_dir, dataset)
        if not os.path.isdir(dataset_dir):
            return {"nodes": [], "edges": []}

        # Scan all date directories for traces
        for date_dir in sorted(os.listdir(dataset_dir)):
            trace_dir = os.path.join(dataset_dir, date_dir, "trace")
            if not os.path.isdir(trace_dir):
                continue

            csv_files = [f for f in os.listdir(trace_dir) if f.endswith(".csv")]
            for csv_file in csv_files:
                cache_key = (dataset, date_dir, "trace", csv_file)
                filepath = os.path.join(trace_dir, csv_file)
                df = self._read_csv(filepath, cache_key)

                # Build span_id -> service map
                span_service = {}
                for _, row in df.iterrows():
                    svc = str(row["service"])
                    nodes.add(svc)
                    span_service[str(row["span_id"])] = svc

                # Build edges from parent->child relationships
                for _, row in df.iterrows():
                    parent_id = row.get("parent_span_id")
                    if pd.notna(parent_id) and str(parent_id) != "":
                        parent_svc = span_service.get(str(parent_id))
                        child_svc = str(row["service"])
                        if parent_svc and parent_svc != child_svc:
                            edges.add((parent_svc, child_svc))

        return {
            "nodes": sorted(list(nodes)),
            "edges": [{"source": s, "target": t} for s, t in sorted(edges)],
        }

    def load_ground_truth(self, dataset: str, date: str) -> dict:
        """Read record.csv, return {root_cause, component, description}."""
        filepath = os.path.join(self._base_path(dataset, date), "record.csv")

        cache_key = (dataset, date, "ground_truth")
        df = self._read_csv(filepath, cache_key)

        if df.empty:
            return {"root_cause": None, "component": None, "description": None}

        row = df.iloc[0]
        return {
            "root_cause": str(row["root_cause"]),
            "component": str(row["component"]),
            "description": str(row["description"]),
        }
