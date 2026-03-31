"""Critical path -- find longest path through trace spans."""
import pandas as pd
from collections import defaultdict
from traces.base import TraceAnalyzer, TraceResult


class CriticalPathAnalyzer(TraceAnalyzer):
    name = "critical_path"
    version = "1.0"

    def analyze(self, spans_df: pd.DataFrame) -> list[TraceResult]:
        results = []
        if spans_df.empty or "trace_id" not in spans_df.columns:
            return results

        service_col = "cmdb_id" if "cmdb_id" in spans_df.columns else None
        if service_col is None:
            return results

        for trace_id, trace_df in spans_df.groupby("trace_id"):
            # Build span tree: parent_id -> [child spans]
            children = defaultdict(list)
            span_info = {}
            roots = []

            for _, row in trace_df.iterrows():
                sid = str(row["span_id"])
                pid = str(row.get("parent_id", ""))
                svc = str(row[service_col])
                dur = float(row.get("duration", 0))
                span_info[sid] = {"service": svc, "duration": dur, "span_id": sid}
                if pid and pid != "" and pid != "nan":
                    children[pid].append(sid)
                else:
                    roots.append(sid)

            if not roots:
                # No root found, use first span
                roots = [str(trace_df.iloc[0]["span_id"])]

            # DFS to find longest path (by total duration)
            best_path = []
            best_duration = 0

            def dfs(span_id, current_path, current_duration):
                nonlocal best_path, best_duration
                info = span_info.get(span_id, {})
                svc = info.get("service", "?")
                dur = info.get("duration", 0)
                new_path = current_path + [svc]
                new_duration = current_duration + dur

                child_spans = children.get(span_id, [])
                if not child_spans:
                    if new_duration > best_duration:
                        best_duration = new_duration
                        best_path = new_path
                else:
                    for child in child_spans:
                        dfs(child, new_path, new_duration)

            for root in roots:
                dfs(root, [], 0)

            # Find bottleneck (service with max duration on critical path)
            svc_durations = defaultdict(float)
            for _, row in trace_df.iterrows():
                svc = str(row[service_col])
                svc_durations[svc] += float(row.get("duration", 0))
            bottleneck = max(svc_durations, key=svc_durations.get) if svc_durations else ""

            results.append(TraceResult(
                trace_id=str(trace_id),
                is_anomalous=False,  # critical path itself is not anomaly detection
                bottleneck_service=bottleneck,
                critical_path=best_path,
                latency_ms=best_duration,
                normal_latency_ms=0,
                analyzer_name=self.name,
                details={
                    "path_length": len(best_path),
                    "service_durations": dict(svc_durations),
                },
            ))
        return results

    def reset(self) -> None:
        pass
