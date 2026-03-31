# Phase 3: Monitoring Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить конфигурируемые инструменты мониторинга для metrics (ruptures, STL, PyOD, BARO), traces (span, dependency, critical path) и correlation (temporal, topological, noise filter).

**Architecture:** Три новых пакета metrics/, traces/, correlation/ с ABC интерфейсами (тот же паттерн что parsers/). Каждый инструмент = 1 файл, 1 класс. YAML config расширяется. Pipeline runner получает новые stages.

**Tech Stack:** Python 3.12, ruptures, statsmodels, pyod, baro, pandas, numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-03-31-monitoring-tools-design.md`

**Verification dataset:** Bank, 2021_03_04 (все часы, focus Hour 7)

---

## File Map

### Новые файлы

| Файл | Назначение |
|------|------------|
| `services/aiops/metrics/__init__.py` | Package init |
| `services/aiops/metrics/base.py` | MetricDetector ABC + DetectionResult |
| `services/aiops/metrics/ruptures_detector.py` | PELT/BOCPD change point detection |
| `services/aiops/metrics/stl_detector.py` | STL/MSTL seasonal decomposition |
| `services/aiops/metrics/oneshot_stl_detector.py` | OneShotSTL streaming |
| `services/aiops/metrics/pyod_detector.py` | PyOD ensemble |
| `services/aiops/metrics/baro_detector.py` | BARO root cause ranking |
| `services/aiops/metrics/ensemble.py` | MetricEnsemble |
| `services/aiops/traces/__init__.py` | Package init |
| `services/aiops/traces/base.py` | TraceAnalyzer ABC + TraceResult |
| `services/aiops/traces/span_analyzer.py` | Span latency/error detection |
| `services/aiops/traces/dependency_builder.py` | Service dependency DAG |
| `services/aiops/traces/critical_path.py` | Critical path extraction |
| `services/aiops/correlation/__init__.py` | Package init |
| `services/aiops/correlation/base.py` | Correlator ABC + Incident |
| `services/aiops/correlation/temporal.py` | Time-window co-occurrence |
| `services/aiops/correlation/topological.py` | Dependency graph walk |
| `services/aiops/correlation/noise_filter.py` | Chronic/acute + entropy |
| `services/aiops/tests/test_metrics.py` | Metric detector tests |
| `services/aiops/tests/test_traces.py` | Trace analyzer tests |
| `services/aiops/tests/test_correlation.py` | Correlator tests |

### Модифицируемые файлы

| Файл | Изменение |
|------|-----------|
| `services/aiops/requirements.txt` | + ruptures, pyod, baro |
| `services/aiops/pipeline/config.py` | + MetricsConfig, TracesConfig, CorrelationConfig |
| `services/aiops/pipeline/runner.py` | + metric/trace/correlation stages |
| `services/aiops/pipeline/trace.py` | + metric/trace/correlation result fields |
| `services/aiops/pipeline_config.yaml` | + metrics, traces, correlation sections |
| `tasks.md` | Phase 3 tasks |

---

## Task 1: MetricDetector ABC + project structure

**Files:**
- Create: `services/aiops/metrics/__init__.py`
- Create: `services/aiops/metrics/base.py`
- Create: `services/aiops/traces/__init__.py`
- Create: `services/aiops/traces/base.py`
- Create: `services/aiops/correlation/__init__.py`
- Create: `services/aiops/correlation/base.py`
- Create: `services/aiops/tests/test_metrics.py`
- Modify: `services/aiops/requirements.txt`

- [ ] **Step 1: Create directories**
```bash
cd services/aiops && mkdir -p metrics traces correlation
touch metrics/__init__.py traces/__init__.py correlation/__init__.py
```

- [ ] **Step 2: Add dependencies to requirements.txt**
Add lines:
```
ruptures==1.1.*
pyod==2.0.*
```
Note: baro and statsmodels -- check actual available versions with pip. statsmodels is likely already installed as pandas dependency.

- [ ] **Step 3: Write failing test for MetricDetector ABC**

Create `services/aiops/tests/test_metrics.py`:
```python
"""Tests for MetricDetector ABC and DetectionResult."""
import pytest
import pandas as pd
from dataclasses import asdict
from metrics.base import DetectionResult, MetricDetector


class TestDetectionResult:
    def test_create(self):
        r = DetectionResult(
            component="Redis02", metric="CPUCpuUtil",
            anomaly_type="change_point", timestamp="2021-03-04T07:01:00",
            value=91.9, baseline=1.7, score=0.95,
            detector_name="ruptures", details={}
        )
        assert r.component == "Redis02"
        assert r.score == 0.95

    def test_serializable(self):
        r = DetectionResult(
            component="X", metric="Y", anomaly_type="spike",
            timestamp="T", value=1.0, baseline=0.0,
            score=0.5, detector_name="test", details={"k": "v"}
        )
        d = asdict(r)
        assert d["details"]["k"] == "v"


class TestMetricDetectorABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            MetricDetector()

    def test_concrete_works(self):
        class FakeDetector(MetricDetector):
            name = "fake"
            version = "0.1"
            def detect(self, df, component):
                return [DetectionResult(
                    component=component, metric="test", anomaly_type="test",
                    timestamp="T", value=1.0, baseline=0.0,
                    score=0.5, detector_name=self.name, details={}
                )]
            def reset(self):
                pass

        d = FakeDetector()
        results = d.detect(pd.DataFrame(), "X")
        assert len(results) == 1
        assert results[0].detector_name == "fake"

    def test_detect_all_loops(self):
        class SimpleDetector(MetricDetector):
            name = "simple"
            version = "0.1"
            def detect(self, df, component):
                return [DetectionResult(
                    component=component, metric="m", anomaly_type="t",
                    timestamp="T", value=1.0, baseline=0.0,
                    score=0.5, detector_name=self.name, details={}
                )]
            def reset(self):
                pass

        d = SimpleDetector()
        df = pd.DataFrame({"cmdb_id": ["A", "A", "B"], "kpi_name": ["cpu", "cpu", "mem"], "value": [1, 2, 3]})
        results = d.detect_all(df)
        assert len(results) == 2  # one per component (A, B)
```

- [ ] **Step 4: Implement base.py**

Create `services/aiops/metrics/base.py`:
```python
"""MetricDetector ABC and DetectionResult."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class DetectionResult:
    component: str
    metric: str
    anomaly_type: str
    timestamp: str
    value: float
    baseline: float
    score: float
    detector_name: str
    details: dict = field(default_factory=dict)


class MetricDetector(ABC):
    name: str
    version: str

    @abstractmethod
    def detect(self, df: pd.DataFrame, component: str) -> list[DetectionResult]:
        ...

    def detect_all(self, df: pd.DataFrame) -> list[DetectionResult]:
        results = []
        if "cmdb_id" in df.columns:
            for comp in df["cmdb_id"].unique():
                comp_df = df[df["cmdb_id"] == comp]
                results.extend(self.detect(comp_df, str(comp)))
        return results

    @abstractmethod
    def reset(self) -> None:
        ...
```

- [ ] **Step 5: Also create traces/base.py and correlation/base.py stubs**

`services/aiops/traces/base.py`:
```python
"""TraceAnalyzer ABC and TraceResult."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class TraceResult:
    trace_id: str
    is_anomalous: bool
    bottleneck_service: str
    critical_path: list[str]
    latency_ms: float
    normal_latency_ms: float
    anomalous_spans: list[dict] = field(default_factory=list)
    analyzer_name: str = ""
    details: dict = field(default_factory=dict)


class TraceAnalyzer(ABC):
    name: str
    version: str

    @abstractmethod
    def analyze(self, spans_df: pd.DataFrame) -> list[TraceResult]:
        ...

    @abstractmethod
    def reset(self) -> None:
        ...
```

`services/aiops/correlation/base.py`:
```python
"""Correlator ABC and Incident."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import uuid


@dataclass
class Incident:
    severity: str
    components: list[str]
    root_cause_candidate: str
    onset: str
    signals: dict = field(default_factory=dict)
    confidence: float = 0.0
    correlator_name: str = ""
    incident_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    details: dict = field(default_factory=dict)


class Correlator(ABC):
    name: str
    version: str

    @abstractmethod
    def correlate(self, log_anomalies: list, metric_anomalies: list,
                  trace_anomalies: list, topology: dict) -> list[Incident]:
        ...

    @abstractmethod
    def reset(self) -> None:
        ...
```

- [ ] **Step 6: Run tests, verify pass**
```bash
cd services/aiops && py -m pytest tests/test_metrics.py -v
```

- [ ] **Step 7: Commit**
```bash
git add metrics/ traces/ correlation/ tests/test_metrics.py requirements.txt
git commit -m "feat: ABC interfaces for metrics, traces, correlation"
```

---

## Task 2: ruptures detector (PELT change point detection)

**Files:**
- Create: `services/aiops/metrics/ruptures_detector.py`
- Modify: `services/aiops/tests/test_metrics.py`

- [ ] **Step 1: Write failing test**
```python
from metrics.ruptures_detector import RupturesDetector

class TestRupturesDetector:
    def test_is_metric_detector(self):
        d = RupturesDetector()
        assert isinstance(d, MetricDetector)
        assert d.name == "ruptures"

    def test_detect_change_point(self):
        # Create data with obvious change point: stable then spike
        import numpy as np
        np.random.seed(42)
        normal = np.random.normal(2.0, 0.5, 50)
        spike = np.random.normal(90.0, 5.0, 10)
        values = np.concatenate([normal, spike])
        df = pd.DataFrame({
            "cmdb_id": ["Redis02"] * 60,
            "kpi_name": ["CPUCpuUtil"] * 60,
            "value": values,
            "timestamp": range(60),
        })
        results = d.detect(df, "Redis02")
        assert len(results) > 0
        assert results[0].anomaly_type == "change_point"
        assert results[0].component == "Redis02"

    def test_no_anomaly_on_stable(self):
        import numpy as np
        np.random.seed(42)
        values = np.random.normal(2.0, 0.5, 60)
        df = pd.DataFrame({
            "cmdb_id": ["Redis02"] * 60,
            "kpi_name": ["CPUCpuUtil"] * 60,
            "value": values,
            "timestamp": range(60),
        })
        d = RupturesDetector()
        results = d.detect(df, "Redis02")
        assert len(results) == 0  # no change points in stable data

    def test_reset(self):
        d = RupturesDetector()
        d.reset()  # should not raise
```

- [ ] **Step 2: Implement ruptures_detector.py**
```python
"""ruptures detector -- PELT/BOCPD change point detection."""
import ruptures
import numpy as np
import pandas as pd
from metrics.base import MetricDetector, DetectionResult


class RupturesDetector(MetricDetector):
    name = "ruptures"
    version = "1.0"

    def __init__(self, method: str = "pelt", penalty: str = "rbf",
                 min_size: int = 5, pen_value: float = 1.0):
        self._method = method
        self._penalty = penalty
        self._min_size = min_size
        self._pen_value = pen_value

    def detect(self, df: pd.DataFrame, component: str) -> list[DetectionResult]:
        results = []
        if df.empty:
            return results
        comp_df = df[df["cmdb_id"] == component] if "cmdb_id" in df.columns else df
        for kpi in comp_df["kpi_name"].unique():
            kpi_df = comp_df[comp_df["kpi_name"] == kpi].sort_values("timestamp")
            values = kpi_df["value"].values.astype(float)
            if len(values) < self._min_size * 2:
                continue
            try:
                algo = ruptures.Pelt(model=self._penalty, min_size=self._min_size)
                change_points = algo.fit_predict(values, pen=self._pen_value)
                # change_points includes len(values) as last element
                for cp in change_points[:-1]:
                    before = values[max(0, cp - self._min_size):cp]
                    after = values[cp:min(len(values), cp + self._min_size)]
                    if len(before) > 0 and len(after) > 0:
                        baseline = float(np.median(before))
                        current = float(np.median(after))
                        if abs(current - baseline) > 2 * max(np.std(before), 0.01):
                            ts = str(kpi_df.iloc[cp]["timestamp"]) if cp < len(kpi_df) else ""
                            results.append(DetectionResult(
                                component=component, metric=str(kpi),
                                anomaly_type="change_point", timestamp=ts,
                                value=current, baseline=baseline,
                                score=min(1.0, abs(current - baseline) / max(baseline, 0.01)),
                                detector_name=self.name,
                                details={"change_point_index": cp, "method": self._method},
                            ))
            except Exception:
                continue
        return results

    def reset(self) -> None:
        pass
```

- [ ] **Step 3: Run tests + verify on Bank data**
```bash
cd services/aiops && py -m pytest tests/test_metrics.py -v
```
Then verify on real data:
```python
from metrics.ruptures_detector import RupturesDetector
import pandas as pd
df = pd.read_csv("../../Bank/telemetry/2021_03_04/metric/metric_container.csv")
d = RupturesDetector()
results = d.detect(df, "Redis02")
for r in results[:5]:
    print(f"{r.component}.{r.metric}: {r.anomaly_type} at {r.timestamp}, value={r.value:.1f}, baseline={r.baseline:.1f}")
```

- [ ] **Step 4: Commit**

---

## Task 3: STL/MSTL detector (seasonal decomposition)

**Files:**
- Create: `services/aiops/metrics/stl_detector.py`
- Modify: `services/aiops/tests/test_metrics.py`

Implement using `statsmodels.tsa.seasonal.STL`. Decomposes metric into trend + seasonal + remainder. Anomalies are detected in remainder component (values > N * std).

- [ ] **Step 1: Write failing test** (STL on synthetic seasonal data + anomaly)
- [ ] **Step 2: Implement stl_detector.py** (STL decomposition, anomaly in remainder)
- [ ] **Step 3: Test + verify on Bank metrics + commit**

---

## Task 4: OneShotSTL detector (streaming decomposition)

**Files:**
- Create: `services/aiops/metrics/oneshot_stl_detector.py`
- Modify: `services/aiops/tests/test_metrics.py`

Clone OneShotSTL or implement simplified streaming STL. O(1) per point.

- [ ] **Step 1: Install/clone OneShotSTL, study API**
```bash
git clone https://github.com/xiao-he/OneShotSTL.git services/aiops/vendor/oneshot_stl
```
- [ ] **Step 2: Write test + implement adapter**
- [ ] **Step 3: Test + verify on Bank metrics + commit**

---

## Task 5: PyOD detector (ensemble anomaly detection)

**Files:**
- Create: `services/aiops/metrics/pyod_detector.py`
- Modify: `services/aiops/tests/test_metrics.py`

PyOD ensemble: IsolationForest + LOF + OCSVM on component KPI matrix.

- [ ] **Step 1: Write failing test**
```python
from metrics.pyod_detector import PyODDetector

class TestPyODDetector:
    def test_is_metric_detector(self):
        d = PyODDetector()
        assert isinstance(d, MetricDetector)
        assert d.name == "pyod"

    def test_detect_anomaly(self):
        import numpy as np
        np.random.seed(42)
        # 50 normal rows + 5 anomalous
        normal = np.random.normal(0, 1, (50, 3))
        anomalous = np.random.normal(10, 1, (5, 3))
        data = np.vstack([normal, anomalous])
        df = pd.DataFrame({
            "cmdb_id": ["comp"] * 55,
            "kpi_name": ["cpu"] * 55,
            "value": data[:, 0],
            "timestamp": range(55),
        })
        d = PyODDetector(methods=["iforest"])
        results = d.detect(df, "comp")
        assert len(results) > 0
```

- [ ] **Step 2: Implement pyod_detector.py** (ensemble of IForest + LOF + OCSVM, voting)
- [ ] **Step 3: Test + verify on Bank + commit**

---

## Task 6: BARO detector (root cause ranking)

**Files:**
- Create: `services/aiops/metrics/baro_detector.py`
- Modify: `services/aiops/tests/test_metrics.py`

BARO: Bayesian Online CPD + root cause ranking across all components.

- [ ] **Step 1: Install baro**
```bash
pip install baro
```
Study API: how to call BARO, what input format it expects.

- [ ] **Step 2: Write test + implement adapter**
- [ ] **Step 3: Test + verify on Bank + commit**

---

## Task 7: MetricEnsemble

**Files:**
- Create: `services/aiops/metrics/ensemble.py`
- Modify: `services/aiops/tests/test_metrics.py`

Combines multiple MetricDetectors. Runs all enabled detectors, merges results by component.

- [ ] **Step 1: Write test** (FakeDetectors, verify merge + dedup)
- [ ] **Step 2: Implement ensemble.py**
```python
class MetricEnsemble:
    def __init__(self, detectors: list[MetricDetector]):
        self.detectors = detectors
    
    def detect_all(self, df: pd.DataFrame) -> dict:
        """Returns {detector_name: [DetectionResult], "merged": [merged results]}"""
        all_results = {}
        for d in self.detectors:
            all_results[d.name] = d.detect_all(df)
        all_results["merged"] = self._merge(all_results)
        return all_results
    
    def _merge(self, results_by_detector):
        # Group by (component, timestamp window) across detectors
        # Multiple detectors agreeing = higher confidence
        ...
```
- [ ] **Step 3: Test + commit**

---

## Task 8: TraceAnalyzer -- span_analyzer

**Files:**
- Create: `services/aiops/traces/span_analyzer.py`
- Create: `services/aiops/tests/test_traces.py`

Analyzes individual spans: flags spans where duration > N * median duration for that service.

- [ ] **Step 1: Write failing test**
```python
from traces.span_analyzer import SpanAnalyzer
from traces.base import TraceAnalyzer, TraceResult

class TestSpanAnalyzer:
    def test_is_trace_analyzer(self):
        a = SpanAnalyzer()
        assert isinstance(a, TraceAnalyzer)
        assert a.name == "span_analyzer"

    def test_detect_slow_span(self):
        df = pd.DataFrame({
            "timestamp": [1, 2, 3, 4, 5],
            "cmdb_id": ["svc1", "svc1", "svc1", "svc1", "svc1"],
            "span_id": ["s1", "s2", "s3", "s4", "s5"],
            "parent_id": ["", "s1", "s1", "s1", "s1"],
            "trace_id": ["t1", "t1", "t1", "t1", "t1"],
            "duration": [10, 12, 11, 13, 500],  # s5 is anomalous
        })
        results = a.analyze(df)
        anomalous = [r for r in results if r.is_anomalous]
        assert len(anomalous) > 0
```

- [ ] **Step 2: Implement span_analyzer.py**
- [ ] **Step 3: Test + verify on Bank trace_span.csv + commit**

---

## Task 9: TraceAnalyzer -- dependency_builder

**Files:**
- Create: `services/aiops/traces/dependency_builder.py`
- Modify: `services/aiops/tests/test_traces.py`

Builds service dependency DAG from trace span parent-child relationships.

- [ ] **Step 1: Write test** (synthetic spans, verify edges)
- [ ] **Step 2: Implement** (group by trace_id, parent_id→cmdb_id edges, deduplicate)
- [ ] **Step 3: Test + verify on Bank + commit**

---

## Task 10: TraceAnalyzer -- critical_path

**Files:**
- Create: `services/aiops/traces/critical_path.py`
- Modify: `services/aiops/tests/test_traces.py`

Finds the longest (most time-consuming) path through each trace.

- [ ] **Step 1: Write test** (synthetic trace tree, verify path)
- [ ] **Step 2: Implement** (build span tree per trace, DFS for longest path)
- [ ] **Step 3: Test + verify on Bank + commit**

---

## Task 11: Correlator -- temporal

**Files:**
- Create: `services/aiops/correlation/temporal.py`
- Create: `services/aiops/tests/test_correlation.py`

Groups anomalies that co-occur within a time window on the same or related components.

- [ ] **Step 1: Write test** (anomalies at close timestamps → grouped)
- [ ] **Step 2: Implement** (parse timestamps, group within window_seconds)
- [ ] **Step 3: Test + commit**

---

## Task 12: Correlator -- topological

**Files:**
- Create: `services/aiops/correlation/topological.py`
- Modify: `services/aiops/tests/test_correlation.py`

Walks dependency graph upstream from symptom to find deepest anomalous component.

- [ ] **Step 1: Write test** (simple graph A→B→C, anomaly on C → root cause A)
- [ ] **Step 2: Implement** (BFS/DFS upstream, find deepest anomalous node)
- [ ] **Step 3: Test + commit**

---

## Task 13: Correlator -- noise_filter

**Files:**
- Create: `services/aiops/correlation/noise_filter.py`
- Modify: `services/aiops/tests/test_correlation.py`

Separates chronic (N/N previous hours anomalous) from acute (new) anomalies. Entropy filtering for low-information alerts.

- [ ] **Step 1: Write test** (chronic component filtered, acute kept)
- [ ] **Step 2: Implement** (history lookup, entropy scoring)
- [ ] **Step 3: Test + commit**

---

## Task 14: Pipeline Config update

**Files:**
- Modify: `services/aiops/pipeline/config.py`
- Modify: `services/aiops/pipeline_config.yaml`
- Modify: `services/aiops/tests/test_pipeline.py`

Add MetricsConfig, TracesConfig, CorrelationConfig to PipelineConfig.

- [ ] **Step 1: Add Pydantic models**
```python
class DetectorConfig(BaseModel):
    name: str
    enabled: bool = True
    params: dict = {}

class MetricsConfig(BaseModel):
    detectors: list[DetectorConfig] = []

class AnalyzerConfig(BaseModel):
    name: str
    enabled: bool = True
    params: dict = {}

class TracesConfig(BaseModel):
    analyzers: list[AnalyzerConfig] = []

class CorrelatorConfig(BaseModel):
    name: str
    enabled: bool = True
    params: dict = {}

class CorrelationConfig(BaseModel):
    correlators: list[CorrelatorConfig] = []

class PipelineConfig(BaseModel):
    parsing: ParsingConfig = ParsingConfig()
    metrics: MetricsConfig = MetricsConfig()
    traces: TracesConfig = TracesConfig()
    correlation: CorrelationConfig = CorrelationConfig()
    context: ContextConfig = ContextConfig()
    agent: AgentConfig = AgentConfig()
    benchmark: BenchmarkConfig = BenchmarkConfig()
```

- [ ] **Step 2: Update pipeline_config.yaml with metrics/traces/correlation sections**
- [ ] **Step 3: Test config loads correctly + commit**

---

## Task 15: Pipeline Runner + Trace update

**Files:**
- Modify: `services/aiops/pipeline/runner.py`
- Modify: `services/aiops/pipeline/trace.py`
- Modify: `services/aiops/tests/test_pipeline.py`

Add metric detection, trace analysis, and correlation stages to runner. Extend PipelineTrace with new fields.

- [ ] **Step 1: Add fields to PipelineTrace**
```python
# New fields
metric_anomalies: dict = field(default_factory=dict)  # {detector: [results]}
baro_ranking: list = field(default_factory=list)
trace_results: dict = field(default_factory=dict)  # {analyzer: [results]}
dependency_graph: dict = field(default_factory=dict)
incidents: list = field(default_factory=list)
noise_stats: dict = field(default_factory=dict)
```

- [ ] **Step 2: Add registries + stages to runner**
```python
METRIC_REGISTRY: dict[str, type] = {}
TRACE_REGISTRY: dict[str, type] = {}
CORRELATION_REGISTRY: dict[str, type] = {}

# In PipelineRunner.run():
# Stage 3: Metric detection
# Stage 4: Trace analysis
# Stage 5: Correlation
```

- [ ] **Step 3: Integration test on Bank H7 + commit**

---

## Task 16: Full comparison run + Excel

**Files:**
- Create: `services/aiops/run_monitoring_comparison.py`

Run all monitoring tools on Bank data, generate Excel with results per tool.

- [ ] **Step 1: Script that runs each detector/analyzer on Bank**
- [ ] **Step 2: Generate Excel: Summary + per-tool results + per-hour breakdown**
- [ ] **Step 3: Commit**

---

## Task 17: Update tasks.md + docs

**Files:**
- Modify: `tasks.md`
- Modify: `README.md`

- [ ] **Step 1: Add Phase 3 to tasks.md**
- [ ] **Step 2: Update README with new tools**
- [ ] **Step 3: Commit**
