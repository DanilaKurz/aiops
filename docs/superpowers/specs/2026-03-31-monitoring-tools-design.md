# Phase 3: Monitoring Tools (Tier 1) -- Design Spec

Дата: 2026-03-31
Статус: approved

## Цель

Добавить конфигурируемые инструменты мониторинга для всех столпов observability: metrics (ruptures, STL, PyOD, BARO), traces (span analysis, dependency graph, critical path), correlation (temporal, topological, noise filter). Тот же паттерн что parsers: ABC + registry + YAML config + pipeline trace.

## Принятые решения

| Вопрос | Решение |
|--------|---------|
| Scope | Только Tier 1 -- pip install, сразу применимо |
| Архитектура | По столпам: metrics/, traces/, correlation/ -- отдельные ABC |
| Паттерн | Тот же что parsers/: ABC + registry + YAML config |
| Проверка | Каждый инструмент на Bank 2021_03_04 |

## Структура файлов

```
services/aiops/
  parsers/                  # Logs (БЕЗ ИЗМЕНЕНИЙ)

  metrics/                  # НОВЫЙ
    __init__.py
    base.py                 # MetricDetector ABC + DetectionResult
    ruptures_detector.py    # PELT/BOCPD change point detection
    stl_detector.py         # STL/MSTL seasonal decomposition
    oneshot_stl_detector.py # OneShotSTL streaming decomposition
    pyod_detector.py        # PyOD ensemble (IForest+LOF+OCSVM)
    baro_detector.py        # BARO root cause ranking
    ensemble.py             # MetricEnsemble

  traces/                   # НОВЫЙ
    __init__.py
    base.py                 # TraceAnalyzer ABC + TraceResult
    span_analyzer.py        # Span-level latency/error detection
    dependency_builder.py   # Service dependency graph from traces
    critical_path.py        # Critical path extraction

  correlation/              # НОВЫЙ
    __init__.py
    base.py                 # Correlator ABC + Incident
    temporal.py             # Time-window co-occurrence
    topological.py          # Dependency graph walk
    noise_filter.py         # Chronic/acute + entropy filtering

  pipeline/                 # Обновить
    config.py               # + metrics, traces, correlation в YAML
    runner.py               # + stages для новых столпов
    trace.py                # + поля для metric/trace results
```

## ABC интерфейсы

### MetricDetector

```python
@dataclass
class DetectionResult:
    component: str          # "Redis02"
    metric: str             # "CPUCpuUtil"
    anomaly_type: str       # "change_point" | "spike" | "seasonal_deviation"
    timestamp: str          # ISO timestamp момента аномалии
    value: float            # текущее значение
    baseline: float         # нормальное значение
    score: float            # 0.0-1.0, severity
    detector_name: str      # "ruptures", "pyod", ...
    details: dict           # detector-specific data

class MetricDetector(ABC):
    name: str
    version: str

    @abstractmethod
    def detect(self, df: pd.DataFrame, component: str) -> list[DetectionResult]
        # df: timestamp, kpi_name, value (long format)
        # component: "Redis02"

    def detect_all(self, df: pd.DataFrame) -> list[DetectionResult]
        # default: loop detect() per component

    @abstractmethod
    def reset(self) -> None
```

### TraceAnalyzer

```python
@dataclass
class TraceResult:
    trace_id: str
    is_anomalous: bool
    bottleneck_service: str     # service causing most latency
    critical_path: list[str]    # ordered service chain
    latency_ms: float
    normal_latency_ms: float
    anomalous_spans: list[dict] # spans with unusual duration/errors
    analyzer_name: str
    details: dict

class TraceAnalyzer(ABC):
    name: str
    version: str

    @abstractmethod
    def analyze(self, spans_df: pd.DataFrame) -> list[TraceResult]
        # spans_df: timestamp, cmdb_id, span_id, parent_id, trace_id, duration

    @abstractmethod
    def reset(self) -> None
```

### Correlator

```python
@dataclass
class Incident:
    incident_id: str
    severity: str               # "critical" | "warning" | "info"
    components: list[str]       # все затронутые компоненты
    root_cause_candidate: str   # наиболее вероятный root cause
    onset: str                  # timestamp первой аномалии
    signals: dict               # {"logs": [...], "metrics": [...], "traces": [...]}
    confidence: float
    correlator_name: str
    details: dict

class Correlator(ABC):
    name: str
    version: str

    @abstractmethod
    def correlate(self, log_anomalies: list, metric_anomalies: list[DetectionResult],
                  trace_anomalies: list[TraceResult], topology: dict) -> list[Incident]

    @abstractmethod
    def reset(self) -> None
```

## Инструменты

### Metrics (5 штук)

| Инструмент | Install | Input | Output |
|------------|---------|-------|--------|
| ruptures/PELT | pip install ruptures | Один KPI timeseries | Change points с timestamps |
| STL/MSTL | Built-in statsmodels | Один KPI timeseries | Trend + seasonal + remainder, anomaly в remainder |
| OneShotSTL | git clone xiao-he/OneShotSTL | Streaming points | Streaming decomposition O(1)/point |
| PyOD ensemble | pip install pyod | Matrix (time x KPIs) | Anomaly score per component |
| BARO | pip install baro | All metrics all components | Ranked root cause list with scores |

### Traces (3 штуки)

| Инструмент | Install | Input | Output |
|------------|---------|-------|--------|
| span_analyzer | Наша реализация | trace_span.csv | Anomalous spans (latency > N * median) |
| dependency_builder | Наша реализация | trace_span.csv | Service dependency graph (DAG) |
| critical_path | Наша реализация | trace_span.csv | Longest path per trace, bottleneck service |

### Correlation (3 штуки)

| Инструмент | Install | Input | Output |
|------------|---------|-------|--------|
| temporal | Наша реализация | All anomalies | Co-occurring anomalies within time window |
| topological | Перенос из detection/ | Anomalies + topology | Upstream root cause walk |
| noise_filter | Расширение существующего | All anomalies + history | Chronic/acute labels + entropy scores |

## YAML Config (расширение)

```yaml
parsing:              # уже есть, без изменений
  mode: parallel
  parsers: [...]

metrics:
  detectors:
    - name: ruptures
      enabled: true
      params: {method: pelt, penalty: rbf}
    - name: stl
      enabled: true
      params: {period: 60, robust: true}
    - name: pyod
      enabled: true
      params: {methods: [iforest, lof, ocsvm], contamination: 0.1}
    - name: baro
      enabled: true
    - name: oneshot_stl
      enabled: false

traces:
  analyzers:
    - name: span_analyzer
      enabled: true
      params: {latency_threshold_multiplier: 3.0}
    - name: dependency_builder
      enabled: true
    - name: critical_path
      enabled: true

correlation:
  correlators:
    - name: temporal
      enabled: true
      params: {window_seconds: 300}
    - name: topological
      enabled: true
    - name: noise_filter
      enabled: true
      params: {chronic_hours: 6, entropy_threshold: 0.3}

context:
  formats: [json, narrative]

agent:
  model: gpt-5.4
  max_iterations: 20

benchmark:
  datasets: [Bank]
  dates: ["2021_03_04"]
  hours: [7]
  save_traces: true
```

## Pipeline Runner (обновление)

Текущий runner выполняет: load data → parse logs → format context → save trace.

Новый runner:
```
1. Load data (logs, metrics, traces) via OpenRCAAdapter
2. Parse logs (parsers/ -- без изменений)
3. Detect metric anomalies (metrics/ -- NEW)
4. Analyze traces (traces/ -- NEW)
5. Correlate signals (correlation/ -- NEW)
6. Format context (pipeline/context_formatter -- обновить с новыми данными)
7. Save trace (pipeline/trace -- расширить)
```

## Pipeline Trace (расширение)

Добавить поля:
```python
# Stage: Metrics
metric_anomalies: list[dict]        # DetectionResult per detector
metric_summary: dict                # {detector: count_anomalies}
baro_ranking: list[dict]            # BARO ranked components

# Stage: Traces
trace_anomalies: list[dict]         # TraceResult per analyzer
dependency_graph: dict              # {nodes, edges}
critical_paths: list[dict]

# Stage: Correlation
incidents: list[dict]               # Incident objects
noise_stats: dict                   # {chronic: N, acute: N, filtered: N}
```

## Проверка каждого инструмента

Каждый инструмент после реализации проверяется на Bank 2021_03_04:
- Запуск на реальных данных
- Проверка типов (DetectionResult/TraceResult/Incident)
- Сравнение с существующим detection layer
- Вывод результатов для Excel отчёта

## Scope

### В этом spec (11 инструментов)

- MetricDetector ABC + 5 детекторов (ruptures, STL, OneShotSTL, PyOD, BARO)
- TraceAnalyzer ABC + 3 анализатора (span, dependency, critical_path)
- Correlator ABC + 3 корреляторa (temporal, topological, noise_filter)
- Обновление pipeline config, runner, trace
- Тесты для всех
- Excel отчёт с результатами на Bank

### НЕ в этом spec

- LLM-agent tools (обновление agent/tools.py)
- Tier 2 инструменты (TraceRCA, MicroRank, RCD, CIRCA)
- Multi-agent architecture
- MCP серверы
