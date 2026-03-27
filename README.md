# AIOps Ensemble Pipeline

Research bench для сравнения парсеров логов и их комбинаций на OpenRCA датасетах.

## Архитектура

```
Raw CSV -> Adapters -> Parsing Layer -> Detection -> Context -> Agent -> RCA Report
                        (6 парсеров)                 (JSON/     (GPT-5.4)
                        (ensemble)                   Narrative)
                              |
                     Pipeline Trace -> Benchmark
```

Один FastAPI-сервис + 5 внешних контейнеров:

| Сервис | Порт | Назначение |
|--------|------|------------|
| aiops-service | 8081 | Основной сервис (парсинг + детекция + агент + API) |
| keep-api | 8080 | Alert management API |
| keep-ui | 3001 | Keep веб-интерфейс |
| keep-db | 5432 | PostgreSQL для Keep |
| chromadb | 8000 | Векторное хранилище для RAG |
| grafana | 3000 | Дашборды |

## Парсеры

| Парсер | Тип | LLM | Роль |
|--------|-----|-----|------|
| Drain3 | Статистический | Нет | Baseline |
| LogLSHD | LSH+DTW | Нет | Быстрый |
| LILAC | LLM+Cache | OpenAI | Primary LLM |
| LogParser-LLM | Prefix tree+LLM | OpenAI | Гибрид |
| DivLog | ICL | OpenAI | Оракул |
| Lemur | Entropy+CoT | OpenAI | Консолидатор |

## Конфигурация

Все параметры в `pipeline_config.yaml`:

- **Парсеры** -- вкл/выкл, индивидуальные параметры
- **Режим ансамбля** -- `parallel` / `cascade` / `single`
- **Голосование** -- `majority` / `weighted` / `best_confidence`
- **Формат контекста** -- `json` / `narrative`
- **Benchmark** -- датасеты, даты, часы

## Быстрый старт

```bash
# 1. Настройка
cp .env.example .env
# Вписать OPENAI_API_KEY в .env

# 2. Данные OpenRCA
git clone https://github.com/microsoft/OpenRCA.git data/openrca
# Скачать телеметрию из Google Drive в data/openrca/Bank/, data/openrca/Telecom/

# 3. Запуск
docker compose up -d

# 4. Настройка Keep (один раз)
py scripts/setup_keep.py --data-dir ./data/openrca --dataset Bank
# Скопировать API key из вывода в .env, перезапустить:
docker compose restart aiops-service

# 5. Прогон пайплайна
curl -X POST http://localhost:8081/ingest/openrca \
  -H "Content-Type: application/json" \
  -d '{"dataset": "Bank", "date": "2021_03_04"}'

# 6. Расследование
curl -X POST http://localhost:8081/investigate \
  -H "Content-Type: application/json" \
  -d '{"incident_id": "test-1", "dataset": "Bank", "date": "2021_03_04"}'

# 7. Benchmark
curl -X POST http://localhost:8081/benchmark/run \
  -H "Content-Type: application/json" \
  -d '{"dataset": "Bank", "dates": ["2021_03_04"]}'

# 8. Дашборды
# Grafana: http://localhost:3000 (admin/admin)
# Keep UI: http://localhost:3001
```

## Структура проекта

```
services/aiops/
  pipeline_config.yaml       # Конфигурация пайплайна
  run_pipeline.py            # Точка входа
  parsers/
    base.py                  # Базовый класс парсера
    drain_parser.py          # Drain3 обертка
    ensemble.py              # Ансамбль + голосование
  pipeline/
    config.py                # Загрузка YAML-конфига
    runner.py                # Оркестратор пайплайна
    context_formatter.py     # JSON/Narrative форматирование
    trace.py                 # Pipeline trace для benchmark
  app/
    main.py                  # FastAPI приложение
    config.py                # Pydantic settings
    models.py                # Pydantic модели
    db.py                    # SQLite схема
    adapters/
      openrca.py             # Чтение OpenRCA CSV
    detection/
      golden_signals.py      # Golden signals детекция
      correlator.py          # Корреляция аномалий
      infra_detector.py      # Инфраструктурные аномалии
      context_builder.py     # Сборка контекста для агента
    drain/
      parser.py              # Drain3 обертка (legacy)
    agent/
      investigator.py        # GPT-5.4 Responses API loop
      tools.py               # 8 tool definitions
      prompts.py             # System prompt
      rag.py                 # ChromaDB knowledge base
    api/                     # REST endpoints
```

## Агент

Один агент (GPT-5.4), 8 tools, 3-фазный протокол расследования.

**Фаза 1 -- Обзор**: топология и метрики всех сервисов, поиск аномальных компонентов.

**Фаза 2 -- Каузальный анализ**: движение UPSTREAM по зависимостям. Если A зависит от B и оба деградированы -- сначала B.

**Фаза 3 -- Верификация**: перекрестная проверка с изменениями и базой знаний.

Tools: `query_metrics`, `query_logs`, `query_traces`, `get_topology`, `get_recent_changes`, `search_knowledge_base`, `query_parser_details`, `get_baseline_comparison`.

Контекст самодостаточный: каждое значение сопровождается объяснением.

## Датасеты

Bank (19 инцидентов), Market (2 cloudbed), Telecom -- OpenRCA формат.

## Стек

| Слой | Технология |
|------|-----------|
| API | FastAPI |
| Парсинг логов | Drain3, LogLSHD, LILAC, LogParser-LLM, DivLog, Lemur |
| Детекция аномалий | scikit-learn (IsolationForest), Golden Signals |
| LLM | OpenAI GPT-5.4 (Responses API) |
| Embeddings | OpenAI text-embedding-3-small |
| Vector store | ChromaDB |
| Alert management | Keep |
| Дашборды | Grafana + Infinity plugin |
| БД | SQLite / PostgreSQL (Keep) |
| Контейнеры | Docker Compose |
