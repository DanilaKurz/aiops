# AIOps MVP

Exploratory prototype evaluating how **Drain3 + Keep + OpenAI GPT-5.4 + Grafana** work together for automated root cause analysis (RCA) of production incidents.

## What It Does

```
OpenRCA logs --> Drain3 (template extraction) --> IsolationForest (anomaly detection)
    --> Keep (alert management, incident correlation)
        --> GPT-5.4 AI Agent (tool-calling investigation)
            --> Structured RCA Report --> Grafana dashboards
```

1. **Ingest** -- loads log/metric/trace data from OpenRCA dataset
2. **Parse** -- Drain3 extracts log templates, groups similar messages into clusters
3. **Detect** -- IsolationForest finds anomalous time windows by template count patterns
4. **Alert** -- anomalies are sent as alerts to Keep, which correlates them into incidents
5. **Investigate** -- AI agent (GPT-5.4) uses 6 tools to query metrics, logs, traces, topology, and knowledge base, following a 3-phase protocol (overview -> causal analysis -> verification)
6. **Report** -- structured JSON report with root cause, causal chain, evidence, and confidence score
7. **Visualize** -- 5 pre-configured Grafana dashboards

## Architecture

Single FastAPI service + 5 external containers:

| Service | Port | Purpose |
|---------|------|---------|
| aiops-service | 8081 | Main service (Drain + Anomaly + AI Agent + API) |
| keep-api | 8080 | Alert management API |
| keep-ui | 3001 | Keep web interface |
| keep-db | 5432 | PostgreSQL for Keep |
| chromadb | 8000 | Vector store for RAG knowledge base |
| grafana | 3000 | Dashboards |

## Prerequisites

- Docker Desktop
- Python 3.12+
- OpenAI API key (GPT-5.4)

## Quick Start

### 1. Clone and configure

```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### 2. Download OpenRCA data

```bash
# Clone OpenRCA repository
git clone https://github.com/microsoft/OpenRCA.git data/openrca

# Download telemetry datasets from Google Drive (manual step)
# Place into data/openrca/Bank/, data/openrca/Telecom/, etc.
```

### 3. Start all services

```bash
docker compose up -d
```

Wait for all containers to be healthy (~30-60 seconds).

### 4. Configure Keep (one-time)

```bash
py scripts/setup_keep.py --data-dir ./data/openrca --dataset Bank
# Copy the API key from output into .env, then restart aiops-service:
docker compose restart aiops-service
```

### 5. Ingest data and run pipeline

```bash
# Ingest OpenRCA Bank dataset
curl -X POST http://localhost:8081/ingest/openrca \
  -H "Content-Type: application/json" \
  -d '{"dataset": "Bank", "date": "2024_01_15"}'

# Check results
curl http://localhost:8081/stats
curl http://localhost:8081/clusters
curl http://localhost:8081/anomalies
```

### 6. Run AI investigation

```bash
curl -X POST http://localhost:8081/investigate \
  -H "Content-Type: application/json" \
  -d '{"incident_id": "test-1", "dataset": "Bank", "date": "2024_01_15"}'
```

### 7. Run benchmark

```bash
curl -X POST http://localhost:8081/benchmark/run \
  -H "Content-Type: application/json" \
  -d '{"dataset": "Bank", "dates": ["2024_01_15"]}'
```

### 8. View dashboards

- Grafana: http://localhost:3000 (admin/admin)
- Keep UI: http://localhost:3001

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /ingest/openrca | Ingest OpenRCA dataset (full pipeline) |
| POST | /ingest/logs | Ingest raw log lines |
| GET | /clusters | List all Drain template clusters |
| GET | /clusters/{id} | Cluster detail |
| GET | /clusters/timeline | Template counts per time window |
| GET | /anomalies | List detected anomalies |
| GET | /stats | Aggregate statistics |
| POST | /investigate | Run AI investigation |
| GET | /reports | List investigation reports |
| GET | /reports/{id} | Report detail |
| POST | /benchmark/run | Run full benchmark |
| GET | /benchmark/results | Benchmark accuracy results |

## AI Agent Design

The agent follows a **3-phase investigation protocol** to avoid common RCA failures:

**Phase 1 -- Overview**: query topology and metrics for ALL services to identify anomalous components.

**Phase 2 -- Causal Analysis**: follow dependencies UPSTREAM. If service A depends on B and both are degraded, investigate B first.

**Phase 3 -- Verification**: cross-check with recent changes and knowledge base. Correlation is not causation.

**Anti-failure rules** prevent the agent from:
- Treating CPU/memory spikes as root causes (they are symptoms)
- Checking only one data type (must check metrics + logs + traces)
- Stopping too early (minimum 10 tool calls)

## Development

### Run tests

```bash
cd services/aiops
py -m pytest tests/ -v
```

### Project structure

```
services/aiops/app/
  config.py          # Settings (pydantic-settings)
  models.py          # Pydantic models
  db.py              # SQLite schema + helpers
  main.py            # FastAPI app with lifespan
  drain/
    parser.py        # Drain3 wrapper
    anomaly.py       # IsolationForest
    alerter.py       # Keep alert sender
  agent/
    investigator.py  # GPT-5.4 Responses API loop
    tools.py         # 6 tool definitions
    prompts.py       # System prompt
    rag.py           # ChromaDB knowledge base
  adapters/
    openrca.py       # OpenRCA CSV reader
  api/
    ingest.py        # Ingest endpoints
    clusters.py      # Cluster endpoints
    anomalies.py     # Anomaly endpoints
    stats.py         # Stats endpoint
    investigate.py   # Investigation endpoints
    benchmark.py     # Benchmark endpoints
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI |
| Log parsing | Drain3 |
| Anomaly detection | scikit-learn (IsolationForest) |
| LLM | OpenAI GPT-5.4 (Responses API) |
| Embeddings | OpenAI text-embedding-3-small |
| Vector store | ChromaDB |
| Alert management | Keep |
| Dashboards | Grafana + Infinity plugin |
| Database | SQLite / PostgreSQL (Keep) |
| Containers | Docker Compose |
