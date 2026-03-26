"""Context Builder v4 -- enriched context with cross-hour stability, alert timeline, and KPI categories."""
import os
from collections import defaultdict
from typing import Optional
from datetime import datetime, timezone, timedelta


KPI_CATEGORIES = {
    "MEMORY": ["mem", "heap", "memory", "nocachememperc", "memusedmemperc", "memused",
               "memlimit", "mempercent", "used_memory", "rss", "swap", "cache", "bufferpool"],
    "CPU": ["cpu", "cpuutil", "cpuload", "cpupercent", "cpuuser", "cpusystem",
            "cpuidle", "cpuwio", "singlecpuutil", "jvm_cpuload", "processcpu"],
    "DISK": ["disk", "dsk", "localdisk", "io_read", "io_write", "fsyncs",
             "pending_fsync", "iops", "dskbusy", "dskread", "dskwrite"],
    "NETWORK": ["network", "tcp", "udp", "packet", "rx", "tx", "retransmit",
                "established", "fin_wait", "close_wait", "time_wait"],
    "JVM": ["jvm", "gc", "noheap", "fgc", "fgct", "younggen", "oldgen", "metaspace"],
    "DB": ["innodb", "mysql", "queries", "slow", "com_", "handler",
           "threads_connected", "threads_running", "aborted", "trxrowsmodified", "rowlock"],
    "SERVICE": ["session", "request", "response", "busy", "active", "keepalive",
                "rejected", "maxtime", "processingtime"],
}


def categorize_kpi(kpi_name: str) -> str:
    kpi_lower = kpi_name.lower()
    scores = {}
    for cat, patterns in KPI_CATEGORIES.items():
        score = sum(1 for p in patterns if p in kpi_lower)
        if score > 0:
            scores[cat] = score
    return max(scores, key=scores.get) if scores else "OTHER"


def ts_to_time(timestamp_str: str, date: str) -> str:
    try:
        ts = int(float(timestamp_str))
        parts = date.split("_")
        cst = timezone(timedelta(hours=8))
        dt = datetime.fromtimestamp(ts, tz=cst)
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError, OSError):
        return "?"


class ContextBuilder:
    """Builds rich context for AI agent with:
    - Cross-hour stability (how many hours was this component anomalous?)
    - Alert timeline summary (when did alerts fire for each component)
    - KPI categories (MEMORY/CPU/DISK/NETWORK/JVM/DB)
    - Golden signal history
    - Topology
    """

    def __init__(self, adapter, dataset: str, date: str, topology: dict):
        self.adapter = adapter
        self.dataset = dataset
        self.date = date
        self.topology = topology
        self._metric_cache = {}
        self._gs_cache = {}
        self._stability_cache = None

    def _load_hour_metrics(self, hour: int) -> dict:
        if hour not in self._metric_cache:
            self._metric_cache[hour] = self.adapter.load_metrics(
                self.dataset, self.date, hour=hour)
        return self._metric_cache[hour]

    def _get_golden_signals(self, hour: int) -> dict:
        if hour in self._gs_cache:
            return self._gs_cache[hour]

        import pandas as pd
        base = self.adapter._base_path(self.dataset, self.date)
        metric_dir = os.path.join(base, "metric")

        target = None
        for name in ["metric_app.csv", "metric_service.csv"]:
            path = os.path.join(metric_dir, name)
            if os.path.isfile(path):
                target = path
                break
        if not target:
            self._gs_cache[hour] = {}
            return {}

        df = pd.read_csv(target)
        if "tc" in df.columns:
            df = df.rename(columns={"tc": "svc"})
        elif "service" in df.columns and "mrt" in df.columns:
            df = df.rename(columns={"service": "svc"})
        elif "serviceName" in df.columns:
            df = df.rename(columns={"serviceName": "svc", "startTime": "timestamp",
                                     "avg_time": "mrt", "succee_rate": "sr"})
            if "sr" in df.columns:
                df["sr"] = df["sr"] * 100

        if "svc" not in df.columns or "timestamp" not in df.columns:
            self._gs_cache[hour] = {}
            return {}

        ts_start = self.adapter._date_to_timestamp(self.date, hour)
        df = df[(df["timestamp"] >= ts_start) & (df["timestamp"] < ts_start + 3600)]

        result = {}
        for svc, g in df.groupby("svc"):
            entry = {}
            if "sr" in g.columns:
                sr = g["sr"].dropna()
                if not sr.empty:
                    entry["sr_min"] = round(float(sr.min()), 1)
                    entry["sr_mean"] = round(float(sr.mean()), 1)
            if "mrt" in g.columns:
                mrt = g["mrt"].dropna()
                if not mrt.empty:
                    entry["mrt_max"] = round(float(mrt.max()), 1)
                    entry["mrt_p50"] = round(float(mrt.median()), 1)
            result[str(svc)] = entry

        self._gs_cache[hour] = result
        return result

    def _compute_stability(self, current_hour: int, lookback: int = 6) -> dict:
        """For each component, count how many of the last N hours it was anomalous.
        Returns {component: {anomalous_hours: N, total_hours: M, is_chronic: bool}}"""
        if self._stability_cache is not None:
            return self._stability_cache

        comp_hours = defaultdict(int)
        scanned = 0
        for h in range(max(0, current_hour - lookback), current_hour):
            m = self._load_hour_metrics(h)
            seen = set()
            for item in m.get("anomalies", []):
                seen.add(item["service"])
            for c in seen:
                comp_hours[c] += 1
            scanned += 1

        result = {}
        for comp, count in comp_hours.items():
            result[comp] = {
                "anomalous_hours": count,
                "total_hours": scanned,
                "is_chronic": count >= scanned * 0.7 and scanned >= 3,
            }
        self._stability_cache = result
        return result

    def _build_alert_timeline(self, infra_alerts: list, hour: int) -> list:
        """Build a timeline of when each component's KPIs first crossed threshold.
        Uses the onset timestamps from the infra alerts."""
        timeline = []
        for ia in infra_alerts:
            onsets = [int(k["onset"]) for k in ia.top_kpis if k.get("onset")]
            earliest = min(onsets) if onsets else None
            cat_info = self._categorize_alert(ia)
            timeline.append({
                "component": ia.component,
                "onset_ts": earliest,
                "onset_time": ts_to_time(str(earliest), self.date) if earliest else "?",
                "severity": ia.severity,
                "kpi_count": ia.anomalous_kpi_count,
                "dominant_category": cat_info["dominant"],
                "categories": cat_info["tags"],
            })

        timeline.sort(key=lambda t: t["onset_ts"] if t["onset_ts"] else float("inf"))
        return timeline

    def _categorize_alert(self, ia) -> dict:
        categories = defaultdict(list)
        for kpi in ia.top_kpis:
            categories[categorize_kpi(kpi["kpi"])].append(kpi)

        dominant = "OTHER"
        if categories:
            dominant = max(categories, key=lambda c: (
                len(categories[c]),
                max(k["deviation"] for k in categories[c])
            ))
        return {"dominant": dominant, "tags": sorted(categories.keys()), "by_cat": dict(categories)}

    def _compute_trend(self, values: list) -> str:
        if len(values) < 2:
            return "unknown"
        recent, prev = values[-1], values[-2]
        avg = sum(values) / len(values)
        if recent > avg * 2 and recent > prev * 1.5:
            return "SPIKE"
        elif recent > prev * 1.2:
            return "rising"
        elif recent < prev * 0.8:
            return "falling"
        return "stable"

    def build(self, hour: int, golden_alerts: list, infra_alerts: list,
              incident_summary: str, lookback_hours: int = 3) -> str:
        lines = []

        # Header
        parts = self.date.split("_")
        dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]), hour=hour)
        lines.append(f"SYSTEM: {self.dataset}, {self.date}, Hour {hour} ({hour:02d}:00-{hour+1:02d}:00), {dt.strftime('%A')}")
        lines.append(f"SUMMARY: {incident_summary}")
        lines.append("")

        # Cross-hour stability
        stability = self._compute_stability(hour, lookback=6)
        chronic = [c for c, s in stability.items() if s["is_chronic"]]
        if chronic:
            lines.append(f"CHRONIC NOISE: These components were anomalous in MOST of the last 6 hours: {', '.join(sorted(chronic))}")
            lines.append("  -> If a component is chronically anomalous, it is LESS likely to be root cause of a NEW incident.")
            lines.append("  -> Focus on components with SUDDEN changes (not chronic ones).")
        else:
            lines.append("BASELINE: No chronically anomalous components detected. Any anomaly may be significant.")
        lines.append("")

        # Alert timeline
        timeline = self._build_alert_timeline(infra_alerts, hour)
        lines.append("=== ALERT TIMELINE (when each component first showed anomaly) ===")
        if timeline:
            for i, t in enumerate(timeline):
                chronic_tag = " (CHRONIC)" if stability.get(t["component"], {}).get("is_chronic") else " (NEW!)" if t["component"] not in stability else ""
                stab = stability.get(t["component"], {})
                stab_str = f"anomalous {stab.get('anomalous_hours', '?')}/{stab.get('total_hours', '?')} prev hours" if stab else ""

                lines.append(f"  {t['onset_time']} | {t['component']:<12} | [{t['dominant_category']}] {t['severity']} | {t['kpi_count']} KPIs | {stab_str}{chronic_tag}")
        lines.append("")

        # Golden Signals
        lines.append("=== GOLDEN SIGNALS ===")
        gs = self._get_golden_signals(hour)
        if not gs:
            lines.append("  No data.")
        else:
            degraded_svcs = []
            for svc, data in sorted(gs.items()):
                sr = data.get("sr_min", None)
                mrt_max = data.get("mrt_max", None)
                mrt_p50 = data.get("mrt_p50", None)

                prev_srs = []
                for ph in range(max(0, hour - lookback_hours), hour):
                    ph_gs = self._get_golden_signals(ph)
                    if svc in ph_gs and "sr_mean" in ph_gs[svc]:
                        prev_srs.append(ph_gs[svc]["sr_mean"])
                prev_str = ", ".join(f"{v:.0f}%" for v in prev_srs) if prev_srs else "?"

                status = "OK"
                if sr is not None and sr < 90:
                    status = "CRITICAL"
                    degraded_svcs.append(svc)
                elif sr is not None and sr < 95:
                    status = "DEGRADED"
                    degraded_svcs.append(svc)
                elif mrt_max and mrt_p50 and mrt_p50 > 0 and mrt_max > mrt_p50 * 5 and mrt_max > 1000:
                    status = "LATENCY"
                    degraded_svcs.append(svc)

                if status != "OK":
                    lines.append(f"  {svc}: [{status}] sr_min={sr}% mrt_max={mrt_max}ms mrt_p50={mrt_p50}ms | prev hours sr: [{prev_str}]")

            if not degraded_svcs:
                lines.append("  All services healthy (sr>95%, mrt normal).")
        lines.append("")

        # Infrastructure details (only non-chronic or severe)
        lines.append("=== INFRASTRUCTURE DETAILS ===")
        if not infra_alerts:
            lines.append("  No significant anomalies.")
        else:
            for ia in infra_alerts:
                stab = stability.get(ia.component, {})
                is_chronic = stab.get("is_chronic", False)
                cat_info = self._categorize_alert(ia)

                label = "CHRONIC" if is_chronic else "NEW/CHANGED"
                lines.append(f"  {ia.component} [{label}] [{'+'.join(cat_info['tags'])}] {ia.severity} -- {ia.anomalous_kpi_count} KPIs")

                for cat, kpis in sorted(cat_info["by_cat"].items(),
                                        key=lambda x: max(k["deviation"] for k in x[1]), reverse=True):
                    top = sorted(kpis, key=lambda k: k["deviation"], reverse=True)[0]
                    short_name = top["kpi"].split("_")[-1] if "_" in top["kpi"] else top["kpi"][:30]

                    # Trend
                    hist_vals = []
                    for ph in range(max(0, hour - lookback_hours), hour):
                        pm = self._load_hour_metrics(ph)
                        for item in pm.get("anomalies", []) + pm.get("normal_metrics", []):
                            if item["service"] == ia.component and item["metric"] == top["kpi"]:
                                hist_vals.append(item["value"])
                                break
                    trend = self._compute_trend(hist_vals + [top["value"]]) if hist_vals else "unknown"
                    prev = f"prev=[{', '.join(f'{v:.1f}' for v in hist_vals[-3:])}]" if hist_vals else "prev=?"

                    lines.append(f"    {cat}: {short_name} = {top['value']} ({top['deviation']}x) trend={trend} {prev}")

                    # Absolute threshold alerts
                    kpi_lower = top["kpi"].lower()
                    if any(p in kpi_lower for p in ["memperc", "memusedmem", "nocachemem"]) and top["value"] > 90:
                        lines.append(f"    >>> ABSOLUTE CRITICAL: memory at {top['value']}%")
                    if any(p in kpi_lower for p in ["cpuutil", "cpupercent", "singlecpu"]) and top["value"] > 90:
                        lines.append(f"    >>> ABSOLUTE CRITICAL: CPU at {top['value']}%")
                lines.append("")
        lines.append("")

        # Topology
        lines.append("=== TOPOLOGY ===")
        deps = defaultdict(list)
        for e in self.topology.get("edges", []):
            deps[e["source"]].append(e["target"])
        for src in sorted(deps.keys()):
            lines.append(f"  {src} -> {', '.join(sorted(deps[src]))}")

        return "\n".join(lines)
