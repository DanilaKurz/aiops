"""Infrastructure Anomaly Detector -- aggregated per-component anomalies with cross-hour baseline."""
from dataclasses import dataclass
from typing import Optional
from collections import defaultdict


@dataclass
class InfraAlert:
    component: str
    severity: str  # "critical" | "warning" | "info"
    anomalous_kpi_count: int
    top_kpis: list  # [{kpi, value, baseline, deviation}]
    onset_timestamp: int
    description: str


class InfraDetector:
    """Detects infrastructure anomalies with proper baseline and aggregation.

    Key differences from old AnomalyDetector:
    - Cross-hour baseline (previous hours, not same hour)
    - Aggregates per component (1 alert per component, not per KPI)
    - Absolute thresholds for known critical metrics
    - Minimum KPI count to trigger (reduces noise)
    """

    ABSOLUTE_THRESHOLDS = {
        "cpu": {
            "patterns": ["cpu_used", "cpuutil", "cpupercent", "cpu_usage", "cpu_pct",
                         "cpucpuutil", "cpu_user", "cpu_system"],
            "critical": 90, "warning": 80,
        },
        "memory": {
            "patterns": ["mem_used", "mempercent", "memusedmemperc", "memory_usage",
                         "mem_pct", "memused"],
            "critical": 95, "warning": 85,
        },
        "disk": {
            "patterns": ["dskpercentbusy", "disk_pct_usage", "io_time", "dskbusy"],
            "critical": 90, "warning": 80,
        },
    }

    def __init__(self, deviation_threshold=5.0, min_anomalous_kpis=3):
        self.deviation_threshold = deviation_threshold
        self.min_anomalous_kpis = min_anomalous_kpis

    def analyze(self, adapter, dataset: str, date: str, hour: int,
                baseline_hours: Optional[list[int]] = None) -> list[InfraAlert]:
        if baseline_hours is None:
            baseline_hours = [h for h in range(max(0, hour - 3), hour)]

        # Load current hour
        current = adapter.load_metrics(dataset, date, hour=hour)
        all_current = current.get("anomalies", []) + current.get("normal_metrics", [])
        if not all_current:
            return []

        # Build baseline from previous hours
        baseline_data = defaultdict(list)
        for bh in baseline_hours:
            bm = adapter.load_metrics(dataset, date, hour=bh)
            for item in bm.get("anomalies", []) + bm.get("normal_metrics", []):
                baseline_data[(item["service"], item["metric"])].append(item["value"])

        baseline_means = {}
        for key, values in baseline_data.items():
            baseline_means[key] = sum(values) / len(values) if values else 0

        # Find anomalies per component
        component_anomalies = defaultdict(list)
        for item in all_current:
            comp = item["service"]
            kpi = item["metric"]
            value = item["value"]
            key = (comp, kpi)

            baseline = baseline_means.get(key, item.get("baseline", 0))
            if baseline == 0:
                continue

            deviation = value / baseline

            # Check absolute thresholds
            is_absolute = False
            kpi_lower = kpi.lower()
            for config in self.ABSOLUTE_THRESHOLDS.values():
                if any(p in kpi_lower for p in config["patterns"]):
                    if value >= config["critical"]:
                        is_absolute = True
                    break

            if is_absolute or deviation >= self.deviation_threshold:
                component_anomalies[comp].append({
                    "kpi": kpi, "value": round(value, 2),
                    "baseline": round(baseline, 2),
                    "deviation": round(deviation, 1),
                    "onset": item.get("onset", ""),
                    "is_absolute": is_absolute,
                })

        # Build aggregated alerts
        alerts = []
        for comp, anomalies in component_anomalies.items():
            if len(anomalies) < self.min_anomalous_kpis:
                continue

            anomalies.sort(key=lambda a: a["deviation"], reverse=True)
            top5 = anomalies[:5]

            has_absolute = any(a["is_absolute"] for a in anomalies)
            if has_absolute or len(anomalies) >= 10:
                severity = "critical"
            elif len(anomalies) >= 5:
                severity = "warning"
            else:
                severity = "info"

            onsets = [int(a["onset"]) for a in anomalies if a["onset"]]
            onset_ts = min(onsets) if onsets else 0

            top_desc = ", ".join(f"{a['kpi'][:30]} {a['deviation']}x" for a in top5[:3])
            alerts.append(InfraAlert(
                component=comp, severity=severity,
                anomalous_kpi_count=len(anomalies), top_kpis=top5,
                onset_timestamp=onset_ts,
                description=f"{comp}: {len(anomalies)} anomalous KPIs. Top: {top_desc}",
            ))

        alerts.sort(key=lambda a: (
            0 if a.severity == "critical" else 1 if a.severity == "warning" else 2,
            -a.anomalous_kpi_count,
        ))
        return alerts
