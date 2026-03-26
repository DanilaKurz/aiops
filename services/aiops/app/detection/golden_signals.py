"""Golden Signal Monitor -- detects service-level degradation from metric_app/metric_service data."""
import os
import glob as glob_mod
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class GoldenSignalAlert:
    service: str
    timestamp: int
    signal_type: str  # "success_rate_drop" | "latency_spike"
    current_value: float
    baseline_value: float
    severity: str  # "critical" | "warning"
    description: str


class GoldenSignalMonitor:
    """Monitors metric_app golden signals (sr, mrt, rr) for degradation."""

    def __init__(self, sr_critical=90.0, sr_warning=95.0,
                 mrt_multiplier=5.0, mrt_critical_ms=10000):
        self.sr_critical = sr_critical
        self.sr_warning = sr_warning
        self.mrt_multiplier = mrt_multiplier
        self.mrt_critical_ms = mrt_critical_ms

    def analyze(self, adapter, dataset: str, date: str,
                hour: Optional[int] = None) -> list[GoldenSignalAlert]:
        base = adapter._base_path(dataset, date)
        metric_dir = os.path.join(base, "metric")

        # Find golden signal file (metric_app or metric_service)
        target = None
        for name in ["metric_app.csv", "metric_service.csv"]:
            path = os.path.join(metric_dir, name)
            if os.path.isfile(path):
                target = path
                break

        if not target:
            return []

        df = pd.read_csv(target)

        # Normalize columns across datasets
        if "tc" in df.columns:
            df = df.rename(columns={"tc": "svc", "sr": "sr", "mrt": "mrt"})
        elif "service" in df.columns and "mrt" in df.columns:
            df = df.rename(columns={"service": "svc"})
        elif "serviceName" in df.columns:
            df = df.rename(columns={
                "serviceName": "svc", "startTime": "timestamp",
                "avg_time": "mrt", "succee_rate": "sr",
            })
            if "sr" in df.columns:
                df["sr"] = df["sr"] * 100

        if "svc" not in df.columns or "timestamp" not in df.columns:
            return []

        if hour is not None:
            ts_start = adapter._date_to_timestamp(date, hour)
            ts_end = ts_start + 3600
            df = df[(df["timestamp"] >= ts_start) & (df["timestamp"] < ts_end)]

        if df.empty:
            return []

        alerts = []
        for svc, group in df.groupby("svc"):
            # Success rate
            if "sr" in group.columns:
                sr = group["sr"].dropna()
                if not sr.empty:
                    min_sr = float(sr.min())
                    mean_sr = float(sr.mean())
                    if min_sr < self.sr_critical:
                        row = group.loc[sr.idxmin()]
                        alerts.append(GoldenSignalAlert(
                            service=str(svc), timestamp=int(row["timestamp"]),
                            signal_type="success_rate_drop",
                            current_value=round(min_sr, 2),
                            baseline_value=round(mean_sr, 2),
                            severity="critical",
                            description=f"{svc}: success rate dropped to {min_sr:.1f}% (baseline {mean_sr:.1f}%)",
                        ))
                    elif min_sr < self.sr_warning:
                        row = group.loc[sr.idxmin()]
                        alerts.append(GoldenSignalAlert(
                            service=str(svc), timestamp=int(row["timestamp"]),
                            signal_type="success_rate_drop",
                            current_value=round(min_sr, 2),
                            baseline_value=round(mean_sr, 2),
                            severity="warning",
                            description=f"{svc}: success rate dropped to {min_sr:.1f}% (baseline {mean_sr:.1f}%)",
                        ))

            # Latency
            if "mrt" in group.columns:
                mrt = group["mrt"].dropna()
                if not mrt.empty and mrt.median() > 0:
                    max_mrt = float(mrt.max())
                    median_mrt = float(mrt.median())
                    if max_mrt > median_mrt * self.mrt_multiplier and max_mrt > 1000:
                        row = group.loc[mrt.idxmax()]
                        severity = "critical" if max_mrt > self.mrt_critical_ms else "warning"
                        alerts.append(GoldenSignalAlert(
                            service=str(svc), timestamp=int(row["timestamp"]),
                            signal_type="latency_spike",
                            current_value=round(max_mrt, 1),
                            baseline_value=round(median_mrt, 1),
                            severity=severity,
                            description=f"{svc}: response time {max_mrt:.0f}ms (median {median_mrt:.0f}ms, {max_mrt/median_mrt:.0f}x)",
                        ))

        alerts.sort(key=lambda a: (0 if a.severity == "critical" else 1, a.timestamp))
        return alerts
