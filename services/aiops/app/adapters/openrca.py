import os
import glob as glob_mod
from datetime import datetime, timezone, timedelta
from typing import Optional, Callable

import pandas as pd

from app.models import LogEntry


class OpenRCAAdapter:
    """Reads OpenRCA dataset CSV files with chunked reading and caching."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._cache: dict = {}

    def _base_path(self, dataset: str, date: str) -> str:
        return os.path.join(self.data_dir, dataset, "telemetry", date)

    def _read_csv(self, path: str, cache_key: tuple) -> pd.DataFrame:
        """Read a small CSV file with caching."""
        if cache_key not in self._cache:
            self._cache[cache_key] = pd.read_csv(path)
        return self._cache[cache_key]

    def _read_csv_filtered(
        self, path: str, cache_key: tuple,
        usecols: Optional[list] = None,
        filter_fn: Optional[Callable] = None,
        chunksize: int = 50_000,
    ) -> pd.DataFrame:
        """Read a large CSV with chunked filtering and caching."""
        if cache_key in self._cache:
            return self._cache[cache_key]

        chunks = []
        for chunk in pd.read_csv(path, chunksize=chunksize, usecols=usecols):
            if filter_fn is not None:
                chunk = filter_fn(chunk)
            if not chunk.empty:
                chunks.append(chunk)

        result = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
        self._cache[cache_key] = result
        return result

    def _date_to_timestamp(self, date: str, hour: int = 0) -> int:
        """Convert date string 'YYYY_MM_DD' + hour to unix timestamp.

        Uses UTC+8 (CST) to match the Bank dataset convention where
        '2021_03_04' midnight corresponds to unix 1614787200.
        """
        parts = date.split("_")
        cst = timezone(timedelta(hours=8))
        dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]),
                      hour=hour, tzinfo=cst)
        return int(dt.timestamp())

    def load_logs(self, dataset: str, date: str,
                  service: Optional[str] = None,
                  hour: Optional[int] = None) -> list:
        """Read log/log_service.csv, return List[LogEntry]."""
        log_path = os.path.join(self._base_path(dataset, date), "log", "log_service.csv")
        if not os.path.isfile(log_path):
            return []

        def make_filter(svc, hr):
            def fn(chunk):
                mask = pd.Series(True, index=chunk.index)
                if svc is not None:
                    mask &= chunk["cmdb_id"] == svc
                if hr is not None:
                    ts_start = self._date_to_timestamp(date, hr)
                    ts_end = ts_start + 3600
                    mask &= (chunk["timestamp"] >= ts_start) & (chunk["timestamp"] < ts_end)
                return chunk[mask]
            return fn

        cache_key = (dataset, date, "log", service, hour)
        df = self._read_csv_filtered(
            log_path, cache_key,
            usecols=["timestamp", "cmdb_id", "log_name", "value"],
            filter_fn=make_filter(service, hour),
        )

        entries = []
        for _, row in df.iterrows():
            entries.append(LogEntry(
                timestamp=str(row["timestamp"]),
                service=str(row["cmdb_id"]),
                message=str(row["value"]),
            ))
        return entries

    def load_metrics(self, dataset: str, date: str,
                     service: Optional[str] = None,
                     metric: Optional[str] = None,
                     time_range: Optional[dict] = None,
                     hour: Optional[int] = None) -> dict:
        """Read all metric_*.csv, normalize to long format, compute anomalies."""
        metric_dir = os.path.join(self._base_path(dataset, date), "metric")
        if not os.path.isdir(metric_dir):
            return {"service": service, "anomalies": [], "normal_metrics": [], "earliest_anomaly": None}

        cache_key = (dataset, date, "metrics_all", service, metric, hour)
        if cache_key in self._cache:
            df = self._cache[cache_key]
        else:
            all_dfs = []
            for fpath in sorted(glob_mod.glob(os.path.join(metric_dir, "metric_*.csv"))):
                temp_df = pd.read_csv(fpath)

                # Normalize to long format: timestamp, cmdb_id, kpi_name, value
                if "kpi_name" in temp_df.columns and "cmdb_id" in temp_df.columns:
                    # Already long format (metric_container, metric_node, etc.)
                    norm = temp_df[["timestamp", "cmdb_id", "kpi_name", "value"]].copy()
                elif "tc" in temp_df.columns:
                    # Wide format (metric_app): melt rr, sr, cnt, mrt
                    value_cols = [c for c in temp_df.columns if c not in ("timestamp", "tc")]
                    norm = temp_df.melt(
                        id_vars=["timestamp", "tc"],
                        value_vars=value_cols,
                        var_name="kpi_name", value_name="value"
                    )
                    norm.rename(columns={"tc": "cmdb_id"}, inplace=True)
                else:
                    continue  # unknown format, skip

                all_dfs.append(norm)

            if not all_dfs:
                return {"service": service, "anomalies": [], "normal_metrics": [], "earliest_anomaly": None}

            df = pd.concat(all_dfs, ignore_index=True)

            # Apply filters
            if service is not None:
                df = df[df["cmdb_id"] == service]
            if metric is not None:
                df = df[df["kpi_name"] == metric]
            if hour is not None:
                ts_start = self._date_to_timestamp(date, hour)
                ts_end = ts_start + 3600
                df = df[(df["timestamp"] >= ts_start) & (df["timestamp"] < ts_end)]

            self._cache[cache_key] = df

        # Compute baseline + anomalies
        anomalies = []
        normal_metrics = []
        earliest_anomaly = None

        for (cmdb, kpi), group in df.groupby(["cmdb_id", "kpi_name"]):
            values = group["value"].astype(float)
            baseline = values.mean()
            if baseline == 0:
                continue

            max_val = values.max()
            max_row = group.loc[values.idxmax()]
            deviation = max_val / baseline

            entry = {
                "metric": kpi,
                "service": cmdb,
                "value": round(float(max_val), 4),
                "baseline": round(float(baseline), 4),
                "deviation": f"{deviation:.1f}x",
                "onset": str(int(max_row["timestamp"])),
            }

            if deviation > 2.0:
                anomalies.append(entry)
                ts_str = str(int(max_row["timestamp"]))
                if earliest_anomaly is None or ts_str < earliest_anomaly:
                    earliest_anomaly = ts_str
            else:
                normal_metrics.append(entry)

        anomalies.sort(key=lambda x: float(x["deviation"].rstrip("x")), reverse=True)

        return {
            "service": service or "all",
            "anomalies": anomalies,
            "normal_metrics": normal_metrics,
            "earliest_anomaly": earliest_anomaly,
        }

    def load_traces(self, dataset: str, date: str,
                    time_range: Optional[dict] = None,
                    hour: Optional[int] = None) -> dict:
        """Read trace/trace_span.csv, build critical path."""
        trace_path = os.path.join(self._base_path(dataset, date), "trace", "trace_span.csv")
        if not os.path.isfile(trace_path):
            return {"critical_path": [], "bottleneck": None, "anomalous_spans_count": 0, "total_spans_analyzed": 0}

        def make_filter(hr):
            def fn(chunk):
                if hr is not None:
                    ts_start = self._date_to_timestamp(date, hr) * 1000  # traces use ms
                    ts_end = ts_start + 3600_000
                    return chunk[(chunk["timestamp"] >= ts_start) & (chunk["timestamp"] < ts_end)]
                return chunk
            return fn

        cache_key = (dataset, date, "trace", hour)
        df = self._read_csv_filtered(
            trace_path, cache_key,
            filter_fn=make_filter(hour),
        )

        if df.empty:
            return {"critical_path": [], "bottleneck": None, "anomalous_spans_count": 0, "total_spans_analyzed": 0}

        total_spans = len(df)

        # Rename columns to internal format
        df = df.rename(columns={
            "cmdb_id": "service",
            "parent_id": "parent_span_id",
            "duration": "duration_ms",
        })

        # Find root spans (empty parent)
        root_spans = df[df["parent_span_id"].isna() | (df["parent_span_id"] == "")]

        critical_path = []
        bottleneck_service = None

        if not root_spans.empty:
            # Take the longest root span
            root = root_spans.loc[root_spans["duration_ms"].idxmax()]

            # Build maps
            span_map = {}
            children_map = {}
            for _, row in df.iterrows():
                sid = str(row["span_id"])
                span_map[sid] = row
                pid = str(row["parent_span_id"]) if pd.notna(row["parent_span_id"]) and row["parent_span_id"] != "" else None
                if pid:
                    children_map.setdefault(pid, []).append(sid)

            # Walk critical path
            current = str(root["span_id"])
            visited = set()
            while current and current not in visited:
                visited.add(current)
                if current not in span_map:
                    break
                span = span_map[current]
                critical_path.append({
                    "service": str(span["service"]),
                    "duration_ms": float(span["duration_ms"]),
                    "status": "ok",
                })
                # Follow longest child
                children = children_map.get(current, [])
                if children:
                    best = max(children, key=lambda c: float(span_map[c]["duration_ms"]) if c in span_map else 0)
                    current = best
                else:
                    break

            # Bottleneck by exclusive time
            if len(critical_path) > 1:
                max_exclusive = -1
                for i, entry in enumerate(critical_path):
                    child_dur = critical_path[i + 1]["duration_ms"] if i + 1 < len(critical_path) else 0
                    exclusive = entry["duration_ms"] - child_dur
                    if exclusive > max_exclusive:
                        max_exclusive = exclusive
                        bottleneck_service = entry["service"]
            elif len(critical_path) == 1:
                bottleneck_service = critical_path[0]["service"]

        return {
            "critical_path": critical_path,
            "bottleneck": bottleneck_service,
            "anomalous_spans_count": 0,
            "total_spans_analyzed": total_spans,
        }

    def load_topology(self, dataset: str) -> dict:
        """Build service dependency graph from traces."""
        nodes = set()
        edges = set()

        dataset_dir = os.path.join(self.data_dir, dataset, "telemetry")
        if not os.path.isdir(dataset_dir):
            return {"nodes": [], "edges": []}

        for date_dir in sorted(os.listdir(dataset_dir)):
            trace_path = os.path.join(dataset_dir, date_dir, "trace", "trace_span.csv")
            if not os.path.isfile(trace_path):
                continue

            # Read only needed columns, sample first 100k rows for topology
            try:
                df = pd.read_csv(trace_path, usecols=["cmdb_id", "parent_id", "span_id"], nrows=100_000)
            except Exception:
                continue

            span_service = {}
            for _, row in df.iterrows():
                svc = str(row["cmdb_id"])
                nodes.add(svc)
                span_service[str(row["span_id"])] = svc

            for _, row in df.iterrows():
                pid = row.get("parent_id")
                if pd.notna(pid) and str(pid) != "":
                    parent_svc = span_service.get(str(pid))
                    child_svc = str(row["cmdb_id"])
                    if parent_svc and parent_svc != child_svc:
                        edges.add((parent_svc, child_svc))

            break  # one date is enough for topology

        return {
            "nodes": sorted(list(nodes)),
            "edges": [{"source": s, "target": t} for s, t in sorted(edges)],
        }

    def load_ground_truth(self, dataset: str, date: str) -> dict:
        """Read record.csv from dataset root, filter by date."""
        filepath = os.path.join(self.data_dir, dataset, "record.csv")
        if not os.path.isfile(filepath):
            return {"root_cause": None, "component": None, "description": None}

        cache_key = (dataset, "record")
        df = self._read_csv(filepath, cache_key)

        # Filter by date
        date_str = date.replace("_", "-")  # "2021_03_04" -> "2021-03-04"
        if "datetime" in df.columns:
            mask = df["datetime"].str.startswith(date_str)
            filtered = df[mask]
        else:
            filtered = df

        if filtered.empty:
            return {"root_cause": None, "component": None, "description": None}

        # Return first incident for this date
        row = filtered.iloc[0]
        return {
            "root_cause": str(row.get("reason", "")),
            "component": str(row.get("component", "")),
            "description": str(row.get("reason", "")),
            "level": str(row.get("level", "")),
            "timestamp": str(row.get("timestamp", "")),
            "datetime": str(row.get("datetime", "")),
        }

    def load_ground_truth_all(self, dataset: str, date: str) -> list:
        """Load ALL incidents for a given date."""
        filepath = os.path.join(self.data_dir, dataset, "record.csv")
        if not os.path.isfile(filepath):
            return []

        cache_key = (dataset, "record")
        df = self._read_csv(filepath, cache_key)

        date_str = date.replace("_", "-")
        if "datetime" in df.columns:
            mask = df["datetime"].str.startswith(date_str)
            filtered = df[mask]
        else:
            filtered = df

        return [
            {
                "root_cause": str(row.get("reason", "")),
                "component": str(row.get("component", "")),
                "description": str(row.get("reason", "")),
                "level": str(row.get("level", "")),
                "timestamp": str(row.get("timestamp", "")),
                "datetime": str(row.get("datetime", "")),
            }
            for _, row in filtered.iterrows()
        ]

    def load_queries(self, dataset: str) -> pd.DataFrame:
        """Read query.csv for benchmark evaluation."""
        filepath = os.path.join(self.data_dir, dataset, "query.csv")
        if not os.path.isfile(filepath):
            return pd.DataFrame()
        cache_key = (dataset, "queries")
        return self._read_csv(filepath, cache_key)
