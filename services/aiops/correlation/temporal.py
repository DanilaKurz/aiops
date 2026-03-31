"""Temporal correlator -- group anomalies by time co-occurrence."""
from collections import defaultdict
from correlation.base import Correlator, Incident


class TemporalCorrelator(Correlator):
    name = "temporal"
    version = "1.0"

    def __init__(self, window_seconds: int = 300):
        self._window = window_seconds

    def correlate(self, log_anomalies: list, metric_anomalies: list,
                  trace_anomalies: list, topology: dict) -> list[Incident]:
        events = []
        for a in metric_anomalies:
            ts = self._parse_ts(a.get("timestamp", a.timestamp if hasattr(a, "timestamp") else "0"))
            comp = a.get("component", a.component if hasattr(a, "component") else "")
            events.append({"ts": ts, "component": comp, "source": "metrics", "data": a})
        for a in log_anomalies:
            ts = self._parse_ts(a.get("timestamp", "0") if isinstance(a, dict) else "0")
            comp = a.get("component", "") if isinstance(a, dict) else ""
            events.append({"ts": ts, "component": comp, "source": "logs", "data": a})
        for a in trace_anomalies:
            ts = 0
            comp = a.get("bottleneck_service", a.bottleneck_service if hasattr(a, "bottleneck_service") else "")
            events.append({"ts": ts, "component": comp, "source": "traces", "data": a})

        if not events:
            return []

        events.sort(key=lambda e: e["ts"])

        clusters = []
        current_cluster = [events[0]]
        for e in events[1:]:
            if e["ts"] - current_cluster[0]["ts"] <= self._window:
                current_cluster.append(e)
            else:
                clusters.append(current_cluster)
                current_cluster = [e]
        clusters.append(current_cluster)

        incidents = []
        for cluster in clusters:
            if len(cluster) < 1:
                continue
            components = list(set(e["component"] for e in cluster if e["component"]))
            signals = defaultdict(list)
            for e in cluster:
                signals[e["source"]].append(e["component"])

            severity = "critical" if len(components) >= 3 else "warning" if len(components) >= 2 else "info"
            onset = str(cluster[0]["ts"])

            incidents.append(Incident(
                severity=severity,
                components=components,
                root_cause_candidate=components[0] if components else "",
                onset=onset,
                signals=dict(signals),
                confidence=min(1.0, len(cluster) / 5),
                correlator_name=self.name,
                details={"window_seconds": self._window, "event_count": len(cluster)},
            ))
        return incidents

    def _parse_ts(self, ts_str) -> float:
        try:
            return float(ts_str)
        except (ValueError, TypeError):
            return 0.0

    def reset(self) -> None:
        pass
