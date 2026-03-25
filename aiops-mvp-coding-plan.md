# AIOps MVP Pipeline — Plan for Coding Agent

## Project Summary

Build a modern AIOps pipeline from open-source components:
- **Keep** (keephq/keep) — alert management, correlation, workflows
- **Drain** — log parsing and template clustering
- **HolmesGPT** (robusta-dev/holmesgpt) — AI agent for alert investigation
- **Custom Dashboard** — visualization of log clusters, anomalies, incidents
- **OpenRCA** dataset — for testing and benchmarking

Stack: Python (FastAPI), Docker Compose, React (dashboards), LLM (Claude API / OpenAI / Ollama).

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  DATA SOURCES                                                │
│  OpenRCA datasets (Telecom/Bank/Market) — logs, metrics,     │
│  traces as test data. Later: real Prometheus/Loki/Jaeger.     │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: LOG PROCESSING SERVICE (custom, Python)            │
│                                                              │
│  1.1 Drain Parser — raw logs → templates + params            │
│  1.2 Template Clustering — group templates by similarity     │
│  1.3 Anomaly Detection — Isolation Forest on template counts │
│  1.4 Alert Generation — anomalous clusters → Keep alerts     │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2: KEEP (alert management platform)                   │
│                                                              │
│  2.1 Ingestion — receive alerts from log processor + metrics │
│  2.2 Enrichment — extraction rules, mapping (CSV/topology)   │
│  2.3 Deduplication — fingerprint-based                       │
│  2.4 Correlation — rules + topology processor                │
│  2.5 Incident Management — create/merge/resolve incidents    │
│  2.6 Workflows — YAML automations (Slack, Jira, etc.)        │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 3: AI INVESTIGATION (HolmesGPT + custom wrapper)      │
│                                                              │
│  3.1 Trigger — on critical incidents from Keep               │
│  3.2 Tools — query metrics, search logs, read traces         │
│  3.3 RAG — runbooks + past incidents (ChromaDB)              │
│  3.4 Output — structured RCA report → back to Keep           │
└──────────────────────────┬──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 4: DASHBOARD (React / Grafana)                        │
│                                                              │
│  4.1 Log Cluster View — Drain templates, frequencies, trends │
│  4.2 Anomaly Timeline — detected anomalies over time         │
│  4.3 Incident Dashboard — from Keep API                      │
│  4.4 AI Investigation View — RCA reports, reasoning chains   │
│  4.5 Service Topology Graph — dependency map                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Infrastructure Setup

### Task 1.1: Docker Compose for full stack

Create `docker-compose.yml` with all services:

```yaml
services:
  # Keep AIOps Platform
  keep-api:
    image: us-central1-docker.pkg.dev/keephq/keep/keep-api:latest
    ports: ["8080:8080"]
    environment:
      - DATABASE_URL=postgresql://keep:keep@keep-db:5432/keep
      - SECRET_KEY=your-secret-key
      - KEEP_TOPOLOGY_PROCESSOR=true
      - KEEP_TOPOLOGY_PROCESSOR_INTERVAL=10
    depends_on: [keep-db]

  keep-ui:
    image: us-central1-docker.pkg.dev/keephq/keep/keep-ui:latest
    ports: ["3000:3000"]
    environment:
      - API_URL=http://keep-api:8080
      - NEXTAUTH_SECRET=your-secret

  keep-db:
    image: postgres:15
    environment:
      - POSTGRES_USER=keep
      - POSTGRES_PASSWORD=keep
      - POSTGRES_DB=keep
    volumes: ["keep-db-data:/var/lib/postgresql/data"]

  # Log Processing Service (custom)
  log-processor:
    build: ./services/log-processor
    ports: ["8081:8081"]
    environment:
      - KEEP_API_URL=http://keep-api:8080
      - KEEP_API_KEY=${KEEP_API_KEY}
    volumes:
      - ./data:/data  # OpenRCA datasets mounted here

  # AI Agent Service (custom wrapper around HolmesGPT)
  ai-agent:
    build: ./services/ai-agent
    ports: ["8082:8082"]
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - KEEP_API_URL=http://keep-api:8080
      - CHROMA_URL=http://chromadb:8000
      - LOG_PROCESSOR_URL=http://log-processor:8081

  # RAG Vector Store
  chromadb:
    image: chromadb/chroma:latest
    ports: ["8000:8000"]
    volumes: ["chroma-data:/chroma/chroma"]

  # Dashboard (custom React app)
  dashboard:
    build: ./services/dashboard
    ports: ["3001:3000"]
    environment:
      - KEEP_API_URL=http://keep-api:8080
      - LOG_PROCESSOR_URL=http://log-processor:8081

volumes:
  keep-db-data:
  chroma-data:
```

### Task 1.2: Download and prepare OpenRCA datasets

```bash
# Script: scripts/setup_data.sh

# Clone OpenRCA
git clone https://github.com/microsoft/OpenRCA.git data/openrca

# Download telemetry from Google Drive (manual step or gdown)
# Place into data/openrca/dataset/
# Expected structure:
#   data/openrca/dataset/
#     Bank/
#       query.csv, record.csv
#       telemetry/YYYY_MM_DD/log/, metric/, trace/
#     Telecom/
#       ...
#     Market/
#       ...

# Also download Loghub for additional log datasets
git clone https://github.com/logpai/loghub.git data/loghub
```

### Task 1.3: Project directory structure

```
aiops-mvp/
├── docker-compose.yml
├── .env                          # API keys, secrets
├── scripts/
│   ├── setup_data.sh             # Download datasets
│   └── seed_keep.sh              # Seed Keep with topology + providers
├── services/
│   ├── log-processor/            # Phase 2
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── app/
│   │   │   ├── main.py           # FastAPI app
│   │   │   ├── drain_parser.py   # Drain implementation
│   │   │   ├── anomaly.py        # Isolation Forest anomaly detection
│   │   │   ├── alerter.py        # Send alerts to Keep
│   │   │   ├── models.py         # Data models
│   │   │   └── api/
│   │   │       ├── clusters.py   # API: get log clusters
│   │   │       ├── anomalies.py  # API: get anomalies
│   │   │       └── ingest.py     # API: ingest logs
│   │   └── tests/
│   ├── ai-agent/                 # Phase 3
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── app/
│   │   │   ├── main.py           # FastAPI app
│   │   │   ├── investigator.py   # HolmesGPT wrapper / custom agent
│   │   │   ├── tools.py          # Tool definitions for agent
│   │   │   ├── rag.py            # RAG retrieval from ChromaDB
│   │   │   ├── prompts.py        # System prompts (anti-failure-mode)
│   │   │   └── api/
│   │   │       ├── investigate.py
│   │   │       └── reports.py
│   │   └── knowledge/            # Runbooks, past incidents for RAG
│   │       ├── runbooks/
│   │       └── past_incidents/
│   └── dashboard/                # Phase 4
│       ├── Dockerfile
│       ├── package.json
│       └── src/
│           ├── App.jsx
│           ├── pages/
│           │   ├── LogClusters.jsx
│           │   ├── Anomalies.jsx
│           │   ├── Incidents.jsx
│           │   ├── Investigation.jsx
│           │   └── Topology.jsx
│           └── components/
├── data/                         # Datasets (gitignored)
│   ├── openrca/
│   └── loghub/
└── docs/
    └── architecture.md
```

---

## Phase 2: Log Processing Service (Drain + Anomaly Detection)

### Task 2.1: Drain Parser Implementation

File: `services/log-processor/app/drain_parser.py`

Implement Drain algorithm for online log parsing.
Use the `drain3` library (PyPI: `drain3`) — production-ready Drain implementation by IBM.

```python
# Key functionality:
# 1. Accept raw log lines
# 2. Parse each line → extract template + parameters
# 3. Maintain template cluster tree (in-memory + periodic persistence)
# 4. Expose API: get all templates, get template by ID, get cluster stats

# drain3 config (drain3.ini):
# [DRAIN]
# sim_th = 0.4           # Similarity threshold (0.0-1.0)
# depth = 4              # Tree depth
# max_children = 100     # Max children per node
# max_clusters = 1024    # Max number of clusters
# extra_delimiters = ["_"]

# Core flow:
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

config = TemplateMinerConfig()
config.load("drain3.ini")
miner = TemplateMiner(config=config)

# For each log line:
result = miner.add_log_message(log_line)
# result.cluster_id — template cluster ID
# result.template_mined — extracted template string
# result.change_type — "cluster_created" | "cluster_template_changed" | "none"
```

Key requirements:
- Store cluster stats in SQLite or in-memory dict: `{cluster_id: {template, count, first_seen, last_seen, example_params}}`
- Expose REST API for dashboard consumption
- Support batch ingestion (for OpenRCA dataset loading) and streaming (for real-time)

### Task 2.2: Anomaly Detection on Log Templates

File: `services/log-processor/app/anomaly.py`

Two anomaly detection approaches:

**A) Template count anomaly (time-series):**
```python
# For each time window (e.g., 5 min), count occurrences of each template
# Build a feature vector: [template_1_count, template_2_count, ...]
# Use Isolation Forest to detect anomalous windows

from sklearn.ensemble import IsolationForest

# 1. Build count matrix: rows=time_windows, cols=template_ids
# 2. Train Isolation Forest on "normal" windows
# 3. Predict on new windows → anomaly score
# 4. If anomalous → identify which templates spiked (contribution analysis)
```

**B) New/rare template detection:**
```python
# If Drain produces a new cluster (change_type == "cluster_created"),
# and the template has never been seen before → flag as anomaly
# Also flag templates that suddenly spike in frequency (>3x baseline)
```

### Task 2.3: Alert Generation → Keep

File: `services/log-processor/app/alerter.py`

When anomaly detected, send alert to Keep via REST API:

```python
import httpx

async def send_alert_to_keep(anomaly):
    alert = {
        "name": f"Log anomaly: {anomaly.template_summary}",
        "severity": anomaly.severity,  # "warning" | "critical"
        "source": ["log-processor"],
        "service": anomaly.service,
        "description": (
            f"Template '{anomaly.template}' appeared {anomaly.count}x "
            f"in last {anomaly.window_minutes}min "
            f"(baseline: {anomaly.baseline_count}x). "
            f"Example: {anomaly.example_log}"
        ),
        "labels": {
            "cluster_id": str(anomaly.cluster_id),
            "template": anomaly.template,
            "anomaly_type": anomaly.anomaly_type,
            "anomaly_score": str(anomaly.score)
        }
    }
    
    await httpx.AsyncClient().post(
        f"{KEEP_API_URL}/alerts/event/log-processor",
        json=alert,
        headers={"x-api-key": KEEP_API_KEY}
    )
```

### Task 2.4: Log Processor REST API

File: `services/log-processor/app/main.py`

FastAPI endpoints for dashboard and agent consumption:

```python
# Endpoints:

# POST /ingest/logs
# Body: {"logs": ["line1", "line2", ...], "source": "bank", "service": "payment-api"}
# → Parse with Drain, detect anomalies, send alerts to Keep

# POST /ingest/openrca
# Body: {"dataset": "Bank", "date": "2024_01_15"}
# → Load OpenRCA log files, batch-process through Drain

# GET /clusters
# → List all Drain template clusters with stats
# Response: [{cluster_id, template, count, first_seen, last_seen, trend}]

# GET /clusters/{cluster_id}
# → Detail of a specific cluster: template, example logs, params, timeline

# GET /clusters/timeline
# Query: ?window=5m&from=2024-01-15T10:00:00&to=2024-01-15T11:00:00
# → Time-series of template counts per window (for dashboard charts)

# GET /anomalies
# Query: ?from=...&to=...&severity=critical
# → List of detected anomalies with scores and contributing templates

# GET /stats
# → Overall stats: total logs processed, unique templates, anomaly rate
```

### Task 2.5: OpenRCA Data Adapter

File: `services/log-processor/app/openrca_adapter.py`

Read OpenRCA dataset format and feed into Drain:

```python
# OpenRCA log structure:
#   dataset/{SYSTEM}/telemetry/{DATE}/log/
#     Contains CSV or text files with log entries
#
# Each log line typically has: timestamp, component, level, message
#
# Steps:
# 1. Read log files for a given system+date
# 2. Parse each line: extract timestamp, component, raw message
# 3. Feed raw message into Drain
# 4. Tag the resulting template with system, component, timestamp
# 5. Store in time-bucketed structure for anomaly detection

# Also read OpenRCA metric/ and trace/ directories:
#   metric/ — CSV files with KPI time series
#   trace/ — CSV files with span data (trace_id, span_id, parent_span_id,
#            service, operation, duration, status)
#
# These need separate adapters that the AI agent can query.
```

---

## Phase 3: AI Agent Service (HolmesGPT-based)

### Task 3.1: Choose agent approach

Two options — pick one:

**Option A: Use HolmesGPT directly**
```bash
pip install holmesgpt
# Configure with Keep webhook: when Keep creates critical incident,
# HolmesGPT investigates automatically.
# HolmesGPT has built-in tools for kubectl, Prometheus, etc.
# For OpenRCA data, we need custom tool plugins.
```

**Option B: Custom agent with tool-calling (recommended for OpenRCA)**
Build a custom FastAPI service that wraps an LLM with tool-calling.
This gives us full control over:
- Which tools the agent has (query OpenRCA data, search Drain clusters, etc.)
- The system prompt (anti-failure-mode instructions from OpenRCA research)
- The investigation protocol (mandatory multi-modal checks)
- Output format (structured JSON RCA report)

### Task 3.2: Agent Tools

File: `services/ai-agent/app/tools.py`

Define tools the agent can call:

```python
TOOLS = [
    {
        "name": "query_metrics",
        "description": "Query KPI metrics for a service/component in a time range",
        "parameters": {
            "service": "string — service name",
            "metric_type": "string — cpu|memory|network|disk|latency|error_rate",
            "from_time": "string — ISO timestamp",
            "to_time": "string — ISO timestamp"
        }
        # Implementation: read from OpenRCA metric/ CSVs
        # or query Prometheus API in production
    },
    {
        "name": "query_logs",
        "description": "Search parsed log templates for a service in a time range",
        "parameters": {
            "service": "string",
            "from_time": "string",
            "to_time": "string",
            "severity_filter": "string — optional, error|warning|critical"
        }
        # Implementation: query log-processor API /clusters/timeline
    },
    {
        "name": "query_traces",
        "description": "Get trace data showing request flow and latency between services",
        "parameters": {
            "service": "string — starting service",
            "from_time": "string",
            "to_time": "string",
            "anomalous_only": "boolean — if true, return only anomalous traces"
        }
        # Implementation: read from OpenRCA trace/ CSVs
        # Return compressed trace format (critical path + anomalies only)
    },
    {
        "name": "get_topology",
        "description": "Get service dependency graph",
        "parameters": {
            "system": "string — Telecom|Bank|Market"
        }
        # Implementation: return pre-loaded topology from OpenRCA
    },
    {
        "name": "get_recent_changes",
        "description": "Get recent deployments or configuration changes",
        "parameters": {
            "service": "string",
            "from_time": "string"
        }
        # Implementation: read from OpenRCA record.csv
    },
    {
        "name": "search_knowledge_base",
        "description": "Search runbooks and past incidents for similar issues",
        "parameters": {
            "query": "string — describe the issue"
        }
        # Implementation: RAG search in ChromaDB
    }
]
```

### Task 3.3: System Prompt

File: `services/ai-agent/app/prompts.py`

The system prompt encodes lessons from OpenRCA failure analysis:

```python
SYSTEM_PROMPT = """
You are an expert SRE investigating a production incident.
You have access to tools for querying metrics, logs, traces, topology, and knowledge base.

## MANDATORY INVESTIGATION PROTOCOL

You MUST follow these rules. Violations produce wrong answers.

### Rule 1: Check ALL data types
Before any conclusion, you MUST query:
- Metrics (CPU, memory, network, disk, latency, error_rate)
- Logs (search for error/warning templates in affected services)
- Traces (request flow, latency breakdown between services)
Skipping ANY data type is a critical error.

### Rule 2: Check ALL metric categories
Do not only check CPU. You must also check: memory, network, disk, latency.
Network faults often cannot be identified from CPU/memory alone.
Use trace latency between parent and child spans to detect network issues.

### Rule 3: Distinguish symptoms from causes
The first anomaly you find is likely a SYMPTOM, not the root cause.
Always follow the dependency chain UPSTREAM.
If Service A depends on Service B, and both are degraded, investigate B first.
Use get_topology() to understand dependencies.

### Rule 4: Verify change correlation
If you suspect a deployment caused the issue, VERIFY:
1. Get the exact deployment time with get_recent_changes()
2. Check if anomaly onset is AFTER the deployment
3. Check if the deployment affected the specific component

### Rule 5: Reason deeply
Your investigation must be at least 10 steps.
Short investigations (< 5 steps) consistently produce wrong answers.
Think step by step. Form hypotheses. Test each one.

### Rule 6: Use compressed data wisely
Trace data is provided in compressed form (critical path + anomalies only).
Focus on: which span has the highest latency relative to its baseline?
That span's service is likely closest to the root cause.

## OUTPUT FORMAT

After investigation, output a JSON object:
{
  "root_cause": {
    "component": "exact component name",
    "reason": "exact failure reason",
    "occurrence_datetime": "YYYY-MM-DD HH:MM:SS",
    "confidence": 0.0-1.0
  },
  "evidence": ["list of key observations"],
  "investigation_steps": ["summary of each step taken"],
  "data_sources_checked": {
    "metrics": ["list of metric types checked"],
    "logs": ["list of services whose logs were checked"],
    "traces": ["list of services whose traces were checked"]
  },
  "suggested_remediation": ["list of recommended actions"]
}

## CURRENT INCIDENT
{incident_context}
"""
```

### Task 3.4: RAG Knowledge Base Setup

File: `services/ai-agent/app/rag.py`

```python
# On startup:
# 1. Load runbooks from knowledge/ directory into ChromaDB
# 2. Load past OpenRCA resolved incidents as "past incidents"
# 3. Use sentence-transformers for embeddings

# Runbook format (Markdown files):
# knowledge/runbooks/cpu_high.md
# knowledge/runbooks/db_connection_pool.md
# knowledge/runbooks/network_partition.md

# Past incident format (JSON files):
# knowledge/past_incidents/inc_001.json
# {
#   "title": "Payment API CPU spike caused by unindexed query",
#   "root_cause": "Missing index on orders.customer_id",
#   "symptoms": ["CPU > 95%", "Latency p99 > 5s", "503 errors"],
#   "resolution": "Added index, rolled back to v2.3.0",
#   "affected_services": ["payment-api", "postgres"]
# }

# Retrieval: on query, return top 3 runbooks + top 3 past incidents
```

### Task 3.5: Agent API

File: `services/ai-agent/app/main.py`

```python
# POST /investigate
# Body: {
#   "incident_id": "inc-123",
#   "system": "Bank",
#   "query": "What caused the payment service degradation between 10:10 and 10:40?",
#   "time_range": {"from": "...", "to": "..."},
#   "alerts": [... list of correlated alerts from Keep ...],
#   "topology": {... service dependency graph ...}
# }
# Response: structured RCA report (JSON)

# GET /reports
# → List all investigation reports

# GET /reports/{investigation_id}
# → Get a specific report with full reasoning chain

# POST /feedback
# Body: {"investigation_id": "...", "correct": true/false, "correction": "..."}
# → Store feedback for future RAG improvement
```

### Task 3.6: Integration with Keep

Keep workflow triggers AI investigation:

```yaml
# keep-workflows/ai-investigation.yaml
workflow:
  id: trigger-ai-investigation
  description: "Trigger AI investigation for critical incidents"
  triggers:
    - type: incident
      filters:
        - key: severity
          value: critical
  actions:
    - name: investigate
      provider:
        type: http
      with:
        url: "http://ai-agent:8082/investigate"
        method: POST
        body:
          incident_id: "{{ incident.id }}"
          query: "Investigate root cause: {{ incident.name }}"
          alerts: "{{ incident.alerts }}"
    - name: post-results-to-keep
      provider:
        type: http
      with:
        url: "{{ keep_api }}/incidents/{{ incident.id }}/comment"
        method: POST
        body:
          text: "AI Investigation: {{ steps.investigate.results.root_cause }}"
```

---

## Phase 4: Dashboard

### Task 4.1: Dashboard Architecture

React app (Vite + React + Tailwind + Recharts/D3).
Reads data from:
- Log Processor API (port 8081) — clusters, anomalies, timelines
- Keep API (port 8080) — alerts, incidents
- AI Agent API (port 8082) — investigation reports

### Task 4.2: Pages to Build

**Page 1: Log Clusters Overview**
- Table of all Drain templates: template text, count, trend (sparkline), last seen
- Sort by count, recency, anomaly score
- Click on cluster → drill-down: example logs, parameter distribution, timeline chart
- Color-code by severity (error templates = red, warning = yellow)
- Search/filter by service, template text, time range

**Page 2: Cluster Timeline (heatmap)**
- X-axis: time (5-min buckets)
- Y-axis: template clusters (top N by frequency)
- Cell color: intensity = count (white→yellow→red)
- Highlight anomalous windows (detected by Isolation Forest)
- Click on cell → show example logs from that window

**Page 3: Anomaly Feed**
- Real-time feed of detected anomalies
- Each card: timestamp, affected service, anomaly type, contributing templates, score
- Link to corresponding Keep alert/incident
- Timeline chart: anomaly count over time

**Page 4: Incidents (from Keep)**
- Pull from Keep API: /incidents
- For each incident: severity, status, alert count, services affected, timeline
- If AI investigation exists → show RCA summary inline
- Correlation visualization: which alerts were grouped and why

**Page 5: AI Investigation Report**
- Investigation ID, incident link
- Reasoning chain: step-by-step (collapsible)
- Evidence list
- Root cause with confidence score
- Data coverage checklist: ✅ metrics ✅ logs ✅ traces (or ❌ if missed)
- Suggested remediation
- Feedback buttons: 👍 Correct / 👎 Wrong + correction field

**Page 6: Service Topology**
- Graph visualization of services and dependencies (D3 force layout or dagre)
- Nodes colored by status (green=OK, yellow=warning, red=critical)
- Edge thickness = request volume
- Click on node → show related alerts, recent anomalies
- Overlay: highlight services involved in current incidents

### Task 4.3: API Integration Layer

```typescript
// services/dashboard/src/api/

// logProcessor.ts
export const getClusters = () => fetch(`${LOG_PROCESSOR_URL}/clusters`)
export const getClusterTimeline = (params) => 
  fetch(`${LOG_PROCESSOR_URL}/clusters/timeline?${params}`)
export const getAnomalies = (params) => 
  fetch(`${LOG_PROCESSOR_URL}/anomalies?${params}`)
export const getStats = () => fetch(`${LOG_PROCESSOR_URL}/stats`)

// keep.ts
export const getAlerts = () => fetch(`${KEEP_API_URL}/alerts`)
export const getIncidents = () => fetch(`${KEEP_API_URL}/incidents`)
export const getTopology = () => fetch(`${KEEP_API_URL}/topology`)

// aiAgent.ts
export const getReports = () => fetch(`${AI_AGENT_URL}/reports`)
export const getReport = (id) => fetch(`${AI_AGENT_URL}/reports/${id}`)
export const submitFeedback = (id, data) => 
  fetch(`${AI_AGENT_URL}/feedback`, {method: 'POST', body: JSON.stringify(data)})
```

---

## Phase 5: OpenRCA Benchmark Testing

### Task 5.1: End-to-end test script

```python
# scripts/run_openrca_benchmark.py

# 1. For each OpenRCA query (dataset/Bank/query.csv):
#    a. Load telemetry for the time window
#    b. Feed logs through log-processor (Drain + anomaly detection)
#    c. Feed metric anomalies as alerts to Keep
#    d. Let Keep correlate → create incidents
#    e. Trigger AI agent investigation
#    f. Collect agent's prediction

# 2. Compare predictions with ground truth (record.csv)
#    Using OpenRCA evaluation script:
#    python -m main.evaluate -p predictions.csv -q query.csv

# 3. Output: accuracy score, comparison with baseline (11.34%)
```

### Task 5.2: Metrics to track

```python
# Track and report:
# - Drain: unique templates found, avg template stability
# - Noise reduction: raw log lines → Drain clusters → anomalies → alerts → incidents
# - AI agent: accuracy (correct root causes / total), avg steps, avg latency
# - Data coverage: % of investigations that checked all 3 data types
# - Comparison: our accuracy vs OpenRCA baseline (11.34%)
```

---

## Implementation Order

### Sprint 1 (days 1-3): Foundation
1. ✅ Create project structure
2. ✅ Set up docker-compose with Keep + Postgres
3. ✅ Verify Keep is running (UI accessible, API responsive)
4. ✅ Download OpenRCA dataset, verify structure

### Sprint 2 (days 4-7): Log Processor
5. ✅ Implement Drain parser with drain3 library
6. ✅ Build OpenRCA log adapter (read log CSVs → feed Drain)
7. ✅ Implement template count time-series + Isolation Forest anomaly detection
8. ✅ Build alerter: anomalies → Keep alerts via REST API
9. ✅ Build REST API for clusters, anomalies, timelines
10. ✅ Test: load Bank logs → verify Drain templates → verify anomalies → verify alerts in Keep

### Sprint 3 (days 8-10): Keep Configuration
11. ✅ Configure Keep providers (log-processor as custom provider)
12. ✅ Set up deduplication rules (fingerprint on service + template)
13. ✅ Set up enrichment: extraction rules for log template metadata
14. ✅ Set up mapping: CSV with service → team → SLA tier
15. ✅ Set up correlation rules: same-service, same-host, topology-based
16. ✅ Load OpenRCA topology into Keep service topology
17. ✅ Create Keep workflow: critical incident → trigger AI agent

### Sprint 4 (days 11-14): AI Agent
18. ✅ Build agent service with tool-calling (Anthropic API or OpenAI)
19. ✅ Implement tools: query_metrics, query_logs, query_traces (read from OpenRCA)
20. ✅ Implement compressed trace format for LLM consumption
21. ✅ Set up ChromaDB with sample runbooks
22. ✅ Write system prompt with anti-failure-mode instructions
23. ✅ Build /investigate endpoint
24. ✅ Test: trigger investigation from Keep → verify structured output

### Sprint 5 (days 15-18): Dashboard
25. ✅ Set up React app (Vite + Tailwind)
26. ✅ Build Log Clusters page (table + drill-down)
27. ✅ Build Cluster Timeline heatmap
28. ✅ Build Anomaly Feed
29. ✅ Build Incidents page (from Keep API)
30. ✅ Build AI Investigation Report page
31. ✅ Build Service Topology graph (D3)

### Sprint 6 (days 19-21): Integration & Benchmarking
32. ✅ End-to-end flow: OpenRCA logs → Drain → Keep → AI Agent → Dashboard
33. ✅ Run OpenRCA benchmark, measure accuracy
34. ✅ Compare with baseline (11.34%), document results
35. ✅ Write README with setup instructions

---

## Key Dependencies (pip / npm)

### Python (log-processor + ai-agent)
```
# services/log-processor/requirements.txt
fastapi==0.115.*
uvicorn==0.34.*
drain3==0.9.*
scikit-learn==1.6.*
pandas==2.2.*
numpy==2.1.*
httpx==0.28.*
pydantic==2.10.*

# services/ai-agent/requirements.txt
fastapi==0.115.*
uvicorn==0.34.*
anthropic==0.49.*    # or openai
chromadb==0.6.*
sentence-transformers==3.4.*
httpx==0.28.*
pydantic==2.10.*
```

### Node.js (dashboard)
```json
{
  "dependencies": {
    "react": "^19",
    "react-dom": "^19",
    "recharts": "^2.15",
    "d3": "^7",
    "@tanstack/react-query": "^5",
    "tailwindcss": "^4"
  }
}
```

---

## Key Reference Links

- Keep docs: https://docs.keephq.dev
- Keep GitHub: https://github.com/keephq/keep
- HolmesGPT: https://github.com/robusta-dev/holmesgpt
- drain3 (IBM): https://github.com/logpai/Drain3
- OpenRCA: https://github.com/microsoft/OpenRCA
- OpenRCA paper: https://openreview.net/forum?id=M4qNIzQYpd
- Loghub datasets: https://github.com/logpai/loghub
- awesome-LLM-AIOps: https://github.com/Jun-jie-Huang/awesome-LLM-AIOps
- RCAEval: https://github.com/phamquiluan/RCAEval
- AIOpsLab: https://github.com/microsoft/AIOpsLab
- DevOps datasets collection: https://github.com/mooselab/DevOpsDataCollection

---

## Success Criteria

1. **Pipeline works end-to-end:** OpenRCA logs → Drain → anomalies → Keep alerts → incidents → AI investigation → structured RCA report
2. **Noise reduction measurable:** raw log lines → templates → anomalies → alerts → incidents, with compression ratio >90%
3. **AI accuracy ≥ baseline:** beat OpenRCA baseline of 11.34% or demonstrate clear improvement from preprocessing
4. **Dashboard functional:** all 6 pages render data, heatmap shows clusters, topology graph shows dependencies
5. **Reproducible:** `docker-compose up` and it works
