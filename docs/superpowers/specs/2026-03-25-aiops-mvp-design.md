# AIOps MVP -- Design Specification

**Date**: 2026-03-25
**Version**: 1.1
**Status**: Approved
**Goal**: Exploratory prototype -- evaluate how Drain3 + Keep + OpenAI GPT-5.4 + Grafana work together for automated root cause analysis.

### Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-25 | Initial spec |
| 1.1 | 2026-03-25 | Added: startup sequence, database schema, error handling, Grafana plugin choice, model fallback, CORS, ingest timeout note |

---

## 1. Architecture Overview

Single Python service (FastAPI) + external containers. Monolith approach -- minimal infrastructure, maximum speed.

```
Docker Compose (6 containers):

+------------------------------------------------------+
|  aiops-service (Python/FastAPI, port 8081)            |
|                                                       |
|  +-------------+  +--------------+  +-------------+  |
|  | Drain Parser|->|Anomaly Detect|->| Alerter     |--|-->Keep API
|  +-------------+  +--------------+  +-------------+  |
|  +-------------+  +--------------+                   |
|  | AI Agent    |<-| RAG (Chroma) |                   |
|  | (OpenAI)    |  |              |                   |
|  +-------------+  +--------------+                   |
+------------------------------------------------------+
         |                    |                |
+--------+-----+  +----------+---+  +---------+--------+
|  ChromaDB    |  |  Keep stack  |  |  Grafana          |
|  (port 8000) |  |  api: 8080   |  |  (port 3000)      |
|              |  |  ui:  3001   |  |  -> aiops-service  |
|              |  |  db: postgres|  |  -> Keep API       |
+--------------+  +--------------+  +-------------------+
```

**Key decisions:**
- 1 service instead of 2 -- Drain, anomaly detection, alerter, AI agent in one FastAPI app
- SQLite for clusters, anomalies, and reports (file in volume, no extra container)
- Grafana with Infinity datasource plugin (`yesoreyeram-infinity-datasource`) -- connects to aiops-service and Keep API endpoints
- CORS middleware enabled (`allow_origins=["*"]`) for local development
- Keep -- standard deploy (api + ui + postgres), minimal configuration

---

## 2. Code Structure

```
services/aiops/
|-- Dockerfile
|-- requirements.txt
|-- drain3.ini
|-- app/
|   |-- main.py                   # FastAPI app, startup/shutdown
|   |-- config.py                 # Settings (pydantic-settings)
|   |-- db.py                     # SQLite: init, sessions
|   |-- models.py                 # Pydantic models (shared)
|   |
|   |-- drain/
|   |   |-- parser.py             # Drain3 wrapper (TemplateMiner)
|   |   |-- anomaly.py            # IsolationForest on template counts
|   |   |-- alerter.py            # Send alerts to Keep
|   |
|   |-- agent/
|   |   |-- investigator.py       # OpenAI Responses API agentic loop
|   |   |-- tools.py              # Tool definitions (query_metrics, query_logs, etc.)
|   |   |-- prompts.py            # System prompt with anti-failure-mode rules
|   |   |-- rag.py                # ChromaDB: load runbooks, search
|   |
|   |-- adapters/
|   |   |-- openrca.py            # Read OpenRCA CSV (logs, metrics, traces)
|   |
|   |-- api/
|       |-- ingest.py             # POST /ingest/logs, POST /ingest/openrca
|       |-- clusters.py           # GET /clusters, /clusters/{id}, /clusters/timeline
|       |-- anomalies.py          # GET /anomalies
|       |-- investigate.py        # POST /investigate, GET /reports
|       |-- stats.py              # GET /stats (for Grafana)
|       |-- benchmark.py          # POST /benchmark/run, GET /benchmark/results
|
|-- knowledge/
|   |-- runbooks/
|   |-- past_incidents/
|
|-- tests/
```

**Principles:**
- Flat structure, no unnecessary abstractions
- `drain/` and `agent/` -- two logical modules in one process
- `adapters/openrca.py` -- single point for reading OpenRCA data
- `api/` -- thin routes, all logic in `drain/` and `agent/` modules
- `models.py` -- shared Pydantic models for the entire service

---

## 3. Docker Compose

6 containers, 1 network:

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| aiops-service | build: ./services/aiops | 8081 | Main service |
| keep-api | keephq/keep-api | 8080 | Alert management API |
| keep-ui | keephq/keep-ui | 3001 | Keep web UI |
| keep-db | postgres:15 | 5432 | Keep database |
| chromadb | chromadb/chroma | 8000 | Vector store for RAG |
| grafana | grafana/grafana-oss | 3000 | Dashboards |

**Volumes:** `keep-db-data`, `chroma-data`, `./data` (OpenRCA datasets), `./grafana/provisioning`

**Single `.env` file:** `OPENAI_API_KEY` (only manual value), rest has defaults.

### Startup and Initialization Sequence

```
1. docker-compose up -d
2. Docker Compose dependency chain (depends_on + healthcheck):
   keep-db (postgres ready) -> keep-api -> keep-ui
   chromadb (healthcheck: /api/v1/heartbeat)
   aiops-service (waits for: chromadb, keep-api)
3. aiops-service startup (app/main.py lifespan):
   a. Initialize SQLite schema (create tables if not exist)
   b. Initialize Drain3 TemplateMiner
   c. Connect to ChromaDB, create collection if not exists
   d. Load runbooks + past_incidents from knowledge/ into ChromaDB (if not already loaded)
4. scripts/setup_keep.py (run manually once):
   a. Wait for Keep API healthcheck
   b. Create API key -> save to .env as KEEP_API_KEY
   c. Load topology from OpenRCA
   d. Configure dedup + correlation rules
5. Ready for /ingest/openrca calls
```

### Error Handling

- **OpenAI API failures**: retry 3 times with exponential backoff (2s, 4s, 8s). On final failure, return partial report with `confidence: 0` and `error` field.
- **Keep API unreachable**: alerter.py logs warning and queues alerts in SQLite (`pending_alerts` table). Retry automatically on next ingest call.
- **ChromaDB empty**: RAG search returns empty list. Agent proceeds without knowledge base context -- still functional, just without runbook enrichment.
- **Ingest timeout**: batch ingest may take 30-60s for large datasets. FastAPI configured with no request timeout. Client should set timeout >= 120s.

---

## 4. Data Flow (end-to-end pipeline)

```
1. LOAD DATA
   POST /ingest/openrca {dataset: "Bank", date: "2024_01_15"}
   -> openrca.py reads CSV from /data/openrca/

2. LOG PROCESSING
   Each log line -> drain/parser.py (TemplateMiner)
   -> cluster_id + template + params
   -> Saved to SQLite: clusters, log_entries

3. ANOMALY DETECTION
   After batch ingestion:
   -> anomaly.py builds count matrix [window x template]
   -> IsolationForest -> anomaly score per window
   -> Plus: new/rare templates = anomaly
   -> Results -> SQLite: anomalies

4. ALERTING -> KEEP
   For each anomaly:
   -> alerter.py -> POST Keep API /alerts/event/log-processor
   -> Keep deduplicates, enriches, correlates
   -> Keep creates incidents from alert groups

5. AI INVESTIGATION
   POST /investigate {incident_id, system, time_range}
   -> investigator.py loads incident context from Keep
   -> RAG: searches similar runbooks/incidents in ChromaDB
   -> OpenAI Responses API tool-calling loop:
      - query_metrics, query_logs, query_traces
      - get_topology, get_recent_changes
      - search_knowledge_base
   -> Structured JSON report -> SQLite: reports
   -> Report posted as comment to Keep incident

6. VISUALIZATION (Grafana)
   -> Dashboard "Log Clusters": /clusters, /clusters/timeline
   -> Dashboard "Anomalies": /anomalies, /stats
   -> Dashboard "Incidents": Keep API /incidents
   -> Dashboard "AI Reports": /reports
   -> Dashboard "Benchmark": /benchmark/results
```

**Important**: steps 2-4 happen synchronously on `/ingest/openrca` call -- one call triggers the entire pipeline. Step 5 (AI investigation) is a separate manual call after Keep forms incidents.

---

## 5. AI Agent -- GPT-5.4 Responses API

### Why Responses API

- OpenAI recommends it for new projects
- ~3% better on benchmarks (chain-of-thought between turns)
- Strict mode by default (tool schemas validated)
- `instructions` parameter instead of system message
- `previous_response_id` -- no need to resend full history

### Agentic Loop

```python
from openai import OpenAI
import json

client = OpenAI()

def investigate(incident_context: str, tools: list, tool_registry: dict):
    input_list = [
        {"role": "user", "content": incident_context}
    ]

    max_iterations = 20
    for i in range(max_iterations):
        response = client.responses.create(
            model=settings.OPENAI_MODEL,
            instructions=SYSTEM_PROMPT,
            tools=tools,
            input=input_list,
            parallel_tool_calls=True,
        )

        tool_calls = [item for item in response.output
                      if item.type == "function_call"]

        if not tool_calls:
            return json.loads(response.output_text)

        input_list += response.output

        for tc in tool_calls:
            args = json.loads(tc.arguments)
            result = tool_registry[tc.name](**args)
            input_list.append({
                "type": "function_call_output",
                "call_id": tc.call_id,
                "output": json.dumps(result)
            })
```

### Tool Definitions (Responses API format)

Flat structure, strict by default, `additionalProperties: false`:

```python
{
    "type": "function",
    "name": "query_metrics",
    "description": "Query KPI metrics with anomaly analysis for a service",
    "parameters": {
        "type": "object",
        "properties": {
            "service": {"type": "string"},
            "metric_type": {"type": "string",
                           "enum": ["cpu","memory","network","disk","latency","error_rate","all"]},
            "from_time": {"type": "string", "description": "ISO timestamp"},
            "to_time": {"type": "string", "description": "ISO timestamp"}
        },
        "required": ["service","metric_type","from_time","to_time"],
        "additionalProperties": false
    }
}
```

### Agent Tools (6 tools)

| Tool | Implementation | Returns |
|------|---------------|---------|
| `query_metrics` | `adapters/openrca.load_metrics()` | Time series with anomaly deviations, baseline, onset time |
| `query_logs` | SQLite query via `db.py` | Top anomalous templates with % deviation from baseline |
| `query_traces` | `adapters/openrca.load_traces()` | Critical path + bottleneck service |
| `get_topology` | `adapters/openrca.load_topology()` | Service dependency graph |
| `get_recent_changes` | `adapters/openrca.load_ground_truth()` | Deploys with exact timestamps |
| `search_knowledge_base` | `agent/rag.py` -> ChromaDB | Top-3 runbooks + past incidents |

### Deep Investigation Design

**Core principle**: Tools return compressed summaries, not raw data.

```
BAD:  query_logs -> 500 log lines -> LLM: "CPU high = root cause"
GOOD: query_logs -> "payment-api: 3 anomalous templates:
       - 'Connection timeout to db-master' (47x, baseline 2x) +2250%
       - 'Request processing failed' (31x, baseline 5x) +520%
       - 'Health check OK' (normal)"
```

**Three-phase investigation (embedded in system prompt):**

Phase 1 -- OVERVIEW (breadth-first):
- get_topology -> understand dependency graph
- query_metrics FOR ALL services in incident window
- Result: list of anomalous services + anomaly types

Phase 2 -- CAUSAL ANALYSIS (follow upstream):
- For each anomalous service:
  - query_logs -> which templates appeared/increased?
  - query_traces -> where is latency? which span degraded first?
- Build chain: service A <- depends on B <- depends on C
- If A and B both anomalous, investigate B (upstream) first

Phase 3 -- VERIFICATION:
- get_recent_changes -> was there a deploy BEFORE anomaly onset?
- search_knowledge_base -> similar past incident?
- Cross-check: do metrics, logs, and traces agree?

**Anti-failure-mode rules (in system prompt):**

| Failure Mode | Prevention |
|-------------|-----------|
| "CPU high = root cause" | "CPU/memory spike is ALWAYS a symptom. Ask: what CAUSED the load?" |
| Checked only metrics | "MUST check all 3 types: metrics + logs + traces. Report without all three is invalid" |
| First service found = culprit | "Follow dependencies UPSTREAM. If A depends on B and both broken -- cause is in B" |
| Too-short investigation | "Minimum 10 tool calls. < 5 steps = 80% chance of wrong answer" |
| Correlation != causation | "Deploy before incident is NOT proof. Check: right component? Exact timeline match?" |

### Structured Output with Self-Assessment

```json
{
  "root_cause": {
    "component": "db-master",
    "reason": "Lock contention from unindexed query after deploy v2.4.1",
    "onset_time": "2024-01-15T10:11:45Z",
    "confidence": 0.85
  },
  "causal_chain": [
    "db-master: lock contention -> query timeout (10:11:45)",
    "payment-api: connection pool exhausted -> latency spike (10:12:00)",
    "gateway: upstream timeout -> 503 errors to clients (10:12:30)"
  ],
  "evidence": ["..."],
  "data_coverage": {
    "metrics_checked": ["cpu","memory","network","disk","latency","error_rate"],
    "logs_checked": ["gateway","payment-api","db-master"],
    "traces_checked": ["gateway->payment-api->db-master"]
  },
  "investigation_quality": {
    "total_tool_calls": 14,
    "all_data_types_checked": true,
    "upstream_followed": true
  }
}
```

---

## 6. Grafana Dashboards

### Datasources (auto-provisioned)

1. **aiops-service** (Infinity plugin) -> `http://aiops-service:8081`
2. **keep-api** (Infinity plugin) -> `http://keep-api:8080`

### 5 Dashboards

| Dashboard | Panels | Source |
|-----------|--------|--------|
| Log Clusters | Template table, top-10 frequency time series | `/clusters`, `/clusters/timeline` |
| Anomalies | Stats (total logs, templates, anomaly rate), anomaly timeline, anomaly table | `/anomalies`, `/stats` |
| Incidents | Incident table from Keep, stat panels (open/resolved/critical) | Keep API `/incidents` |
| AI Reports | Report table, drill-down (causal chain, evidence, coverage) | `/reports`, `/reports/{id}` |
| Benchmark | Accuracy stats, per-incident comparison table | `/benchmark/results` |

### Provisioning

```
grafana/
|-- provisioning/
    |-- datasources/
    |   |-- datasources.yml
    |-- dashboards/
        |-- dashboards.yml
        |-- log-clusters.json
        |-- anomalies.json
        |-- incidents.json
        |-- ai-reports.json
        |-- benchmark.json
```

Mounted via Docker Compose volumes -- dashboards ready immediately after `docker-compose up`.

### Key API Response Schemas (for Grafana)

**GET /stats**
```json
{
  "total_logs": 12450,
  "unique_templates": 87,
  "anomaly_count": 5,
  "anomaly_rate": 0.04,
  "last_ingest": "2024-01-15T10:30:00Z"
}
```

**GET /clusters/timeline?window=300**
```json
[
  {
    "window_start": "2024-01-15T10:00:00Z",
    "window_end": "2024-01-15T10:05:00Z",
    "clusters": [
      {"cluster_id": 1, "template": "Connection timeout to <*>", "count": 47},
      {"cluster_id": 2, "template": "Request processed in <*>ms", "count": 312}
    ]
  }
]
```

**GET /anomalies**
```json
[
  {
    "id": 1,
    "window_start": "2024-01-15T10:10:00Z",
    "window_end": "2024-01-15T10:15:00Z",
    "score": 0.92,
    "anomaly_type": "isolation_forest",
    "service": "payment-api",
    "details": {
      "top_templates": [
        {"template": "Connection timeout to <*>", "count": 47, "baseline": 2, "deviation": "23.5x"}
      ]
    }
  }
]
```

**POST /investigate -> GET /reports/{id}**
```json
{
  "id": 1,
  "incident_id": "inc-123",
  "created_at": "2024-01-15T10:45:00Z",
  "root_cause": {"component": "db-master", "reason": "...", "onset_time": "...", "confidence": 0.85},
  "causal_chain": ["..."],
  "evidence": ["..."],
  "data_coverage": {"metrics_checked": [], "logs_checked": [], "traces_checked": []},
  "quality": {"total_tool_calls": 14, "all_data_types_checked": true, "upstream_followed": true}
}
```

---

## 7. Keep Configuration

### What we configure

- **Provider**: log-processor as alert source (webhook provider)
- **Deduplication**: fingerprint on `service + template`
- **Correlation**: alerts from same service within 5 min window -> one incident
- **Topology**: load dependency graph from OpenRCA via API

### What we skip (keep it simple)

- Enrichment rules
- CSV service-to-team mapping
- YAML workflow automation
- Slack/Jira integrations

### API Integration

```
aiops-service -> Keep:
  POST /alerts/event/log-processor    # send alerts
  POST /topology                       # load dependency graph

aiops-service <- Keep:
  GET /incidents                       # read incidents for AI agent
  GET /incidents/{id}                  # incident details
  POST /incidents/{id}/comment         # post RCA report
```

### Setup Script

```
scripts/setup_keep.py:
  1. Wait for Keep API readiness (healthcheck loop)
  2. Create API key
  3. Load topology from OpenRCA dataset
  4. Configure deduplication rules
  5. Configure correlation rules
```

Run once after `docker-compose up`.

---

## 8. OpenRCA Data Handling

### Data Directory Structure

```
data/openrca/
|-- Bank/
    |-- 2024_01_15/
        |-- log/          # timestamp, message per service
        |-- metric/       # timestamp, metric_name, value per service
        |-- trace/        # trace_id, span_id, parent, service, duration, status
        |-- record.csv    # ground truth: root cause, timeline, changes
```

### Adapter (`openrca.py`)

| Method | Purpose | Consumer |
|--------|---------|----------|
| `load_logs(dataset, date, service?)` | Read log/*.csv -> List[LogEntry] | Drain parser |
| `load_metrics(dataset, date, service, metric?, time_range?)` | Read metric/*.csv, compute baseline + deviation | AI Agent `query_metrics` |
| `load_traces(dataset, date, time_range?)` | Read trace/*.csv, build critical path | AI Agent `query_traces` |
| `load_topology(dataset)` | Parse traces -> service dependency graph | AI Agent `get_topology` + Keep |
| `load_ground_truth(dataset, date)` | Read record.csv -> actual root cause | Benchmark |

**Key decisions:**
- CSV read via `pandas`
- Cache in memory after first load (datasets are small)
- `load_metrics` computes baseline and deviation internally -- AI Agent receives processed data
- `load_traces` builds critical path by longest span chain -- AI Agent doesn't see raw spans

---

## 9. Configuration

```python
class Settings(BaseSettings):
    # OpenAI
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-5.4"     # fallback: "gpt-4.1" if gpt-5.4 unavailable
    AGENT_MAX_ITERATIONS: int = 20

    # Keep
    KEEP_API_URL: str = "http://keep-api:8080"
    KEEP_API_KEY: str = ""

    # ChromaDB
    CHROMA_URL: str = "http://chromadb:8000"
    CHROMA_COLLECTION: str = "aiops_knowledge"
    # Use OpenAI embeddings to avoid PyTorch dependency in container
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Data
    OPENRCA_DATA_DIR: str = "/data/openrca"
    SQLITE_PATH: str = "/data/aiops.db"

    # Drain
    DRAIN_SIMILARITY: float = 0.4
    DRAIN_DEPTH: int = 4
    DRAIN_MAX_CLUSTERS: int = 1024

    # Anomaly detection
    ANOMALY_WINDOW_SECONDS: int = 300
    ANOMALY_CONTAMINATION: float = 0.1

    class Config:
        env_file = ".env"
```

Only `OPENAI_API_KEY` requires manual setup. Everything else has working defaults for Docker Compose.

---

## 10. Database Schema (SQLite)

```sql
-- Log entries parsed by Drain
CREATE TABLE log_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    service TEXT NOT NULL,
    raw_message TEXT NOT NULL,
    cluster_id INTEGER NOT NULL,
    params TEXT,  -- JSON array of extracted parameters
    dataset TEXT NOT NULL,
    date TEXT NOT NULL
);

-- Drain cluster templates
CREATE TABLE clusters (
    id INTEGER PRIMARY KEY,
    template TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    first_seen TEXT,
    last_seen TEXT
);

-- Detected anomalies
CREATE TABLE anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    score REAL NOT NULL,
    anomaly_type TEXT NOT NULL,  -- 'isolation_forest' | 'new_template' | 'rare_spike'
    service TEXT,
    details TEXT,  -- JSON: contributing templates, deviations
    alert_sent INTEGER DEFAULT 0
);

-- AI investigation reports
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT,
    dataset TEXT,
    date TEXT,
    created_at TEXT NOT NULL,
    root_cause TEXT NOT NULL,      -- JSON: {component, reason, onset_time, confidence}
    causal_chain TEXT,             -- JSON array
    evidence TEXT,                 -- JSON array
    data_coverage TEXT,            -- JSON: {metrics_checked, logs_checked, traces_checked}
    quality TEXT,                  -- JSON: {total_tool_calls, all_data_types_checked, ...}
    correct INTEGER               -- NULL=unknown, 1=correct, 0=incorrect (benchmark)
);

-- Pending alerts (retry queue for Keep failures)
CREATE TABLE pending_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,          -- JSON alert body
    retry_count INTEGER DEFAULT 0
);
```

---

## 11. Benchmark and Validation

```
POST /benchmark/run {dataset: "Bank", dates: ["2024_01_15", ...]}
```

For each incident:
1. Ingest data -> Drain -> Anomaly -> Keep
2. AI Agent investigation -> report
3. Compare `report.root_cause.component` with `record.csv.root_cause`

**Metrics:**
- **Top-1 accuracy**: exact component match
- **Top-3 accuracy**: root cause anywhere in causal_chain
- **Avg tool calls**: investigation depth
- **Avg confidence**: agent self-assessment vs actual accuracy

**Result endpoint**: `GET /benchmark/results` -- feeds Grafana Benchmark dashboard.

**Benchmark workflow**: `POST /benchmark/run` handles the full loop automatically -- ingest, Drain, anomaly detection, Keep alerting, AI investigation, and comparison with ground truth. No manual steps required.

---

## 12. Technology Stack Summary

| Layer | Technology |
|-------|-----------|
| API framework | FastAPI |
| Log parsing | Drain3 (TemplateMiner) |
| Anomaly detection | scikit-learn (IsolationForest) |
| LLM | OpenAI GPT-5.4 (Responses API) |
| Embeddings | OpenAI text-embedding-3-small |
| Vector store | ChromaDB |
| Alert management | Keep (keephq) |
| Dashboards | Grafana + Infinity datasource plugin |
| Database | SQLite (aiops-service), PostgreSQL (Keep) |
| Data processing | pandas |
| Config | pydantic-settings |
| Containers | Docker Compose |
