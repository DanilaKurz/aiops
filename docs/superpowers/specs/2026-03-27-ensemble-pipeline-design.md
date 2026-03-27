# Ensemble Pipeline: Design Spec

Дата: 2026-03-27
Статус: approved

## Цель

Research bench для сравнения парсеров логов и их комбинаций на OpenRCA датасетах. Конфигурируемый pipeline с полным trace каждого прогона. Архитектура позволяет переход к online-обработке без переписывания.

## Принятые решения

| Вопрос | Решение | Обоснование |
|--------|---------|-------------|
| Цель проекта | Research-first, production-ready архитектура | Начинаем с экспериментов на датасетах, но с чистыми интерфейсами |
| Результат сравнения | Pipeline trace (полная запись каждого прогона) | Максимум данных для анализа, dashboard строится поверх |
| Стратегия ансамбля | Configurable (parallel / cascade / single через YAML) | Research = parallel, production = cascade |
| Парсеры | Все 6: Drain3, LogLSHD, LILAC, DivLog, LogParser-LLM, Lemur | Полное сравнение для research |
| Структура проекта | Модульная: parsers/, pipeline/, benchmark/ | Каждый парсер = 1 файл, 1 класс, общий ABC |
| Формат agent context | Configurable: JSON + Narrative (оба самодостаточных) | Формат контекста — переменная эксперимента |
| Агентская архитектура | Single agent, улучшенный контекст, расширяемый интерфейс | Проще сделать хорошо, multi-agent в будущем |
| Интеграция парсеров | Adapter wrapping (pip install, subprocess при конфликтах) | Прагматичный гибрид |
| Документация | README.md на русском, лаконично | Позиция + что делает + короткое описание |
| Проверка этапов | Каждый парсер проверяется на Bank Hour 7 сразу | Ловить проблемы типов на ранней стадии |

## Архитектура

```
Raw CSV -> OpenRCAAdapter -> Parsing Layer -> Detection Layer -> Context Layer -> Agent -> RCA Report
                              (6 parsers)     (без изменений)   (JSON/Narrative)  (GPT-5.4)
                              (ensemble)                        (self-documenting)
                                   |                                  |
                                   +------ Pipeline Trace (всё) ------+
                                                  |
                                           Benchmark Runner
```

### 5 слоёв

1. **Data Layer** (`adapters/`) — OpenRCAAdapter, без изменений. Bank/Market/Telecom CSV -> normalized DataFrame.

2. **Parsing Layer** (`parsers/`) — 6 парсеров за общим `LogParser` ABC. Configurable через YAML: mode (parallel/cascade/single), voting (majority/weighted/best_confidence), consolidator (Lemur).

3. **Detection Layer** (`detection/`) — без изменений. IsolationForest + GoldenSignals + InfraDetector + Correlator.

4. **Context Layer** (`pipeline/`) — генерация agent context в 2 форматах. Каждое значение сопровождается: что это, что нормально, почему подозрительно.

5. **Agent Layer** (`agent/`) — single agent GPT-5.4, 8 tools, 3-фазный протокол, улучшенный контекст.

## Структура файлов

```
services/aiops/
  app/                          # FastAPI, API endpoints (без изменений)
    main.py, api/, models.py, db.py

  parsers/                      # НОВЫЙ: все парсеры
    base.py                     # LogParser ABC + ParseResult + EnsembleResult
    drain_parser.py             # Drain3 wrapper
    loglshd_parser.py           # LogLSHD adapter
    lilac_parser.py             # LILAC adapter
    divlog_parser.py            # DivLog adapter
    logparser_llm_parser.py     # LogParser-LLM adapter
    lemur_parser.py             # Lemur adapter (parser + consolidator)
    ensemble.py                 # EnsembleParser: voting, cascade, single

  pipeline/                     # НОВЫЙ: оркестрация
    runner.py                   # Запуск pipeline по YAML config
    trace.py                    # PipelineTrace dataclass + сохранение
    config.py                   # Загрузка/валидация YAML config
    context_formatter.py        # Генерация agent context (JSON + Narrative)

  benchmark/                    # НОВЫЙ: research
    runner.py                   # Batch experiments, ablation
    scoring.py                  # Метрики (per-incident, per-parser, cross-config)

  detection/                    # Без изменений
    context_builder.py, golden_signals.py, correlator.py, infra_detector.py

  agent/                        # Улучшенный
    investigator.py, tools.py, prompts.py, rag.py

  adapters/                     # Без изменений
    openrca.py
```

## LogParser ABC

```python
@dataclass
class ParseResult:
    template: str           # "GC (Allocation Failure) <*>ms"
    cluster_id: int         # unique template ID
    confidence: float       # 0.0 - 1.0
    parser_name: str        # "drain3", "loglshd", ...
    params: dict[str, str]  # extracted variables
    metadata: dict          # parser-specific extras

class LogParser(ABC):
    name: str
    requires_llm: bool
    version: str

    @abstractmethod
    def parse(self, log_line: str) -> ParseResult

    def parse_batch(self, lines: list[str]) -> list[ParseResult]
        # default: loop parse(). LLM parsers override.

    @abstractmethod
    def reset(self) -> None
        # clear learned state for fair benchmark runs
```

## EnsembleParser

```python
@dataclass
class EnsembleResult:
    consensus_template: str
    consensus_confidence: float
    per_parser: dict[str, ParseResult]
    agreement_ratio: float      # 0.0-1.0
    vote_details: dict

class EnsembleParser:
    parsers: list[LogParser]
    mode: "parallel" | "cascade" | "single"
    voting: "majority" | "weighted" | "best_confidence"
    consolidator: LogParser | None  # Lemur
```

## 6 парсеров

| Парсер | Тип | Источник | LLM | Роль в ансамбле |
|--------|-----|----------|-----|-----------------|
| Drain3 | Статистический | pip drain3 | Нет | Baseline |
| LogLSHD | LSH+DTW | github mooselab/LogLSHD | Нет | Быстрый первый проход |
| LILAC | LLM+Cache | github logpai/LILAC | OpenAI (cache снижает) | Primary LLM parser |
| LogParser-LLM | Prefix tree+LLM | github LLMparser/LLMparser | OpenAI (~272/3.6M) | Гибрид |
| DivLog | ICL | logpai/logparser | OpenAI (каждая строка) | Оракул для сложных |
| Lemur | Entropy+CoT | github zwpride/lemur | OpenAI (merging) | Консолидатор |

## YAML Config

```yaml
parsing:
  mode: parallel              # parallel | cascade | single
  voting: majority            # majority | weighted | best_confidence
  cascade_threshold: 0.7
  parsers:
    - name: drain3
      enabled: true
      params: {sim_th: 0.4, depth: 4}
    - name: loglshd
      enabled: true
    - name: lilac
      enabled: true
      params: {cache_size: 10000}
    - name: logparser_llm
      enabled: true
    - name: divlog
      enabled: false           # v2, дорогой
      params: {sample_size: 100}
  consolidator:
    name: lemur
    enabled: true
    params: {merge_threshold: 0.85}

context:
  formats: [json, narrative]

agent:
  model: gpt-5.4
  fallback_model: gpt-4.1
  max_iterations: 20

benchmark:
  datasets: [Bank]
  dates: [2021_03_04]
  hours: [7]
  save_traces: true
```

## Agent Context: самодостаточный формат

Каждое значение в контексте сопровождается тремя вещами:
- **Что это** — человекочитаемое название и роль компонента
- **Что нормально** — baseline/normal range
- **Почему подозрительно** — multiplier, trend, temporal correlation

Пример (Narrative):
```
Redis02 (cache server, Tier 4 backend)
CRITICAL -- first anomaly at 07:01

  CPU utilization: 91.9%
    Normal for this host: 1-3%
    53.8x above normal baseline
    Previous 3 hours: 1.0%, 3.4%, 0.8%
    Sudden spike (was stable)
```

Пример (JSON):
```json
{
  "name": "Redis02",
  "role": "in-memory cache used by all Tomcat servers",
  "metrics": [{
    "name": "CPU utilization",
    "value": 91.9, "unit": "%",
    "normal_range": "1-3%",
    "multiplier": 53.8,
    "trend": "sudden spike from stable baseline",
    "history_hours": [1.0, 3.4, 0.8]
  }],
  "why_suspicious": "NEW spike + precedes user impact + upstream"
}
```

## Agent Tools (8 штук)

### Существующие (улучшенные)

| Tool | Параметры | Возвращает |
|------|-----------|------------|
| `query_metrics` | dataset, date, service?, hour? | Anomalies + normal metrics + earliest onset |
| `query_logs` | dataset, date, service?, hour? | Template clusters + anomaly scores + parser agreement |
| `query_traces` | dataset, date, hour? | Critical path + bottleneck + anomalous spans |
| `get_topology` | dataset | Nodes + edges + dependency levels + component roles |
| `get_recent_changes` | dataset, date | Deploys, config changes before incident window |
| `search_knowledge_base` | query | RAG results from runbooks + past incidents |

### Новые

| Tool | Параметры | Возвращает |
|------|-----------|------------|
| `query_parser_details` | service, hour? | Per-parser template breakdown, agreement, confidence |
| `get_baseline_comparison` | service, metric, hours_back? | Current vs historical values, trend, percentile |

### query_logs (ensemble-aware)

Вместо raw text samples возвращает:
```json
{
  "templates": [
    {
      "template": "GC (<*>) <*>ms",
      "count": 247,
      "is_anomalous": true,
      "confidence": 0.92,
      "agreement": 0.85,
      "meaning": "Java GC struggling with memory pressure"
    }
  ]
}
```

## Pipeline Trace

```python
@dataclass
class PipelineTrace:
    # Metadata
    trace_id: str
    timestamp: datetime
    config_snapshot: dict
    dataset: str
    date: str
    hour: int

    # Stage 1: Parsing
    raw_log_count: int
    parse_results: dict[str, list[ParseResult]]  # per parser
    ensemble_results: list[EnsembleResult]
    template_summary: dict[str, int]              # templates per parser

    # Stage 2: Detection
    anomalies: list[AnomalyInfo]
    golden_signals: list[GoldenSignalAlert]
    infra_alerts: list[InfraAlert]
    incidents: list[Incident]

    # Stage 3: Context
    agent_contexts: dict[str, str]          # format -> context text
    context_token_counts: dict[str, int]

    # Stage 4: Investigation
    agent_results: dict[str, RCAReport]     # per context format
    tool_call_log: list[ToolCall]

    # Evaluation
    ground_truth: GroundTruth
    scores: dict[str, float]

    # Performance
    timing: dict[str, float]                # per-stage seconds
```

### Хранение

```
traces/
  2026-03-27T14-30_Bank_2021_03_04_h07/
    config.yaml
    trace.json
    parse_results/
      drain3.jsonl
      loglshd.jsonl
      lilac.jsonl
      ensemble.jsonl
    contexts/
      json_context.json
      narrative_context.txt
    agent/
      rca_json.json
      rca_narrative.json
      tool_calls.jsonl
```

## Benchmark

### BenchmarkRunner

```python
class BenchmarkRunner:
    def run_experiment(config_path: str) -> list[PipelineTrace]
    def compare_configs(trace_dirs: list[str]) -> ComparisonReport
    def run_ablation(base_config: str, vary: str) -> list[ComparisonReport]
```

### Метрики

**Per-incident:** component_match, reason_similarity, onset_time_error, confidence_calibration, tool_call_efficiency

**Per-parser:** template_count, template_stability, parsing_time, llm_calls, agreement_with_ensemble

**Cross-config:** accuracy_delta, cost_delta, context_token_savings

## Документация

README.md на русском, лаконичный формат:
- Позиция (что это)
- Что делает
- Короткое описание
- Без перегрузки деталями

## Scope

### Must have (v1)

- Реорганизация структуры проекта
- LogParser ABC + Drain3 adapter
- LogLSHD интеграция
- LILAC интеграция
- LogParser-LLM интеграция
- Lemur интеграция (parser + consolidator)
- DivLog интеграция
- EnsembleParser (parallel voting)
- Pipeline runner + YAML config
- Pipeline trace (JSON)
- Benchmark runner (accuracy per config)
- Agent context: 2 самодостаточных формата
- Новые tools: query_parser_details, get_baseline_comparison
- README.md

### Nice to have (v2)

- Классификация инцидентов по группам (архитектура, scope, длительность, impact, причина)
- Cascade mode
- HTML отчёты benchmark
- Multi-agent architecture
- CausalRCA вместо topology-only корреляции

## Проверка каждого этапа

Каждый парсер после интеграции проверяется на **Bank, 2021_03_04, Hour 7** (Redis02 CPU incident):
- Парсер запускается на реальных логах
- Проверяются типы данных ParseResult
- Сравниваются templates с Drain3 baseline
- Для LLM-парсеров считается количество API calls
