"""Spike: build L0/L1/L2 tables on Bank dataset (real sources only) — ENHANCED.

Enhancements over mockup_l2_tables.py:
  - ALL 10 Bank days (not just 3)
  - Per-L1 arrays (burst_5min, day_counts, host_ev)
  - L2 keyword matching metadata
  - Cross-L2 incident correlation
  - Stale rule flag
  - Output data.json + data.js in docs/mockup_l2/

Sources:
  Prometheus  -- metric_container.csv, thresholds = p95 of baseline day 2021-03-04
  AppMonitor  -- metric_app.csv, success-rate and response-time alerts
  Log Agent   -- log_service.csv parsed by Drain3

Output:
  - 4 CSVs in docs/mockup_l2/
  - docs/mockup_l2/index.html
  - docs/mockup_l2/data.json
  - docs/mockup_l2/data.js

Usage: py sandbox/compute_l2_enhanced.py
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

DAYS = [
    "2021_03_04", "2021_03_05", "2021_03_06", "2021_03_07",
    "2021_03_09", "2021_03_10", "2021_03_12",
    "2021_03_23", "2021_03_24", "2021_03_25",
]
DAYS_HUMAN = [d.replace("_", "-") for d in DAYS]
TOTAL_DAYS = len(DAYS)
DAY_HUMAN = " / ".join(DAYS_HUMAN)        # for HTML title

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "Bank"
OUT = ROOT / "docs" / "mockup_l2"
OUT.mkdir(parents=True, exist_ok=True)


def telemetry_dir(day):
    return BANK / "telemetry" / day


LOG_SAMPLE_PER_DAY = 70_000     # cap per-day log sample
GAP_MIN = 5                     # series break threshold, minutes
DOWNSAMPLE_FREQ = "5min"        # max 1 metric L0 per (kpi, host, 5-min bucket)
BASELINE_DAY = "2021_03_04"     # normal day used for threshold computation

# Prometheus alert rules: threshold = p95 of baseline day.
# match "=" -> exact kpi_name, "~" -> regex on kpi_name.
RULES = [
    {"id": "prom-cpu",   "match": "=", "kpi": "OSLinux-CPU_CPU_CPUCpuUtil",
     "label": "CPU utilization above threshold",
     "l2": "CPU/Memory нагрузка", "p": 0.95},
    {"id": "prom-load",  "match": "=", "kpi": "OSLinux-CPU_CPU_CPULoad",
     "label": "Load average above threshold",
     "l2": "CPU/Memory нагрузка", "p": 0.95},
    {"id": "prom-wio",   "match": "=", "kpi": "OSLinux-CPU_CPU_CPUWio",
     "label": "Disk IO wait above threshold",
     "l2": "Disk IO нагрузка", "p": 0.95},
    {"id": "prom-jvm",   "match": "~", "pattern": r"JVM-Memory.*HeapMemoryUsed$",
     "label": "JVM heap usage high",
     "l2": "JVM heap & GC давление", "p": 0.95},
    {"id": "prom-cmem",  "match": "~", "pattern": r"_MemPercent$",
     "label": "Container memory high",
     "l2": "CPU/Memory нагрузка", "p": 0.95},
    {"id": "prom-cnet",  "match": "~", "pattern": r"_NetworkRxBytes$",
     "label": "Network RX above threshold",
     "l2": "Сетевые деградации", "p": 0.95},
    {"id": "prom-mysql", "match": "~", "pattern": r"Mysql.*GetResponseTime",
     "label": "MySQL response time high",
     "l2": "Slow SQL queries", "p": 0.95},
]

# Drop pattern: lines that aren't alerts at all (load test traffic, access logs)
LOG_DROP = re.compile(r"\bk6/|HTTP/1\.1|GET /|POST /api|access_log", re.I)

# L2 keyword routing. First match wins. Order matters: more specific first.
L2_LOG_KEYWORDS = [
    # JVM heap & GC pressure (specific to Bank — JVM-heavy stack)
    (re.compile(r"\bGC\b|ParNew|CMS\b|Metaspace|Allocation Failure|Full GC|garbage|HeapMemory|ThreadLocal|memory leak|NamingResourcesImpl|JVM", re.I),
     "JVM heap & GC давление"),
    # Slow SQL queries
    (re.compile(r"Query_time|User@Host|Lock_time|Rows_sent|Rows_examined|page_cleaner|InnoDB|\bSELECT |\bINSERT |\bUPDATE |TableName", re.I),
     "Slow SQL queries"),
    # Tomcat lifecycle / deployments / restarts
    (re.compile(r"deploy|startInternal|StandardService|StandardEngine|Bootstrap|Catalina\.start|ProtocolHandler|Server startup|Server built|Architecture|VersionLogger|Initializing Spring|ApplicationContext\.log|TldScanner|Failed to start component|FrameworkServlet|web application|Servlet Engine|JedisSentinel|JedisPool|Tomcat", re.I),
     "Tomcat деплои и рестарты"),
    # Disk / IO load
    (re.compile(r"\bdisk\b|\bio[ _-]wait\b|disk space|access_log", re.I),
     "Disk IO нагрузка"),
    # Network / connectivity
    (re.compile(r"\bnetwork|packet|timeout|connection|\btcp\b|socket|RpcContext|dubbo", re.I),
     "Сетевые деградации"),
    # Generic resource pressure (CPU, Memory)
    (re.compile(r"\bcpu|memory|load |Mem(?:Percent|Usage)", re.I),
     "CPU/Memory нагрузка"),
]
# default for unmatched templates
DEFAULT_L2 = "Неизвестно / не классифицировано"

REASON_TO_L2 = {
    "high CPU usage":               "CPU/Memory нагрузка",
    "high memory usage":            "CPU/Memory нагрузка",
    "high JVM CPU load":            "JVM heap & GC давление",
    "JVM Out of Memory (OOM) Heap": "JVM heap & GC давление",
    "high disk I/O read usage":     "Disk IO нагрузка",
    "high disk space usage":        "Disk IO нагрузка",
    "network packet loss":          "Сетевые деградации",
    "network latency":              "Сетевые деградации",
}

# OIM severity by reason — reflects nature of incident, not just "all critical".
# OOM/disk-space = unrecoverable without restart -> CRIT
# CPU/memory/IO/network = mostly transient under load -> WARN
OIM_SEVERITY = {
    "JVM Out of Memory (OOM) Heap": "CRITICAL",
    "high disk space usage":        "CRITICAL",
    "high JVM CPU load":            "WARNING",
    "high CPU usage":                "WARNING",
    "high memory usage":             "WARNING",
    "high disk I/O read usage":      "WARNING",
    "network latency":               "WARNING",
    "network packet loss":           "WARNING",
}

OIM_SEVERITY_REASONING = {
    "JVM Out of Memory (OOM) Heap": "Heap исчерпан, без рестарта JVM не восстанавливается — критично всегда",
    "high disk space usage":        "Диск заполняется — БД/логи скоро встанут, требует немедленных действий",
    "high JVM CPU load":            "Высокая нагрузка на JVM — обычно переживается под пиками",
    "high CPU usage":                "Скачок CPU — чаще транзиентный, не повод эскалации",
    "high memory usage":             "Высокая память — надо смотреть тренд, обычно WARN",
    "high disk I/O read usage":      "Всплеск IO — типично кратковременен под нагрузкой",
    "network latency":               "Сетевая задержка — почти всегда транзиентна",
    "network packet loss":           "Потери пакетов — обычно эпизод, не глобальная авария",
}


def severity_for_ratio(value, thr):
    ratio = value / max(thr, 1e-6)
    if ratio >= 2.0:
        return "CRITICAL"
    if ratio >= 1.5:
        return "WARNING"
    return "INFO"


def _baseline_thresholds() -> dict:
    """Compute p95 per kpi_name from the baseline (normal) day."""
    path = telemetry_dir(BASELINE_DAY) / "metric" / "metric_container.csv"
    df = pd.read_csv(path)
    return df.groupby("kpi_name")["value"].quantile(0.95).to_dict()


def gen_prometheus_l0():
    print(f"[1/3] Loading metric_container.csv for {len(DAYS)} day(s) ...")
    baseline = _baseline_thresholds()
    parts = []
    for day in DAYS:
        df = pd.read_csv(telemetry_dir(day) / "metric" / "metric_container.csv")
        df["date"] = day.replace("_", "-")
        parts.append(df)
        print(f"      {day}: {len(df):,} rows")
    m = pd.concat(parts, ignore_index=True)
    m["timestamp"] = pd.to_datetime(m["timestamp"], unit="s")
    print(f"      total: rows={len(m):,} kpis={m.kpi_name.nunique()}")
    out = []
    for r in RULES:
        if r["match"] == "=":
            sub = m[m.kpi_name == r["kpi"]]
        else:
            sub = m[m.kpi_name.str.contains(r["pattern"], regex=True, na=False)]
        if sub.empty:
            print(f"      {r['id']:<10}: 0 rows match")
            continue
        # threshold = p95 of each kpi_name from baseline (honest)
        kpi_thrs = {kpi: baseline.get(kpi) for kpi in sub["kpi_name"].unique()}
        rows_above = []
        for kpi, grp in sub.groupby("kpi_name"):
            thr = kpi_thrs.get(kpi)
            if thr is None or thr == 0:
                continue
            above = grp[grp["value"] > thr].copy()
            above["_thr"] = thr
            rows_above.append(above)
        if not rows_above:
            print(f"      {r['id']:<10}: 0 events above baseline p95")
            continue
        above = pd.concat(rows_above, ignore_index=True)
        above["bucket"] = above["timestamp"].dt.floor(DOWNSAMPLE_FREQ)
        above = above.groupby(["cmdb_id", "kpi_name", "bucket"], as_index=False).first()
        sev = [severity_for_ratio(v, t) for v, t in zip(above["value"], above["_thr"])]
        ts_str = above["timestamp"].dt.strftime("%H:%M:%S").values
        kpi_short = above["kpi_name"].str.split("_").str[-1]
        raw = [f"[{ts}] {r['label']} on {h}: {ks}={v:.2f} > p95_baseline={t:.2f}"
               for ts, h, ks, v, t in zip(ts_str, above["cmdb_id"].values,
                                           kpi_short.values, above["value"].values, above["_thr"].values)]
        out.append(pd.DataFrame({
            "timestamp":   above["timestamp"].values,
            "date":        above["date"].values,
            "source":      "Prometheus",
            "severity":    sev,
            "rule_id":     r["id"],
            "l1_template": r["label"] + " on {host}",
            "l1_origin":   f"metric threshold rule · p95 baseline {BASELINE_DAY}",
            "l2_class":    r["l2"],
            "l2_keywords": [[r["label"]] for _ in range(len(above))],
            "host":        above["cmdb_id"].values,
            "service":     above["cmdb_id"].values,
            "raw_value":   raw,
        }))
        print(f"      {r['id']:<10}: L0_events={len(above):>5}")
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def gen_app_monitor_l0():
    """Generate alerts from metric_app.csv: success rate and response time."""
    print(f"[2/3-app] Loading metric_app.csv baseline + incident days ...")
    base = pd.read_csv(telemetry_dir(BASELINE_DAY) / "metric" / "metric_app.csv")
    sr_thr = base["sr"].quantile(0.05)      # alert when sr drops below 5th-pct of normal
    mrt_thr = base["mrt"].quantile(0.95) * 1.5  # alert when mrt exceeds 1.5x worst-normal

    parts = []
    for day in DAYS:
        df = pd.read_csv(telemetry_dir(day) / "metric" / "metric_app.csv")
        df["date"] = day.replace("_", "-")
        parts.append(df)
    m = pd.concat(parts, ignore_index=True)
    m["timestamp"] = pd.to_datetime(m["timestamp"], unit="s")
    print(f"      sr_thr={sr_thr:.1f}%  mrt_thr={mrt_thr:.0f}ms  rows={len(m):,}")

    out = []
    # Success-rate drop alerts
    sr_bad = m[m["sr"] < sr_thr].copy()
    if not sr_bad.empty:
        sr_bad["bucket"] = sr_bad["timestamp"].dt.floor(DOWNSAMPLE_FREQ)
        sr_bad = sr_bad.groupby(["tc", "bucket"], as_index=False).first()
        out.append(pd.DataFrame({
            "timestamp":   sr_bad["timestamp"].values,
            "date":        sr_bad["date"].values,
            "source":      "AppMonitor",
            "severity":    ["CRITICAL"] * len(sr_bad),
            "rule_id":     "app-sr-drop",
            "l1_template": "Service success rate drop on {service}",
            "l1_origin":   f"metric rule · sr < p05 of baseline {BASELINE_DAY}",
            "l2_class":    "Сетевые деградации",
            "l2_keywords": [["Service success rate drop"] for _ in range(len(sr_bad))],
            "host":        sr_bad["tc"].values,
            "service":     sr_bad["tc"].values,
            "raw_value":   [f"sr={v:.1f}% < threshold={sr_thr:.1f}% (svc={s})"
                            for v, s in zip(sr_bad["sr"].values, sr_bad["tc"].values)],
        }))
        print(f"      app-sr-drop: {len(sr_bad):>5} events (sr < {sr_thr:.1f}%)")

    # Response-time spike alerts
    mrt_bad = m[m["mrt"] > mrt_thr].copy()
    if not mrt_bad.empty:
        mrt_bad["bucket"] = mrt_bad["timestamp"].dt.floor(DOWNSAMPLE_FREQ)
        mrt_bad = mrt_bad.groupby(["tc", "bucket"], as_index=False).first()
        out.append(pd.DataFrame({
            "timestamp":   mrt_bad["timestamp"].values,
            "date":        mrt_bad["date"].values,
            "source":      "AppMonitor",
            "severity":    ["WARNING"] * len(mrt_bad),
            "rule_id":     "app-mrt-spike",
            "l1_template": "Service response time spike on {service}",
            "l1_origin":   f"metric rule · mrt > 1.5x p95 of baseline {BASELINE_DAY}",
            "l2_class":    "Сетевые деградации",
            "l2_keywords": [["Service response time spike"] for _ in range(len(mrt_bad))],
            "host":        mrt_bad["tc"].values,
            "service":     mrt_bad["tc"].values,
            "raw_value":   [f"mrt={v:.0f}ms > threshold={mrt_thr:.0f}ms (svc={s})"
                            for v, s in zip(mrt_bad["mrt"].values, mrt_bad["tc"].values)],
        }))
        print(f"      app-mrt-spike: {len(mrt_bad):>5} events (mrt > {mrt_thr:.0f}ms)")

    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def gen_log_l0():
    print(f"[3/3] Loading log_service.csv for {len(DAYS)} day(s) ...")
    parts = []
    for day in DAYS:
        df = pd.read_csv(telemetry_dir(day) / "log" / "log_service.csv")
        df["date"] = day.replace("_", "-")
        # filter out non-alert traffic per day
        keep = ~df["value"].astype(str).str.contains(LOG_DROP, na=False)
        df_kept = df[keep]
        dropped = len(df) - len(df_kept)
        if len(df_kept) > LOG_SAMPLE_PER_DAY:
            df_kept = df_kept.sample(n=LOG_SAMPLE_PER_DAY, random_state=42)
        parts.append(df_kept)
        print(f"      {day}: rows={len(df):,} dropped={dropped:,} sampled={len(df_kept):,}")
    L = pd.concat(parts, ignore_index=True)
    L["timestamp"] = pd.to_datetime(L["timestamp"], unit="s")
    L = L.sort_values("timestamp").reset_index(drop=True)
    print(f"      total kept: {len(L):,}")
    miner = TemplateMiner(config=TemplateMinerConfig())
    template_ids = np.empty(len(L), dtype=np.int32)
    tpl_text = {}
    msgs = L["value"].astype(str).values
    n = len(msgs)
    for i, msg in enumerate(msgs):
        res = miner.add_log_message(msg)
        cid = res["cluster_id"]
        template_ids[i] = cid
        if cid not in tpl_text or res["change_type"] != "none":
            tpl_text[cid] = res["template_mined"]
        if i and i % 50_000 == 0:
            print(f"      drain3 progress: {i:,}/{n:,}  unique_tpls={len(tpl_text)}")
    L["template_id"] = template_ids
    L["l1_template"] = pd.Series(template_ids).map(tpl_text).values
    print(f"      drain3 done: {len(tpl_text)} unique templates")

    def classify_with_keywords(tpl):
        for pat, l2 in L2_LOG_KEYWORDS:
            m = pat.search(tpl)
            if m:
                return l2, [m.group()]
        return DEFAULT_L2, []

    def severity_from_log(msg):
        s = str(msg).lstrip()
        head = s[:10].upper()
        if head.startswith("SEVERE") or head.startswith("ERROR") or head.startswith("FATAL"):
            return "CRITICAL"
        if head.startswith("WARN"):
            return "WARNING"
        return "INFO"

    l2_meta = L["l1_template"].apply(classify_with_keywords)
    L["l2_class"] = l2_meta.apply(lambda x: x[0])
    L["l2_keywords"] = l2_meta.apply(lambda x: x[1])
    L["source"] = "Log Agent"
    L["rule_id"] = "log-tpl-" + L["template_id"].astype(str)
    L["l1_origin"] = "Drain3 cluster #" + L["template_id"].astype(str) + " · ML auto-clustering"
    L["host"] = L["cmdb_id"]
    L["service"] = L["cmdb_id"]
    L["severity"] = L["value"].apply(severity_from_log)
    L["raw_value"] = L["value"].astype(str)
    return L[["timestamp", "date", "source", "severity", "rule_id", "l1_template", "l1_origin",
              "l2_class", "l2_keywords", "host", "service", "raw_value"]]




L1_LABEL_RULES = [
    (re.compile(r"Full GC \(Metadata GC Threshold\)", re.I), "Metadata GC threshold"),
    (re.compile(r"Full GC \(Last ditch", re.I), "Last-ditch Full GC"),
    (re.compile(r"Full GC", re.I), "Full GC pause"),
    (re.compile(r"GC \(Allocation Failure\)", re.I), "Allocation Failure GC"),
    (re.compile(r"GC \(CMS Initial Mark\)", re.I), "CMS Initial Mark"),
    (re.compile(r"GC \(GCLocker", re.I), "GCLocker GC"),
    (re.compile(r"CMS-concurrent-mark", re.I), "CMS concurrent mark"),
    (re.compile(r"Query_time.*Rows_examined: 1\b", re.I), "Slow SELECT (1 row)"),
    (re.compile(r"Query_time.*Rows_sent: 0 Rows_examined: 0", re.I), "Slow query (0 rows)"),
    (re.compile(r"Query_time.*INSERT", re.I), "Slow INSERT"),
    (re.compile(r"Query_time.*UPDATE", re.I), "Slow UPDATE"),
    (re.compile(r"Query_time", re.I), "Slow SQL query"),
    (re.compile(r"page_cleaner.*intended loop", re.I), "InnoDB page_cleaner slow"),
    (re.compile(r"Same incident from\s+(.+?)\s+on", re.I), None),  # keep as-is
    (re.compile(r"checkThreadLocalMapForLeaks", re.I), "ThreadLocal memory leak"),
    (re.compile(r"clearReferencesThreads", re.I), "Tomcat thread leak"),
    (re.compile(r"Initializing Spring", re.I), "Spring WebApp init"),
    (re.compile(r"Deployment.*finished", re.I), "Tomcat deploy finished"),
    (re.compile(r"Deploying web application", re.I), "Tomcat deploy started"),
    (re.compile(r"Server startup", re.I), "Server startup"),
    (re.compile(r"Servlet Engine|StandardEngine.*startInternal", re.I), "Servlet engine start"),
    (re.compile(r"ProtocolHandler", re.I), "Tomcat ProtocolHandler"),
    (re.compile(r"VersionLoggerListener", re.I), "Tomcat version logger"),
    (re.compile(r"JedisSentinelPool", re.I), "Redis Sentinel pool init"),
    (re.compile(r"BasicDataSourceFactory.*maxActive", re.I), "DBCP2 maxActive deprecated"),
    (re.compile(r"BasicDataSourceFactory.*maxWait", re.I), "DBCP2 maxWait deprecated"),
    (re.compile(r"BasicDataSourceFactory", re.I), "DBCP2 config warning"),
    (re.compile(r"TldScanner.*JAR was scanned", re.I), "TLD scanner empty JAR"),
    (re.compile(r"Failed to start component", re.I), "Failed to start component"),
    (re.compile(r"Failed to retrieve JNDI", re.I), "JNDI cleanup failed"),
    (re.compile(r"shutdown command was received", re.I), "Tomcat shutdown command"),
    (re.compile(r"Waiting for .*instance", re.I), "Tomcat waiting on instance"),
    (re.compile(r"AprLifecycleListener", re.I), "Tomcat APR not found"),
    (re.compile(r"NioSelectorPool", re.I), "Tomcat NIO selector init"),
    (re.compile(r"StandardWrapper.*unload", re.I), "Tomcat servlet unload"),
    (re.compile(r"ContainerBase\.addChild", re.I), "Tomcat addChild error"),
    (re.compile(r"Error deploying", re.I), "Tomcat deploy error"),
]


def short_l1_name(template, max_len=55):
    """Convert long log template to short readable name."""
    s = str(template)
    for pat, label in L1_LABEL_RULES:
        if pat.search(s):
            if label is not None:
                return label
            return re.sub(r"\s+", " ", s).strip()[:max_len]
    s = re.sub(r"^(SEVERE|INFO|WARNING|DEBUG)\s*\[\S+\]\s*", "", s)
    s = re.sub(r"^[\w.$]+\s+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("<*>", "{X}")
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


def top_l1_per_class(L0, top_n=3):
    """For each L2 class, return ', '-joined top-N unique L1 short names by event count."""
    out = {}
    for l2, grp in L0.groupby("l2_class"):
        ranked = grp.groupby("l1_template").size().sort_values(ascending=False).index.tolist()
        seen = []
        for tpl in ranked:
            short = short_l1_name(tpl)
            if short not in seen:
                seen.append(short)
            if len(seen) >= top_n:
                break
        out[l2] = ", ".join(seen)
    return out


def make_verdict(row):
    if row["Класс проблемы L2"] == "Дубли из разных систем":
        return "Дедупликация на уровне правил необходима"
    if row["Событий L0"] >= 5000 and row["AutoResolve %"] >= 85:
        return "Массовые ложные срабатывания, ужесточить пороги или duration"
    if row["AutoResolve %"] < 60:
        return "Алерты не закрываются сами — реальная нагрузка, требует фикса архитектуры"
    if row["Событий L0"] < 200:
        return "Незначительный поток, правила в норме"
    if row["AutoResolve %"] >= 95 and row["Среднее время жизни (мин)"] <= 2:
        return "Полный шум: TTL близок к нулю, рассмотреть отключение правила"
    return "Шум средней интенсивности, рассмотреть подъём severity"


def make_series(events):
    rows = []
    for (rule, host), grp in events.groupby(["rule_id", "host"], sort=False):
        ts = grp.sort_values("timestamp")["timestamp"].values
        first = grp.sort_values("timestamp").iloc[0]
        if len(ts) == 1:
            rows.append({
                "rule_id": rule, "host": host,
                "events_in_series": 1, "duration_s": 0,
                "l2_class": first["l2_class"], "l1_template": first["l1_template"],
                "source": first["source"], "service": first["service"],
            })
            continue
        gaps = np.diff(ts).astype("timedelta64[s]").astype(int)
        breaks = np.where(gaps > GAP_MIN * 60)[0]
        starts = np.r_[0, breaks + 1]
        ends = np.r_[breaks, len(ts) - 1]
        for s, e in zip(starts, ends):
            dur = int((ts[e] - ts[s]).astype("timedelta64[s]").astype(int))
            rows.append({
                "rule_id": rule, "host": host,
                "events_in_series": int(e - s + 1), "duration_s": dur,
                "l2_class": first["l2_class"], "l1_template": first["l1_template"],
                "source": first["source"], "service": first["service"],
            })
    df = pd.DataFrame(rows)
    # auto-resolved = short series that closed by gap > GAP_MIN
    # softened: any series with <=5 events OR <=10min duration counts as auto-resolved
    df["auto_resolved"] = ((df["events_in_series"] <= 5) | (df["duration_s"] <= 600)).astype(int)
    return df


def mark_duplicates(L0, window_min=1):
    """Flag duplicates: same host, same time window, 2+ distinct sources.

    Duplicates are NOT reclassified — they keep their original L2 class.
    This is a preprocessing step (Integration Center), not a classification step.
    Returns (L0_flagged, dedup_stats).
    """
    L0 = L0.copy()
    L0["_minute"] = L0["timestamp"].dt.floor(f"{window_min}min")
    src_count = (L0.groupby(["host", "_minute"])["source"]
                 .nunique().rename("src_in_window").reset_index())
    L0 = L0.merge(src_count, on=["host", "_minute"], how="left")
    is_dup = L0["src_in_window"] >= 2
    n_dup = int(is_dup.sum())

    # For each duplicate event, record which sources fired together (for UI explanation)
    if n_dup:
        pairs = (L0[is_dup].groupby(["host", "_minute"])["source"]
                 .agg(lambda x: " + ".join(sorted(set(x))))
                 .rename("dup_sources").reset_index())
        L0 = L0.merge(pairs, on=["host", "_minute"], how="left")
    else:
        L0["dup_sources"] = None

    L0["is_dup"] = is_dup
    L0 = L0.drop(columns=["_minute", "src_in_window"])

    # Sample a few examples for the UI explanation
    examples = []
    if n_dup:
        sample = L0[is_dup].head(3)
        for row in sample.itertuples():
            examples.append({
                "host": row.host,
                "sources": row.dup_sources,
                "l2_class": row.l2_class,
                "time": str(row.timestamp)[:16],
            })

    dedup_stats = {
        "received": len(L0),
        "deduplicated": n_dup,
        "unique": len(L0) - n_dup,
        "window_min": window_min,
        "criterion": f"host совпадает + временное окно {window_min} мин + 2+ источника",
        "examples": examples,
    }
    print(f"  dedup: {n_dup:,} events flagged ({100*n_dup/max(len(L0),1):.1f}%) — kept original L2 class")
    return L0, dedup_stats


def compute_cross_l2(L0_unique):
    """For each L1, which other L2 classes share the same (host, day)."""
    l1_l2_map = L0_unique.groupby("l1_template")["l2_class"].first().to_dict()
    host_day_l2 = L0_unique.groupby(["host", "date"])["l2_class"].apply(set).to_dict()

    result = {}
    for (l1_template, source), grp in L0_unique.groupby(["l1_template", "source"]):
        related = {}
        my_l2 = l1_l2_map.get(l1_template, "")
        for _, row in grp.iterrows():
            key = (row["host"], row["date"])
            others = host_day_l2.get(key, set())
            for other_l2 in others:
                if other_l2 != my_l2:
                    related[other_l2] = related.get(other_l2, 0) + 1
        if related:
            result[(l1_template, source)] = related
    return result


def compute_stale(row):
    """Stale = auto-resolve >= 90%, days active >= 80%, TTL < 10 min, events >= 200."""
    auto_r = row.get("autoresolve_pct", 0)
    days_r = row.get("days_active_ratio", 1)
    ttl = row.get("avg_lifetime_min", 99)
    ev = row.get("events", 0)
    return auto_r >= 90 and days_r >= 0.8 and ttl < 10 and ev >= 200


def main():
    z = gen_prometheus_l0()
    a = gen_app_monitor_l0()
    g = gen_log_l0()
    print()
    L0 = pd.concat([z, a, g], ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    if "l1_origin" not in L0.columns:
        L0["l1_origin"] = ""
    print(f"L0 raw total events: {len(L0):,}")
    print(f"  per source: {L0['source'].value_counts().to_dict()}")
    L0, dedup_stats = mark_duplicates(L0, window_min=1)
    # Use only unique (non-duplicate) events for L2 classification
    L0_unique = L0[~L0["is_dup"]].copy()
    print(f"  L0 unique (after dedup): {len(L0_unique):,}")
    print(f"  L2 class breakdown:")
    for k, v in L0_unique["l2_class"].value_counts().items():
        print(f"    {k:<40} {v:>7,}")
    series = make_series(L0_unique)
    print(f"  series: {len(series):,}  auto_resolved={series['auto_resolved'].sum():,}")

    # ====== Table 1: Главная сводная по классам L2 ======
    g1 = L0_unique.groupby("l2_class").agg(
        events_l0=("rule_id", "count"),
        templates_l1=("rule_id", "nunique"),
        host_count=("host", "nunique"),
        service_count=("service", "nunique"),
    )
    s1 = series.groupby("l2_class").agg(
        incidents=("rule_id", "count"),
        avg_lifetime_s=("duration_s", "mean"),
        autoresolve_pct=("auto_resolved", lambda x: round(100 * x.mean(), 1)),
    )
    sources_str = L0_unique.groupby("l2_class")["source"].agg(lambda x: ", ".join(sorted(set(x))))
    top_src = L0_unique.groupby("l2_class")["source"].agg(lambda x: x.value_counts().index[0])
    top_host = L0_unique.groupby("l2_class")["host"].agg(lambda x: x.value_counts().index[0])
    top_svc = L0_unique.groupby("l2_class")["service"].agg(lambda x: x.value_counts().index[0])
    inner_l1 = pd.Series(top_l1_per_class(L0_unique, top_n=3), name="inner_l1")
    main = g1.join(s1).assign(
        inner_l1=inner_l1,
        sources=sources_str, top_source=top_src, top_host=top_host, top_service=top_svc,
    ).reset_index()
    main["avg_lifetime_min"] = (main["avg_lifetime_s"] / 60).round(1)
    main = main.drop(columns="avg_lifetime_s")
    main = main.sort_values("events_l0", ascending=False).reset_index(drop=True)
    main.insert(0, "#", main.index + 1)
    main = main[[
        "#", "l2_class", "inner_l1", "sources", "events_l0", "templates_l1",
        "incidents", "autoresolve_pct", "avg_lifetime_min",
        "top_source", "top_host", "top_service", "host_count", "service_count",
    ]]
    main.columns = [
        "#", "Класс проблемы L2", "Что входит внутрь, L1", "Источники",
        "Событий L0", "Шаблонов L1", "Инцидентов", "AutoResolve %",
        "Среднее время жизни (мин)", "Самый шумный источник",
        "Самый шумный host", "Самый шумный service", "Хостов", "Сервисов",
    ]
    sev_counts = L0_unique.pivot_table(
        index="l2_class", columns="severity", values="rule_id", aggfunc="count", fill_value=0
    )
    for col in ("CRITICAL", "WARNING", "INFO"):
        if col not in sev_counts.columns:
            sev_counts[col] = 0
    main["CRITICAL"] = main["Класс проблемы L2"].map(sev_counts["CRITICAL"]).fillna(0).astype(int)
    main["WARNING"] = main["Класс проблемы L2"].map(sev_counts["WARNING"]).fillna(0).astype(int)
    main["INFO"] = main["Класс проблемы L2"].map(sev_counts["INFO"]).fillna(0).astype(int)
    main["Вывод"] = main.apply(make_verdict, axis=1)
    main.to_csv(OUT / "01_main_l2_classes.csv", index=False, encoding="utf-8-sig")

    # ====== Table 2: Drill-down L2 -> L1 ======
    g2 = L0_unique.groupby(["l2_class", "l1_template", "rule_id", "source"]).agg(
        events=("host", "count"),
        hosts=("host", "nunique"),
        services=("service", "nunique"),
    ).reset_index()
    s2 = series.groupby(["l2_class", "l1_template"]).agg(
        incidents=("rule_id", "count"),
        avg_lifetime_s=("duration_s", "mean"),
        autoresolve_pct=("auto_resolved", lambda x: round(100 * x.mean(), 1)),
    ).reset_index()
    drill = g2.merge(s2, on=["l2_class", "l1_template"], how="left")
    drill["avg_lifetime_min"] = (drill["avg_lifetime_s"] / 60).round(1)
    drill = drill.drop(columns="avg_lifetime_s")

    # l1_origin: how was this L1 template created
    origin_map = (L0_unique.groupby(["l1_template", "source"])["l1_origin"].first().to_dict())
    drill["l1_origin"] = drill.apply(
        lambda r: origin_map.get((r["l1_template"], r["source"]), "—"), axis=1
    )

    # extra noise metrics per (l1_template, source): events_per_host / dedup_ratio /
    # burstiness / days_active_ratio / burst_5min / day_counts / host_ev / l2_keywords
    L0_w = L0_unique.copy()
    L0_w["bucket"] = L0_w["timestamp"].dt.floor("5min")
    extra_rows = []
    for (l1, src), g in L0_w.groupby(["l1_template", "source"]):
        n_events = len(g)
        n_hosts = max(g["host"].nunique(), 1)
        n_days = g["date"].nunique()
        # dedup hash = host + 5-min bucket
        unique_hashes = g.groupby(["host", "bucket"]).ngroups
        # bucket counts per (host, bucket) — for burstiness
        per_bucket = g.groupby(["host", "bucket"]).size()
        median_b = float(per_bucket.median()) if len(per_bucket) else 0.0
        p95_b = float(per_bucket.quantile(0.95)) if len(per_bucket) else 0.0
        if median_b > 0:
            burst = round(p95_b / median_b, 2)
        elif p95_b > 0:
            burst = round(p95_b, 2)
        else:
            burst = 0.0

        # NEW: per-day counts (N elements, one per day)
        day_counts_series = g.groupby("date").size()
        day_counts = [int(day_counts_series.get(d.replace("_", "-"), 0)) for d in DAYS]

        # NEW: per-window burst for sparkline
        per_window = g.groupby("bucket").size().sort_index()
        burst_5min = per_window.tolist()
        # Cap at 500 points to keep SVG small
        if len(burst_5min) > 500:
            idx = np.linspace(0, len(burst_5min)-1, 500, dtype=int)
            burst_5min = [burst_5min[i] for i in idx]

        # NEW: per-host distribution
        host_ev = g.groupby("host").size().to_dict()

        # NEW: per-host per-day matrix for stacked chart
        host_day = g.groupby(["host", "date"]).size().reset_index(name="cnt")
        host_day_matrix = {}
        for _, hd_row in host_day.iterrows():
            h = hd_row["host"]
            d = hd_row["date"]  # e.g. 2021_03_04
            day_label = d.replace("_", "-")
            if h not in host_day_matrix:
                host_day_matrix[h] = {}
            host_day_matrix[h][day_label] = int(hd_row["cnt"])

        # NEW: keywords matched
        kws = g["l2_keywords"].iloc[0]
        keywords_entry = kws if isinstance(kws, list) else []

        extra_rows.append({
            "l1_template": l1,
            "source": src,
            "events_per_host": round(n_events / n_hosts, 1),
            "dedup_ratio": round(n_events / max(unique_hashes, 1), 2),
            "burstiness": burst,
            "days_active_ratio": round(n_days / TOTAL_DAYS, 2),
            "burst_5min": burst_5min,
            "day_counts": day_counts,
            "day_labels": DAYS_HUMAN,
            "host_ev": host_ev,
            "host_day_matrix": host_day_matrix,
            "l2_keywords": keywords_entry,
        })
    extra = pd.DataFrame(extra_rows)
    drill = drill.merge(extra, on=["l1_template", "source"], how="left")

    # NEW: cross-L2 correlation
    cross_l2 = compute_cross_l2(L0_unique)
    drill["related_l2"] = drill.apply(
        lambda r: cross_l2.get((r["l1_template"], r["source"]), {}), axis=1
    )
    # NEW: stale rule flag
    drill["is_stale"] = drill.apply(compute_stale, axis=1)

    # NEW: per-L1 incidents (series) for drill-down
    def collect_incidents(grp):
        """Group series by (l1_template, source) → list of incident dicts sorted by host."""
        incidents = []
        for _, r in grp.iterrows():
            incidents.append({
                "host": r["host"],
                "service": r.get("service", ""),
                "events": int(r["events_in_series"]),
                "duration_min": round(r["duration_s"] / 60, 1),
                "auto_resolved": bool(r["auto_resolved"]),
            })
        # Sort by events descending
        incidents.sort(key=lambda x: -x["events"])
        return incidents[:50]  # max 50 per L1 to keep payload small

    incident_map = {}
    for (tmpl, src), grp in series.groupby(["l1_template", "source"]):
        incident_map[(tmpl, src)] = collect_incidents(grp)
    drill["incidents"] = drill.apply(
        lambda r: incident_map.get((r["l1_template"], r["source"]), []), axis=1
    )

    def reco(row):
        if row.autoresolve_pct >= 90 and row.avg_lifetime_min <= 5:
            return "Поднять threshold или добавить duration 5m"
        if row.hosts == 1 and row.events >= 50:
            return f"Per-host override порога для {row.host_top}"
        if row.autoresolve_pct >= 75 and row.events >= 100:
            return "Понизить severity или дедуплицировать"
        return "—"

    # need top host per template
    host_top_map = L0_unique.groupby("l1_template")["host"].agg(lambda x: x.value_counts().index[0]).to_dict()
    drill["host_top"] = drill["l1_template"].map(host_top_map)
    # real raw example per (l1_template, source) — first non-empty raw_value
    raw_map = (L0_unique.dropna(subset=["raw_value"])
               .groupby(["l1_template", "source"])["raw_value"].first().to_dict())
    drill["example_l0"] = drill.apply(
        lambda r: raw_map.get((r["l1_template"], r["source"]), str(r["l1_template"])), axis=1
    )
    # severity: dominant per (l1_template, source)
    def dominant_sev(group):
        return group.value_counts().index[0]
    sev_map = L0_unique.groupby(["l1_template", "source"])["severity"].agg(dominant_sev).to_dict()
    drill["severity"] = drill.apply(lambda r: sev_map.get((r["l1_template"], r["source"]), "INFO"), axis=1)
    drill["Рекомендация"] = drill.apply(reco, axis=1)
    drill = drill[[
        "l2_class", "l1_template", "l1_origin", "source", "severity", "rule_id", "example_l0",
        "events", "hosts", "services", "incidents", "autoresolve_pct",
        "avg_lifetime_min", "events_per_host", "dedup_ratio", "burstiness",
        "days_active_ratio",
        "burst_5min", "day_counts", "day_labels", "host_ev", "host_day_matrix", "l2_keywords",
        "related_l2", "is_stale", "incidents",
        "Рекомендация",
    ]]
    drill.columns = [
        "Класс L2", "Шаблон L1", "Как создан L1", "Source", "Severity", "Rule/trigger key",
        "Пример события L0", "Events", "Hosts", "Services", "Инциденты",
        "AutoResolve %", "Среднее время жизни (мин)",
        "Events/host", "Dedup ratio", "Burstiness P95/med", "Days active ratio",
        "burst_5min", "day_counts", "day_labels", "host_ev", "host_day_matrix", "l2_keywords",
        "related_l2", "is_stale", "incidents",
        "Рекомендация",
    ]
    drill["Шаблон L1"] = drill["Шаблон L1"].astype(str).apply(lambda s: s if len(s) <= 100 else s[:97] + "...")
    drill["Пример события L0"] = drill["Пример события L0"].astype(str).apply(
        lambda s: re.sub(r"\s+", " ", s).strip()
    )
    drill["Пример события L0"] = drill["Пример события L0"].apply(
        lambda s: s if len(s) <= 220 else s[:217] + "..."
    )
    drill = drill.sort_values(["Класс L2", "Events"], ascending=[True, False])
    drill.to_csv(OUT / "02_drilldown_l2_to_l1.csv", index=False, encoding="utf-8-sig")

    # ====== Table 3: Top sources ======
    src = L0_unique.groupby("source").agg(events=("rule_id", "count"), hosts=("host", "nunique"))
    src_inc = series.groupby("source").agg(
        incidents=("rule_id", "count"),
        autoresolve_pct=("auto_resolved", lambda x: round(100 * x.mean(), 1)),
    )
    src_top_l2 = L0_unique.groupby("source")["l2_class"].agg(lambda x: x.value_counts().index[0])
    src_top_svc = L0_unique.groupby("source")["service"].agg(lambda x: x.value_counts().index[0])
    src_share = (src["events"] / src["events"].sum() * 100).round(1)
    top_sources = src.join(src_inc).assign(
        top_l2=src_top_l2, top_service=src_top_svc, share_pct=src_share,
    ).reset_index()
    top_sources.columns = ["Source", "Events", "Hosts", "Incidents", "AutoResolve %",
                           "Top L2 class", "Top service", "Доля шума %"]
    top_sources = top_sources.sort_values("Events", ascending=False)
    top_sources.to_csv(OUT / "03_top_sources.csv", index=False, encoding="utf-8-sig")

    # ====== Table 4: Top hosts/services ======
    hs = L0_unique.groupby("host").agg(events=("rule_id", "count"))
    hs_inc = series.groupby("host").agg(
        incidents=("rule_id", "count"),
        autoresolve_pct=("auto_resolved", lambda x: round(100 * x.mean(), 1)),
        avg_lifetime_s=("duration_s", "mean"),
    )
    hs_top_l2 = L0.groupby("host")["l2_class"].agg(lambda x: x.value_counts().index[0])
    hs_service = L0_unique.groupby("host")["service"].agg(lambda x: x.value_counts().index[0])
    top_hosts = hs.join(hs_inc).assign(service=hs_service, top_l2=hs_top_l2).reset_index()
    top_hosts["avg_lifetime_min"] = (top_hosts["avg_lifetime_s"] / 60).round(1)
    top_hosts = top_hosts.drop(columns="avg_lifetime_s")
    top_hosts.columns = ["Host", "Events", "Incidents", "AutoResolve %",
                         "Service", "Top L2 class", "Среднее время жизни (мин)"]
    top_hosts = top_hosts.sort_values("Events", ascending=False).head(20)
    top_hosts.to_csv(OUT / "04_top_hosts_services.csv", index=False, encoding="utf-8-sig")

    # ====== Interactive HTML viewer + JSON/JS data ======
    render_html(main, drill, top_sources, top_hosts, dedup_stats)

    print(f"\n{'=' * 70}")
    print(f"Output ready: {OUT.relative_to(ROOT)}")
    print(f"  CSV: 4 files")
    print(f"  HTML: index.html")
    print(f"  JSON: data.json")
    print(f"  JS:   data.js")
    print(f"{'=' * 70}")


def build_rules_payload():
    """Rules / sources catalog."""
    prom_rows = []
    for r in RULES:
        target = r.get("kpi") or r.get("pattern", "")
        prom_rows.append({
            "id": r["id"],
            "kpi": target,
            "match": "exact" if r["match"] == "=" else "regex",
            "label": r["label"],
            "l2": r["l2"],
            "threshold": f"p95 of baseline day {BASELINE_DAY}",
            "note": "Порог = 95-й перцентиль KPI за нормальный день. Событие = значение выше порога, "
                    "дедуп до 1 события / 5-мин окно на хост.",
        })
    app_meta = {
        "sr_rule":  f"sr < p05 baseline ({BASELINE_DAY}) → CRITICAL · Service success rate drop",
        "mrt_rule": f"mrt > 1.5 × p95 baseline ({BASELINE_DAY}) → WARNING · Response time spike",
        "note": "Данные из metric_app.csv: rr=request_rate, sr=success_rate, mrt=mean_response_time. "
                "Пороги вычислены из нормального дня автоматически.",
    }
    log_meta = {
        "engine": "drain3 (template mining)",
        "sample": f"до {LOG_SAMPLE_PER_DAY:,} строк/день, sort by timestamp, random_state=42 для воспроизводимости",
        "drop": "строки доступа/нагрузочного теста (regex LOG_DROP) отбрасываются",
        "severity_rule": "по prefix-у строки: SEVERE/ERROR/FATAL → CRITICAL, WARN → WARNING, иначе INFO",
        "note": "ШАБЛОНЫ: drain3 кластеризует логи автоматически. Никаких заранее заданных правил — "
                 "L1-шаблонов столько, сколько drain3 нашёл в выборке.",
    }
    return {"prometheus": prom_rows, "app_monitor": app_meta, "log_agent": log_meta}


def render_html(main_df, drill_df, sources_df, hosts_df, dedup_stats):
    payload = {
        "day": DAY_HUMAN,
        "days": DAYS_HUMAN,
        "main": main_df.to_dict(orient="records"),
        "drill": drill_df.to_dict(orient="records"),
        "sources": sources_df.to_dict(orient="records"),
        "hosts": hosts_df.to_dict(orient="records"),
        "rules": build_rules_payload(),
        "dedup": dedup_stats,
        "totals": {
            "events": int(main_df["Событий L0"].sum()),
            "incidents": int(main_df["Инцидентов"].sum()),
            "templates": int(main_df["Шаблонов L1"].sum()),
            "classes": int(len(main_df)),
        },
    }
    json_str = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    # Write data.json — raw JSON dump for debugging
    (OUT / "data.json").write_text(json_str, encoding="utf-8")

    # Write data.js — JS with const DATA = <json>;
    (OUT / "data.js").write_text(f"const DATA = {json_str};", encoding="utf-8")

    # Write index.html — static HTML template (loads data.js via script tag)
    (OUT / "index.html").write_text(HTML_TEMPLATE, encoding="utf-8")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Artimate · Анализатор шума алертов · Bank dataset</title>
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font: 14px/1.45 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #1f2937;
    background: #f6f7f9;
    min-height: 100vh;
  }
  /* ===== Header ===== */
  header.topbar {
    display: flex; align-items: center; gap: 32px;
    padding: 0 32px; height: 64px;
    background: #fff;
    border-bottom: 1px solid #e5e7eb;
    position: sticky; top: 0; z-index: 10;
  }
  .logo { font-weight: 600; font-size: 18px; letter-spacing: 0.3px; color: #4f46e5; }
  .logo .accent { color: #1f2937; font-weight: 400; margin-left: 4px; font-size: 13px; }
  nav.tabs { display: flex; gap: 0; flex: 1; height: 100%; }
  nav.tabs button {
    background: none; border: none; cursor: pointer;
    padding: 0 18px; height: 100%;
    font: inherit; color: #6b7280;
    border-bottom: 2px solid transparent;
    transition: color .15s, border-color .15s;
  }
  nav.tabs button:hover { color: #1f2937; }
  nav.tabs button.active { color: #4f46e5; border-bottom-color: #4f46e5; }
  .search {
    flex: 0 0 320px; height: 36px; padding: 0 14px;
    border: 1px solid #e5e7eb; border-radius: 18px;
    background: #f9fafb; font: inherit; color: #1f2937;
  }
  .search:focus { outline: none; border-color: #c7d2fe; background: #fff; }
  /* ===== Page title ===== */
  .page-title {
    padding: 24px 32px 0;
    display: flex; align-items: baseline; gap: 16px;
  }
  .page-title h1 { margin: 0; font-size: 24px; font-weight: 600; color: #111827; }
  .page-title .meta { color: #6b7280; font-size: 13px; }
  /* ===== Stats strip ===== */
  .stats {
    display: flex; gap: 12px;
    padding: 16px 32px;
  }
  .stat-card {
    background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 12px 16px; min-width: 120px;
  }
  .stat-card .label { color: #6b7280; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
  .stat-card .value { font-size: 22px; font-weight: 600; color: #111827; margin-top: 4px; }
  /* ===== Card / table wrapper ===== */
  .card {
    background: #fff;
    border: 1px solid #e5e7eb; border-radius: 8px;
    margin: 8px 32px 24px;
    overflow: hidden;
  }
  .card-header {
    padding: 14px 18px; border-bottom: 1px solid #e5e7eb;
    font-weight: 600; font-size: 15px;
  }
  /* ===== Tables ===== */
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-weight: 500; color: #6b7280; font-size: 12px;
       text-transform: uppercase; letter-spacing: 0.4px;
       padding: 12px 14px; border-bottom: 1px solid #e5e7eb;
       background: #fafafa; white-space: nowrap; }
  td { padding: 12px 14px; border-bottom: 1px solid #f1f3f5; vertical-align: top; }
  tbody tr:hover { background: #fafbff; }
  tr.l2-row { cursor: pointer; }
  tr.l2-row .toggle { display: inline-block; width: 14px; color: #9ca3af; }
  tr.l2-row.expanded .toggle { color: #4f46e5; }
  tr.l1-host-row { display: none; }
  tr.l1-host-row.show { display: table-row; }
  tr.l1-host-row td { background: #f9fafb; padding: 0 14px 14px; border-bottom: 1px solid #e5e7eb; }
  .nested-table { width: 100%; border: 1px solid #e5e7eb; border-radius: 6px; overflow: hidden; margin-top: 6px; }
  .nested-table th { background: #f3f4f6; padding: 8px 10px; font-size: 11px; }
  .nested-table td { padding: 8px 10px; font-size: 13px; }
  /* ===== Pills / chips for AutoResolve % ===== */
  .pill { display: inline-block; padding: 2px 10px; border-radius: 999px;
          font-size: 12px; font-weight: 500; min-width: 50px; text-align: center; }
  .pill-red { background: #fee2e2; color: #b91c1c; }
  .pill-amber { background: #fef3c7; color: #b45309; }
  .pill-green { background: #d1fae5; color: #047857; }
  .pill-gray { background: #f3f4f6; color: #4b5563; }
  /* ===== Source tag ===== */
  .src-tag { display: inline-block; padding: 2px 8px; border-radius: 4px;
             font-size: 11px; font-weight: 500; background: #eef2ff; color: #4f46e5; }
  .src-tag.prometheus { background: #fff7ed; color: #c2410c; }
  .src-tag.log { background: #ecfdf5; color: #047857; }
  .src-tag.app { background: #fdf4ff; color: #7e22ce; }
  /* ===== Severity chip ===== */
  .sev { display: inline-block; padding: 2px 8px; border-radius: 4px;
         font-size: 11px; font-weight: 600; letter-spacing: 0.3px; }
  .sev-crit { background: #fee2e2; color: #b91c1c; }
  .sev-warn { background: #fef3c7; color: #b45309; }
  .sev-info { background: #e0f2fe; color: #0369a1; }
  .sev-stack { display: inline-flex; gap: 4px; flex-wrap: wrap; }
  /* ===== L1 origin tag ===== */
  .origin-tag { display: inline-block; padding: 2px 8px; border-radius: 4px;
                font-size: 11px; font-weight: 500; background: #f3f4f6; color: #374151; }
  .origin-ml   { background: #fdf4ff; color: #7e22ce; }
  .origin-rule { background: #eff6ff; color: #1d4ed8; }
  /* ===== Dedup card highlight ===== */
  .dedup-card { border-left: 3px solid #f59e0b; }
  /* ===== Verdict cell ===== */
  td.verdict { color: #4b5563; font-style: italic; max-width: 280px; }
  td.template { font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 12px; color: #374151; max-width: 360px; word-break: break-word; }
  td.numeric { text-align: right; font-variant-numeric: tabular-nums; }
  /* ===== Modal ===== */
  .modal-backdrop {
    display: none; position: fixed; inset: 0;
    background: rgba(17, 24, 39, 0.45); z-index: 100;
    align-items: center; justify-content: center;
  }
  .modal-backdrop.show { display: flex; }
  .modal {
    background: #fff; border-radius: 10px; max-width: 720px; width: 90%;
    max-height: 80vh; overflow: auto;
    box-shadow: 0 12px 40px rgba(0,0,0,0.18);
  }
  .modal-head { display: flex; justify-content: space-between; align-items: center;
                padding: 16px 22px; border-bottom: 1px solid #e5e7eb; }
  .modal-head h3 { margin: 0; font-size: 16px; }
  .modal-close { cursor: pointer; background: none; border: none; font-size: 22px; color: #6b7280; }
  .modal-body { padding: 18px 22px; }
  .modal-body dl { margin: 0; display: grid; grid-template-columns: 180px 1fr; gap: 10px 16px; }
  .modal-body dt { color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.4px; }
  .modal-body dd { margin: 0; color: #1f2937; }
  .modal-body pre {
    background: #f3f4f6; padding: 12px; border-radius: 6px; font-size: 12px;
    white-space: pre-wrap; word-break: break-word; margin: 8px 0;
    max-height: 200px; overflow: auto;
  }
  /* ===== Footer ===== */
  footer {
    padding: 18px 32px; color: #6b7280; font-size: 12px;
    border-top: 1px solid #e5e7eb; background: #fff;
    display: flex; justify-content: space-between;
  }
  .hidden { display: none; }
  /* ===== Filter bar ===== */
  .filter-bar {
    display: flex; align-items: center; gap: 14px;
    padding: 10px 32px; background: #fff;
    border-bottom: 1px solid #e5e7eb;
    font-size: 13px; color: #4b5563;
  }
  .filter-bar .label { color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.4px; }
  .filter-bar label.cb { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; }
  .filter-bar label.cb input { margin: 0; cursor: pointer; }
  /* ===== Rules tab ===== */
  .rules-section { padding: 18px 22px; }
  .rules-section h3 { margin: 0 0 8px 0; font-size: 15px; color: #111827; }
  .rules-section .subtitle { color: #6b7280; font-size: 13px; margin-bottom: 14px; line-height: 1.55; }
  .rules-section table { margin-bottom: 4px; }
  .rules-section + .rules-section { border-top: 1px solid #e5e7eb; margin-top: 8px; padding-top: 18px; }
  .rules-note { background: #fef3c7; color: #92400e; padding: 8px 12px; border-radius: 6px;
                font-size: 12px; line-height: 1.55; margin-bottom: 12px; }
  .rules-note.real { background: #d1fae5; color: #065f46; }
  .rules-note.neutral { background: #e0f2fe; color: #075985; }
  /* ===== Class profile block ===== */
  .class-profile { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 12px 16px; margin-bottom: 10px; }
  .cp-header { font-weight: 600; font-size: 14px; color: #166534; margin-bottom: 8px; }
  .cp-body { display: flex; gap: 20px; flex-wrap: wrap; }
  .cp-section { font-size: 13px; color: #374151; }
  .cp-label { color: #6b7280; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; font-weight: 600; }
  .cp-charts { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 8px; }
  .cp-chart { background: #fff; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px; }
  .cp-chart-label { font-size: 11px; color: #6b7280; margin-bottom: 4px; white-space: nowrap; }
  /* ===== Path chain ===== */
  .path-chain { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; margin-bottom: 16px; }
  .path-step { display: flex; align-items: center; gap: 8px; padding: 6px 0; }
  .path-label { display: inline-block; min-width: 60px; padding: 2px 8px; border-radius: 4px; background: #eef2ff; color: #4f46e5; font-size: 11px; font-weight: 600; text-align: center; }
  .path-arrow { color: #9ca3af; font-size: 16px; margin-left: 26px; }
  /* ===== Stale flag ===== */
  .stale-flag { background: #fef3c7; border: 1px solid #f59e0b; border-radius: 6px; padding: 10px 14px; margin-bottom: 16px; font-size: 13px; color: #92400e; }
  .stale-badge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; background: #fef3c7; color: #b45309; cursor: help; }
  /* ===== Cross-L2 badge ===== */
  .cross-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; background: #fdf4ff; color: #7e22ce; cursor: pointer; }
  .cross-popover { position: fixed; z-index: 200; background: #1f2937; color: #fff; font-size: 12px; padding: 8px 12px; border-radius: 6px; max-width: 300px; white-space: normal; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
  /* ===== Tooltips ===== */
  th.has-tip { cursor: help; position: relative; }
  .tip-icon { color: #9ca3af; font-size: 11px; margin-left: 2px; }
  th.has-tip .tip-popover { display: none; position: absolute; z-index: 50; background: #1f2937; color: #fff; font-size: 12px; font-weight: 400; padding: 8px 12px; border-radius: 6px; max-width: 280px; white-space: normal; text-transform: none; letter-spacing: 0; top: 100%; left: 50%; transform: translateX(-50%); margin-top: 4px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
  th.has-tip:hover .tip-popover { display: block; }
  /* ===== Host drill ===== */
  .host-section { font-weight: 600; font-size: 13px; color: #374151; margin: 8px 0 4px; }
  .host-drill-grid { display: flex; gap: 16px; flex-wrap: wrap; }
  .host-drill-col { flex: 1; min-width: 200px; }
  .host-drill-item { font-size: 12px; padding: 2px 0; color: #4b5563; }
</style>
</head>
<body>

<header class="topbar">
  <div class="logo">Artimate<span class="accent">анализатор шума</span></div>
  <nav class="tabs">
    <button class="tab-btn active" data-tab="classes">Классы L2</button>
    <button class="tab-btn" data-tab="sources">Источники</button>
    <button class="tab-btn" data-tab="hosts">Хосты</button>
    <button class="tab-btn" data-tab="rules">Правила внешних алертов</button>
    <button class="tab-btn" data-tab="about">О данных</button>
  </nav>
  <input class="search" placeholder="Поиск по шаблону / host / rule…" id="searchInput">
</header>

<div class="filter-bar">
  <span class="label">Severity:</span>
  <label class="cb"><input type="checkbox" data-sev="CRITICAL" checked> <span class="sev sev-crit">CRIT</span></label>
  <label class="cb"><input type="checkbox" data-sev="WARNING" checked> <span class="sev sev-warn">WARN</span></label>
  <label class="cb"><input type="checkbox" data-sev="INFO" checked> <span class="sev sev-info">INFO</span></label>
  <span style="flex:1"></span>
  <label class="cb"><input type="checkbox" id="staleFilter"> <span style="color:#b45309">⚠ Только устаревшие</span></label>
</div>

<div class="page-title">
  <h1 id="pageTitle">Классы проблем</h1>
  <span class="meta" id="pageMeta"></span>
</div>

<div class="stats" id="statsStrip"></div>

<!-- Tab: classes -->
<section id="tab-classes" class="tab-pane">
  <div class="card">
    <div class="card-header">Главная сводная — кликни на класс L2 для drill-down в шаблоны L1</div>
    <table id="mainTable"></table>
  </div>
</section>

<!-- Tab: sources -->
<section id="tab-sources" class="tab-pane hidden">
  <div class="card">
    <div class="card-header">Самые шумные источники</div>
    <table id="sourcesTable"></table>
  </div>
</section>

<!-- Tab: hosts -->
<section id="tab-hosts" class="tab-pane hidden">
  <div class="card">
    <div class="card-header">Самые шумные host (top-20)</div>
    <table id="hostsTable"></table>
  </div>
</section>

<!-- Tab: rules -->
<section id="tab-rules" class="tab-pane hidden">
  <div class="card">
    <div class="card-header">Источники алертов и правила, по которым строятся события L0</div>
    <div id="rulesContent"></div>
  </div>
</section>

<!-- Tab: about -->
<section id="tab-about" class="tab-pane hidden">
  <div class="card">
    <div class="card-header">О данных</div>
    <div style="padding: 18px 22px; line-height: 1.7;">
      <p><b>Источник данных:</b> OpenRCA Bank dataset, день <span id="aboutDay"></span></p>
      <p><b>Что это:</b> демонстрация классификации алертов по уровням L0 → L1 → L2 на реальных данных.</p>
      <ul>
        <li><b>L0 — события</b>: сырые алерты из трёх реальных источников датасета:
          <ul>
            <li><span class="src-tag prometheus">Prometheus</span> пороговые алерты на <code>metric_container.csv</code> — порог = p95 нормального дня</li>
            <li><span class="src-tag app">AppMonitor</span> алерты на <code>metric_app.csv</code> — sr &lt; p05 baseline или mrt &gt; 1.5× p95 baseline</li>
            <li><span class="src-tag log">Log Agent</span> Drain3-шаблоны из <code>log_service.csv</code></li>
          </ul>
        </li>
        <li><b>L1 — шаблоны</b>: повторяющиеся trigger keys (`zbx-cpu`, `log-tpl-N`, `oim-...`)</li>
        <li><b>L2 — классы проблем</b>: 7 семантических групп под Bank (JVM heap & GC, Slow SQL, Disk IO, …)</li>
      </ul>
      <p><b>AutoResolve%</b>: серия событий считается самоликвидировавшейся, если в ней <b>≤ 5 событий ИЛИ длительность ≤ 10 минут</b> — то есть алерт «потух сам» без вмешательства. Высокий % при большом потоке событий = устаревшее шумное правило: моргает и тушится без реальной причины. Серия = последовательность срабатываний шаблона на одном хосте с разрывом &lt; 5 минут.</p>
      <p><b>Дубли</b>: события на одном host в окне 1 мин из ≥ 2 источников переклассифицируются в класс «Дубли из разных систем».</p>
      <p><b>Дополнительные метрики шума</b> (в drill-down):</p>
      <ul>
        <li><b>Ev/host</b> = events / unique_hosts — среднее число событий на один хост. Высокое = шум сосредоточен на 1-2 хостах (per-host issue).</li>
        <li><b>Dedup</b> = events / unique(host + 5-min bucket) — среднее число дубликатов на одну пару (host, 5 мин). Значение > 1 = повторяющийся шум за одно окно.</li>
        <li><b>Burstiness</b> = P95 / median количеств событий по 5-мин окнам (per host). Высокое = редкие, но плотные всплески.</li>
        <li><b>Days active</b> = days_active / total_days. 1.0 = постоянный шум, &lt; 1 = эпизодический.</li>
      </ul>
    </div>
      <p><b>Drain3 cluster #N</b>: Drain3 — наш собственный алгоритм кластеризации логов. Мы (AIOps) сами обрабатываем сырые логи через Drain3: он автоматически группирует похожие строки в шаблоны, заменяя переменные части (IP, числа, ID) на &lt;*&gt;. «Cluster #23» означает «23-й уникальный шаблон, найденный Drain3 в логах». Это порядковый номер, никакой семантики в нём нет. То есть: Log Agent → сырые строки → Drain3 кластеризует → L1-шаблон №23 → мы назначаем L2-класс по ключевым словам.</p>
      <p><b>ServiceTest1..11</b>: замаскированные имена сервисов из оригинального датасета OpenRCA Bank. Реальные имена заменены на абстрактные для конфиденциальности.</p>
  </div>
</section>

<!-- Modal -->
<div class="modal-backdrop" id="modal">
  <div class="modal">
    <div class="modal-head">
      <h3 id="modalTitle">—</h3>
      <button class="modal-close" onclick="closeModal()">&#x2715;</button>
    </div>
    <div class="modal-body" id="modalBody"></div>
  </div>
</div>

<footer>
  <span>© Artimate · OpenRCA Bank dataset</span>
  <span>v0.1 · spike</span>
</footer>

<script src="data.js"></script>
<script>

function pillFor(autoR) {
  const v = Number(autoR);
  let cls = "pill-gray";
  if (v >= 90) cls = "pill-red";
  else if (v >= 70) cls = "pill-amber";
  else if (v < 50) cls = "pill-green";
  return `<span class="pill ${cls}">${v.toFixed(1)}%</span>`;
}

function srcTag(src) {
  const s = src.toLowerCase();
  const cls = s.includes("prometheus") ? "prometheus"
    : s.includes("log") ? "log"
    : s.includes("app") ? "app" : "";
  return `<span class="src-tag ${cls}">${src}</span>`;
}

function sevChip(sev) {
  const map = {CRITICAL: "sev-crit", WARNING: "sev-warn", INFO: "sev-info"};
  const cls = map[sev] || "sev-info";
  return `<span class="sev ${cls}">${sev}</span>`;
}

function sevStack(crit, warn, info) {
  const parts = [];
  if (crit > 0 && SEV_FILTER.CRITICAL) parts.push(`<span class="sev sev-crit">${fmtNum(crit)}</span>`);
  if (warn > 0 && SEV_FILTER.WARNING) parts.push(`<span class="sev sev-warn">${fmtNum(warn)}</span>`);
  if (info > 0 && SEV_FILTER.INFO) parts.push(`<span class="sev sev-info">${fmtNum(info)}</span>`);
  return `<div class="sev-stack">${parts.join("")}</div>`;
}

function fmtNum(n) {
  const v = Number(n);
  if (isNaN(v)) return "—";
  return v.toLocaleString("ru-RU");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

// ===== SVG chart helpers =====
function sparklineSVG(data, width, height, color) {
  if (!data || data.length < 2) return "";
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = Math.max(max - min, 1);
  const stepX = width / (data.length - 1);
  const pts = data.map((v, i) =>
    `${(i * stepX).toFixed(1)},${(height - ((v - min) / range) * (height - 4)).toFixed(1)}`
  ).join(" ");
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
}
function barChartSVG(data, width, height, color) {
  if (!data || data.length === 0) return "";
  const max = Math.max(...data, 1);
  const barW = Math.max(2, Math.floor(width / data.length) - 1);
  const bars = data.map((v, i) => {
    const h = Math.max(1, (v / max) * (height - 4));
    return `<rect x="${i * (barW + 1)}" y="${height - h - 2}" width="${barW}" height="${h}" fill="${color}" rx="1"/>`;
  }).join("");
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${bars}</svg>`;
}
function stackedBarSVG(hostDayMatrix, dayLabels, dayTotals, width) {
  const hosts = Object.keys(hostDayMatrix).sort();
  if (!hosts.length || !dayLabels || !dayLabels.length) return "";
  const maxVal = Math.max(...dayTotals, 1);
  const nDays = dayLabels.length;
  const barW = Math.max(6, Math.floor((width - 30) / nDays) - 2);
  const barGap = 2;
  const chartH = 60;
  const palette = ["#4f46e5","#059669","#b45309","#7c3aed","#dc2626","#0891b2","#ca8a04","#be185d","#65a30d","#1d4ed8"];
  // Build per-day stacks
  let dayHtml = "";
  for (let di = 0; di < nDays; di++) {
    const day = dayLabels[di];
    let yOff = chartH - 2;
    let segs = "";
    hosts.forEach((h, hi) => {
      const cnt = (hostDayMatrix[h] && hostDayMatrix[h][day]) || 0;
      if (cnt > 0) {
        const segH = Math.max(1, (cnt / maxVal) * (chartH - 4));
        const color = palette[hi % palette.length];
        segs += `<rect x="0" y="${yOff - segH}" width="${barW}" height="${segH}" fill="${color}" rx="0.5"/><title>${escapeHtml(h)}: ${cnt} (${day})</title>`;
        yOff -= segH;
      }
    });
    const x = 15 + di * (barW + barGap);
    dayHtml += `<g transform="translate(${x}, 0)">${segs}</g>`;
  }
  return `<svg width="${width}" height="${chartH + 4}" viewBox="0 0 ${width} ${chartH + 4}">${dayHtml}</svg>`;
}

// ===== Tooltips =====
const TOOLTIPS = {
  "Events/host": "Событий на хост = total_events / unique_hosts. Показывает неравномерность: если один хост даёт >2x от среднего — правило бьёт избыточно по одному хосту, нужен per-host override.",
  "Dedup ratio": "events / unique(host + 5min). > 10 — плохая дедупликация.",
  "Burstiness P95/med": "P95 / median событий в 5-мин окнах. > 2.0 — есть аномальные всплески. ~1.0 — равномерный шум.",
  "Days active ratio": "Доля дней с событиями. > 0.8 — хронический шум. < 0.5 — эпизодический.",
  "AutoResolve %": "Доля авто-закрытых инцидентов. 90%+ при низком TTL — ложное срабатывание.",
  "Среднее время жизни (мин)": "Среднее время жизни инцидента. < 5 мин при AutoR ≥ 95% — ложное срабатывание.",
};
function thWithTooltip(label, tipKey) {
  const tip = TOOLTIPS[tipKey] || "";
  if (!tip) return `<th>${label}</th>`;
  return `<th class="has-tip">${label} <span class="tip-icon">ⓘ</span><span class="tip-popover">${tip}</span></th>`;
}

// ===== Clickable source chips =====
function srcTagLink(s) {
  const cls = {Prometheus: "prometheus", "Log Agent": "log", AppMonitor: "app"}[s] || "";
  const safe = escapeHtml(s);
  return `<a href="#" class="src-tag ${cls}" onclick="switchTab('rules');return false">${safe}</a>`;
}
function switchTab(tab) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab-pane").forEach(p => p.classList.toggle("hidden", p.id !== "tab-" + tab));
  document.getElementById("pageTitle").textContent = TAB_TITLES[tab] || tab;
}

// ===== Cross-L2 badge =====
function crossL2Badge(className) {
  const rows = DATA.drill.filter(r => r["Класс L2"] === className && r.related_l2 && Object.keys(r.related_l2).length > 0);
  if (rows.length === 0) return "";
  const related = {};
  rows.forEach(r => Object.entries(r.related_l2).forEach(([l2, cnt]) => { related[l2] = (related[l2] || 0) + cnt; }));
  const entries = Object.entries(related).sort((a, b) => b[1] - a[1]);
  const text = entries.map(([l2, cnt]) => `${escapeHtml(l2)}: ${fmtNum(cnt)}`).join("\\n");
  const total = entries.reduce((s, e) => s + e[1], 0);
  return `<span class="cross-badge" title="${text}">+${entries.length} пересечений</span>`;
}

// ===== Class profile block =====
function renderClassProfile(className, drillRows) {
  if (!drillRows || drillRows.length === 0) return "";
  const first = drillRows[0];
  const kw = (first.l2_keywords && first.l2_keywords.length > 0) ? first.l2_keywords : ["(default: всё неспецифичное)"];
  const sources = [...new Set(drillRows.map(r => r["Source"]))];
  const totalE = drillRows.reduce((s, r) => s + r["Events"], 0);
  let html = `<div class="class-profile"><div class="cp-header">Как AIOps определила этот класс</div><div class="cp-body">
    <div class="cp-section"><span class="cp-label">Ключевые слова:</span> <code>${kw.join(", ")}</code></div>
    <div class="cp-section"><span class="cp-label">Источники:</span> ${sources.map(s => srcTagLink(s)).join(" ")}</div>
    <div class="cp-section"><span class="cp-label">Всего:</span> ${fmtNum(totalE)} событий</div>
  </div></div>`;
  if (first.burst_5min && first.burst_5min.length >= 2) {
    const bv = first["Burstiness P95/med"] || 0;
    const burstColor = bv > 2 ? "#b45309" : "#4f46e5";
    html += `<div class="cp-charts">
      <div class="cp-chart"><div class="cp-chart-label">Burst ${bv > 2 ? '(⚠ пики)' : '(равномерно)'} P95/med=${bv}</div>${sparklineSVG(first.burst_5min, 200, 40, burstColor)}</div>
      <div class="cp-chart"><div class="cp-chart-label">Дни (${first.day_counts ? first.day_counts.filter(d => d > 0).length + '/' + first.day_counts.length : '—'})</div>${barChartSVG(first.day_counts || [], 200, 40, "#059669")}</div>
      <div class="cp-chart"><div class="cp-chart-label">Распределение по хостам/дням</div>${stackedBarSVG(first.host_day_matrix || {}, first.day_labels || [], first.day_counts || [], 220)}</div>
    </div>`;
  }
  return html;
}

// ===== Stale =====
function staleBadge(row) {
  if (!row.is_stale) return "";
  return ` <span class="stale-badge" title="Бьёт ${Math.round((row["Days active ratio"]||0)*10)}/10 дней, ${row["AutoResolve %"]}% auto-resolve, TTL ${row["Среднее время жизни (мин)"]} мин">⚠ Устарело</span>`;
}

// ===== Host drill =====
function toggleHost(i) {
  const tr = document.querySelector(`tr.host-row[data-i="${i}"]`);
  const drillTr = document.getElementById(`host-drill-${i}`);
  const expanded = tr.classList.toggle("expanded");
  tr.querySelector(".toggle").textContent = expanded ? "▼" : "▶";
  if (expanded) {
    drillTr.querySelector("td").innerHTML = renderHostDetail(DATA.hosts[i]["Host"]);
    drillTr.classList.add("show");
  } else {
    drillTr.classList.remove("show");
  }
}
function renderHostDetail(hostName) {
  const rows = DATA.drill.filter(r => r.host_ev && r.host_ev[hostName] !== undefined);
  const byL2 = {};
  rows.forEach(r => { const l2 = r["Класс L2"]; if (!byL2[l2]) byL2[l2] = []; byL2[l2].push(r); });
  let html = '<div class="host-drill-grid">';
  Object.entries(byL2).forEach(([l2, l1rows]) => {
    html += `<div class="host-drill-col"><div class="host-section">${escapeHtml(l2)}</div>`;
    l1rows.forEach(r => {
      const ev = r.host_ev[hostName] || 0;
      html += `<div class="host-drill-item">${escapeHtml(r["Rule/trigger key"])} — ${fmtNum(ev)} соб.${r.is_stale ? ' ⚠' : ''}</div>`;
    });
    html += '</div>';
  });
  html += '</div>';
  return html;
}

// ===== Stale filter state =====
let staleOnly = false;

// ===== Stats strip =====
function renderStats() {
  const t = DATA.totals;
  const d = DATA.dedup;
  const dedupPct = d ? (100 * d.deduplicated / Math.max(d.received, 1)).toFixed(1) : "—";
  document.getElementById("statsStrip").innerHTML = `
    <div class="stat-card"><div class="label">Получено L0</div><div class="value">${fmtNum(d ? d.received : t.events)}</div></div>
    <div class="stat-card dedup-card" title="${d ? d.criterion : ''}">
      <div class="label">Дедуплицировано <span style="color:#9ca3af;font-size:10px">▼ Центр интеграции</span></div>
      <div class="value" style="color:#b45309">${d ? fmtNum(d.deduplicated) : '—'} <span style="font-size:13px;color:#9ca3af">${dedupPct}%</span></div>
    </div>
    <div class="stat-card"><div class="label">Уникальных L0</div><div class="value">${fmtNum(t.events)}</div></div>
    <div class="stat-card"><div class="label">Классов L2</div><div class="value">${t.classes}</div></div>
    <div class="stat-card"><div class="label">Шаблонов L1</div><div class="value">${fmtNum(t.templates)}</div></div>
    <div class="stat-card"><div class="label">Инцидентов (серий)</div><div class="value">${fmtNum(t.incidents)}</div></div>`;
  const nd = DATA.days.length;
  document.getElementById("pageMeta").textContent =
    `Bank · ${DATA.days.join(", ")} · ${nd} ${nd===1?'день':(nd<5?'дня':'дней')} · ${t.classes} классов · ${fmtNum(t.events)} уникальных событий`;
  document.getElementById("aboutDay").textContent = DATA.days.join(", ");
}

// ===== Main table (Classes L2 with drill-down) =====
function renderMain() {
  const cols = [
    {k:"#", label:"#"},
    {k:"Класс проблемы L2", label:"Класс L2"},
    {k:"Что входит внутрь, L1", label:"Что входит внутрь, L1"},
    {k:"Источники", label:"Источники"},
    {k:"_severity", label:"Severity"},
    {k:"Событий L0", label:"L0", num:true},
    {k:"Шаблонов L1", label:"L1", num:true},
    {k:"Инцидентов", label:"Инц.", num:true},
    {k:"AutoResolve %", label:"AutoR%"},
    {k:"Среднее время жизни (мин)", label:"TTL мин", num:true},
    {k:"Самый шумный источник", label:"Top src"},
    {k:"Самый шумный host", label:"Top host"},
    {k:"Самый шумный service", label:"Top svc"},
    {k:"_cross_l2", label:"Cross-L2"},
    {k:"Вывод", label:"Вывод"},
  ];
  let h = "<thead><tr><th></th>";
  cols.forEach(c => h += `<th class="${c.num?'numeric':''}">${c.label}</th>`);
  h += "</tr></thead><tbody>";
  DATA.main.forEach((row, i) => {
    // stale filter
    if (staleOnly) {
      const className = row["Класс проблемы L2"];
      const hasStale = DATA.drill.some(r => r["Класс L2"] === className && r.is_stale);
      if (!hasStale) return;
    }
    h += `<tr class="l2-row" data-i="${i}" onclick="toggleClass(${i})">
            <td><span class="toggle">▶</span></td>`;
    cols.forEach(c => {
      const v = row[c.k];
      if (c.k === "_severity") h += `<td>${sevStack(row["CRITICAL"]||0, row["WARNING"]||0, row["INFO"]||0)}</td>`;
      else if (c.k === "AutoResolve %") h += `<td>${pillFor(v)}</td>`;
      else if (c.k === "Источники") h += `<td>${String(v).split(",").map(s => srcTagLink(s.trim())).join(" ")}</td>`;
      else if (c.k === "Самый шумный источник") h += `<td>${srcTagLink(v)}</td>`;
      else if (c.k === "Вывод") h += `<td class="verdict">${escapeHtml(v)}</td>`;
      else if (c.k === "_cross_l2") h += `<td>${crossL2Badge(row["Класс проблемы L2"])}</td>`;
      else if (c.num) h += `<td class="numeric">${fmtNum(v)}</td>`;
      else h += `<td>${escapeHtml(v)}</td>`;
    });
    h += "</tr>";
    h += `<tr class="l1-host-row" id="drill-${i}"><td colspan="${cols.length+1}"></td></tr>`;
  });
  h += "</tbody>";
  document.getElementById("mainTable").innerHTML = h;
}

function toggleClass(i) {
  const tr = document.querySelector(`tr.l2-row[data-i="${i}"]`);
  const drillTr = document.getElementById(`drill-${i}`);
  const expanded = tr.classList.toggle("expanded");
  tr.querySelector(".toggle").textContent = expanded ? "▼" : "▶";
  if (expanded) {
    const className = DATA.main[i]["Класс проблемы L2"];
    const rows = DATA.drill.filter(r => r["Класс L2"] === className);
    drillTr.querySelector("td").innerHTML = renderClassProfile(className, rows) + renderDrill(rows);
    drillTr.classList.add("show");
  } else {
    drillTr.classList.remove("show");
  }
}

function renderDrill(rows) {
  rows = rows.filter(r => SEV_FILTER[r["Severity"]] !== false);
  let h = `<table class="nested-table"><thead><tr>
    <th>Шаблон L1</th><th>Как создан</th><th>Source</th><th>Severity</th><th>Trigger</th>
    <th>Пример события L0</th><th>Events</th><th>Hosts</th><th>Инц.</th>
    ${thWithTooltip("AutoR%", "AutoResolve %")}
    ${thWithTooltip("TTL мин", "Среднее время жизни (мин)")}
    ${thWithTooltip("Ev/host", "Events/host")}
    ${thWithTooltip("Dedup", "Dedup ratio")}
    ${thWithTooltip("Burst", "Burstiness P95/med")}
    ${thWithTooltip("Дни", "Days active ratio")}
    <th>Рекомендация</th>
  </tr></thead><tbody>`;
  rows.forEach((r, idx) => {
    const originCls = (r["Как создан L1"]||"").includes("Drain3") ? "origin-ml"
      : (r["Как создан L1"]||"").includes("metric") ? "origin-rule" : "";
    h += `<tr style="cursor:pointer" onclick='openModal(${escapeHtml(JSON.stringify(r))})'>
      <td class="template">${escapeHtml(r["Шаблон L1"])}</td>
      <td><span class="origin-tag ${originCls}" title="${escapeHtml(r["Как создан L1"]||"")}">${escapeHtml((r["Как создан L1"]||"").split("·")[0].trim())}</span></td>
      <td>${srcTagLink(r["Source"])}</td>
      <td>${sevChip(r["Severity"])}</td>
      <td><code>${escapeHtml(r["Rule/trigger key"])}</code></td>
      <td class="template">${escapeHtml(r["Пример события L0"])}</td>
      <td class="numeric">${fmtNum(r["Events"])}</td>
      <td class="numeric">${r["Hosts"]}</td>
      <td class="numeric">${fmtNum(r["Инциденты"])}</td>
      <td>${pillFor(r["AutoResolve %"])}</td>
      <td class="numeric">${r["Среднее время жизни (мин)"]}</td>
      <td class="numeric">${fmtNum(r["Events/host"])}</td>
      <td class="numeric">${r["Dedup ratio"]}</td>
      <td class="numeric">${r["Burstiness P95/med"]}</td>
      <td class="numeric">${r["Days active ratio"]}</td>
      <td class="verdict">${escapeHtml(r["Рекомендация"])}${staleBadge(r)}</td>
    </tr>`;
  });
  h += "</tbody></table>";
  return h;
}

// ===== Sources table =====
function renderSources() {
  let h = `<thead><tr>
    <th>Source</th><th class="numeric">Events</th><th class="numeric">Hosts</th>
    <th class="numeric">Incidents</th><th>AutoResolve %</th><th>Top L2 class</th>
    <th>Top service</th><th class="numeric">Доля шума %</th>
  </tr></thead><tbody>`;
  DATA.sources.forEach(r => {
    h += `<tr>
      <td>${srcTagLink(r["Source"])}</td>
      <td class="numeric">${fmtNum(r["Events"])}</td>
      <td class="numeric">${r["Hosts"]}</td>
      <td class="numeric">${fmtNum(r["Incidents"])}</td>
      <td>${pillFor(r["AutoResolve %"])}</td>
      <td>${escapeHtml(r["Top L2 class"])}</td>
      <td>${escapeHtml(r["Top service"])}</td>
      <td class="numeric">${r["Доля шума %"]}%</td>
    </tr>`;
  });
  h += "</tbody>";
  document.getElementById("sourcesTable").innerHTML = h;
}

// ===== Hosts table =====
function renderHosts() {
  let h = `<thead><tr>
    <th></th><th>Host</th><th>Service</th><th class="numeric">Events</th>
    <th class="numeric">Incidents</th><th>AutoResolve %</th><th>Top L2 class</th>
    <th class="numeric">TTL мин</th>
  </tr></thead><tbody>`;
  DATA.hosts.forEach((r, i) => {
    h += `<tr class="host-row" data-i="${i}" onclick="toggleHost(${i})" style="cursor:pointer">
      <td><span class="toggle">▶</span></td>
      <td><b>${escapeHtml(r["Host"])}</b></td>
      <td>${escapeHtml(r["Service"])}</td>
      <td class="numeric">${fmtNum(r["Events"])}</td>
      <td class="numeric">${fmtNum(r["Incidents"])}</td>
      <td>${pillFor(r["AutoResolve %"])}</td>
      <td>${escapeHtml(r["Top L2 class"])}</td>
      <td class="numeric">${r["Среднее время жизни (мин)"]}</td>
    </tr>`;
    h += `<tr class="l1-host-row" id="host-drill-${i}"><td colspan="8"></td></tr>`;
  });
  h += "</tbody>";
  document.getElementById("hostsTable").innerHTML = h;
}

// ===== Modal for L1 row detail =====
function openModal(row) {
  document.getElementById("modalTitle").textContent = row["Класс L2"] + " — " + row["Rule/trigger key"];
  const body = document.getElementById("modalBody");
  const kw = (row.l2_keywords && row.l2_keywords.length) ? row.l2_keywords.join(", ") : "";
  const pathHTML = `<div class="path-chain">
    <div class="path-step"><span class="path-label">L0</span><code style="font-size:11px">${escapeHtml(String(row["Пример события L0"]||"").substring(0,120))}</code></div>
    <div class="path-arrow">↓</div>
    <div class="path-step"><span class="path-label">Источник</span>${srcTagLink(row["Source"])} · правило <code>${escapeHtml(row["Rule/trigger key"])}</code></div>
    <div class="path-arrow">↓</div>
    <div class="path-step"><span class="path-label">L2</span>${escapeHtml(row["Класс L2"])}${kw ? ` <span style="color:#6b7280;font-size:12px">(ключевые слова: ${kw})</span>` : ""}</div>
  </div>`;
  const staleHTML = row.is_stale ? `<div class="stale-flag">⚠ Устаревшее правило — бьёт ${Math.round((row["Days active ratio"]||0)*10)}/10 дней, ${row["AutoResolve %"]}% auto-resolve, TTL ${row["Среднее время жизни (мин)"]} мин. Рекомендация: поднять порог в источнике или добавить duration.</div>` : "";

  // Build incidents table
  const incs = row.incidents || [];
  let incHTML = "";
  if (incs.length > 0) {
    // Find max events for bar scaling
    const maxEv = Math.max(...incs.map(i => i.events), 1);
    incHTML = `<div style="margin-top:14px"><b>Инциденты (${fmtNum(row["Инциденты"] || 0)} серий, показаны ${incs.length} крупнейших)</b>
    <div style="max-height:260px;overflow-y:auto;margin-top:6px">
    <table class="nested-table" style="margin-top:0"><thead><tr>
      <th>Host</th><th>Service</th><th class="numeric">Событий</th><th class="numeric">Длит. (мин)</th><th class="numeric">AutoR</th><th>Бар</th>
    </tr></thead><tbody>`;
    incs.forEach(inc => {
      const barW = Math.max(2, (inc.events / maxEv) * 80);
      const autoColor = inc.auto_resolved ? "#d1fae5" : "#fee2e2";
      const autoText = inc.auto_resolved ? "✓" : "✗";
      incHTML += `<tr>
        <td><b>${escapeHtml(inc.host)}</b></td>
        <td>${escapeHtml(inc.service)}</td>
        <td class="numeric">${fmtNum(inc.events)}</td>
        <td class="numeric">${inc.duration_min}</td>
        <td style="background:${autoColor};text-align:center;font-size:12px">${autoText}</td>
        <td><svg width="100" height="14" viewBox="0 0 100 14"><rect x="0" y="3" width="${barW}" height="8" fill="#4f46e5" rx="2"/></svg></td>
      </tr>`;
    });
    incHTML += `</tbody></table></div></div>`;
  }

  body.innerHTML = pathHTML + staleHTML + `
    <dl>
      <dt>Источник</dt><dd>${srcTagLink(row["Source"])}</dd>
      <dt>Severity</dt><dd>${sevChip(row["Severity"])}</dd>
      <dt>Trigger key</dt><dd><code>${escapeHtml(row["Rule/trigger key"])}</code></dd>
      <dt>Как создан L1</dt><dd><span class="origin-tag ${(row["Как создан L1"]||"").includes("Drain3")?"origin-ml":"origin-rule"}">${escapeHtml(row["Как создан L1"]||"—")}</span></dd>
      <dt>Пример L0 (raw)</dt><dd><pre>${escapeHtml(row["Пример события L0"])}</pre></dd>
      <dt>Агрегаты</dt><dd>${fmtNum(row["Events"])} событий · ${fmtNum(row["Инциденты"] || 0)} инц. · ${pillFor(row["AutoResolve %"])} · TTL ${row["Среднее время жизни (мин)"]} мин · Ev/host ${fmtNum(row["Events/host"])} · Burst ${row["Burstiness P95/med"]} · Дни ${row["Days active ratio"]}</dd>
      <dt>Рекомендация</dt><dd><b>${escapeHtml(row["Рекомендация"])}</b></dd>
    </dl>` + incHTML;
  document.getElementById("modal").classList.add("show");
  event.stopPropagation();
}
function closeModal() {
  document.getElementById("modal").classList.remove("show");
}
document.getElementById("modal").addEventListener("click", e => {
  if (e.target.id === "modal") closeModal();
});

// ===== Severity filter =====
const SEV_FILTER = {CRITICAL: true, WARNING: true, INFO: true};
document.querySelectorAll(".filter-bar input[data-sev]").forEach(cb => {
  cb.addEventListener("change", () => {
    SEV_FILTER[cb.dataset.sev] = cb.checked;
    renderMain();
  });
});

// ===== Stale filter =====
document.getElementById("staleFilter").addEventListener("change", function() {
  staleOnly = this.checked;
  renderMain();
});

// ===== Rules tab =====
function renderRules() {
  const r = DATA.rules;
  let h = "";
  // Prometheus
  h += `<div class="rules-section">
    <h3>Prometheus — пороговые алерты на инфраструктурных метриках</h3>
    <div class="subtitle">7 правил на <code>metric_container.csv</code>. Порог = p95 нормального дня <b>${r.prometheus[0]?.threshold || ''}</b>. Каждое значение выше порога = одно событие L0 (дедуп до 1 / 5-мин окно / хост).</div>
    <div class="rules-note real">РЕАЛЬНЫЕ ДАННЫЕ: пороги вычислены из metric_container.csv за baseline-день автоматически.</div>
    <table><thead><tr>
      <th>Trigger ID</th><th>KPI / pattern</th><th>Тип</th><th>Метка алерта</th>
      <th>Threshold</th><th>L2-класс</th>
    </tr></thead><tbody>`;
  r.prometheus.forEach(x => {
    h += `<tr>
      <td><code>${escapeHtml(x.id)}</code></td>
      <td class="template">${escapeHtml(x.kpi)}</td>
      <td>${escapeHtml(x.match)}</td>
      <td>${escapeHtml(x.label)}</td>
      <td>${escapeHtml(x.threshold)}</td>
      <td>${escapeHtml(x.l2)}</td>
    </tr>`;
  });
  h += `</tbody></table>
    <div class="subtitle" style="margin-top:10px"><b>Severity:</b> <code>ratio = value / threshold</code>; <span class="sev sev-crit">CRIT</span> при ratio ≥ 2.0, <span class="sev sev-warn">WARN</span> при ratio ≥ 1.5, иначе <span class="sev sev-info">INFO</span>.</div>
  </div>`;
  // AppMonitor
  h += `<div class="rules-section">
    <h3>AppMonitor — алерты уровня сервиса</h3>
    <div class="subtitle">Данные из <code>metric_app.csv</code>. Два правила на sr (success rate) и mrt (mean response time). Пороги из нормального дня.</div>
    <div class="rules-note real">РЕАЛЬНЫЕ ДАННЫЕ: metric_app.csv содержит sr, mrt, rr по 11 сервисам. Пороги автоматические.</div>
    <table><thead><tr><th>Правило</th><th>Значение</th></tr></thead><tbody>
      <tr><td><b>SR drop</b></td><td>${escapeHtml(r.app_monitor.sr_rule)}</td></tr>
      <tr><td><b>MRT spike</b></td><td>${escapeHtml(r.app_monitor.mrt_rule)}</td></tr>
      <tr><td><b>Примечание</b></td><td>${escapeHtml(r.app_monitor.note)}</td></tr>
    </tbody></table>
  </div>`;
  // Log Agent
  h += `<div class="rules-section">
    <h3>Log Agent — drain3 (template mining)</h3>
    <div class="subtitle">Никаких заранее заданных правил. Лог-строки кластеризуются автоматически: drain3 строит дерево шаблонов, где общие токены остаются как есть, а вариативные части заменяются на <code>&lt;*&gt;</code>. L1-шаблонов столько, сколько drain3 нашёл в данных.</div>
    <div class="rules-note neutral">ШАБЛОНЫ: ${escapeHtml(r.log_agent.engine)}. ${escapeHtml(r.log_agent.note)}</div>
    <table><thead><tr><th style="width:200px">Параметр</th><th>Значение</th></tr></thead><tbody>
      <tr><td><b>Engine</b></td><td>${escapeHtml(r.log_agent.engine)}</td></tr>
      <tr><td><b>Сэмплирование</b></td><td>${escapeHtml(r.log_agent.sample)}</td></tr>
      <tr><td><b>Фильтр на входе</b></td><td>${escapeHtml(r.log_agent.drop)}</td></tr>
      <tr><td><b>Severity</b></td><td>${escapeHtml(r.log_agent.severity_rule)}</td></tr>
    </tbody></table>
    <div class="subtitle" style="margin-top:10px">L2-класс шаблона определяется regex-эвристикой по содержимому: ключевые слова <code>GC/CMS/Heap/ParNew</code> → JVM, <code>Query_time/InnoDB</code> → Slow SQL, <code>deploy/Tomcat/Catalina</code> → Tomcat-рестарты, и т.д. Полный список — в коде <code>L2_LOG_KEYWORDS</code>.</div>
  </div>`;
  document.getElementById("rulesContent").innerHTML = h;
}

// ===== Tabs =====
const TAB_TITLES = {
  classes: "Классы проблем",
  sources: "Источники алертов",
  hosts: "Хосты",
  rules: "Правила и источники",
  about: "О данных",
};
document.querySelectorAll(".tab-btn").forEach(b => {
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    document.querySelectorAll(".tab-pane").forEach(x => x.classList.add("hidden"));
    document.getElementById("tab-" + b.dataset.tab).classList.remove("hidden");
    document.getElementById("pageTitle").textContent = TAB_TITLES[b.dataset.tab];
  });
});

// ===== Search (filter rows) =====
document.getElementById("searchInput").addEventListener("input", e => {
  const q = e.target.value.toLowerCase().trim();
  document.querySelectorAll("table tbody tr").forEach(tr => {
    if (tr.classList.contains("l1-host-row")) return;
    const text = tr.textContent.toLowerCase();
    tr.style.display = (!q || text.includes(q)) ? "" : "none";
  });
});

// ===== Bootstrap =====
renderStats();
renderMain();
renderSources();
renderHosts();
renderRules();
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()
