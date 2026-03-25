# AIOps MVP -- Task Board

**Plan:** `docs/superpowers/plans/2026-03-25-aiops-mvp.md`
**Spec:** `docs/superpowers/specs/2026-03-25-aiops-mvp-design.md`

**Status: ALL TASKS COMPLETE -- 31/31 tests passing**

---

## Batch 1 -- Foundation

| # | Task | Status |
|---|------|--------|
| 1 | Project scaffolding (config, models, db, requirements) | DONE |
| 2 | Docker Compose + Dockerfile | DONE |
| 12 | System prompt | DONE |

## Batch 2 -- Core Modules

| # | Task | Status |
|---|------|--------|
| 3 | OpenRCA data adapter | DONE |
| 4 | Drain parser | DONE |
| 5 | RAG module (ChromaDB) | DONE |

## Batch 3 -- Processing

| # | Task | Status |
|---|------|--------|
| 6 | Anomaly detection | DONE |
| 7 | Agent tools (6 tools) | DONE |

## Batch 4 -- Integration Modules

| # | Task | Status |
|---|------|--------|
| 8 | Keep alerter | DONE |
| 9 | AI Investigator | DONE |

## Batch 5 -- API Layer

| # | Task | Status |
|---|------|--------|
| 10 | API routes -- pipeline (ingest, clusters, anomalies, stats) | DONE |
| 11 | API routes -- agent (investigate, reports, benchmark) | DONE |

## Batch 6 -- Assembly

| # | Task | Status |
|---|------|--------|
| 13 | FastAPI main.py (lifespan, routers) | DONE |
| 14 | Keep setup script | DONE |
| 15 | Grafana provisioning (5 dashboards) | DONE |

## Batch 7 -- Verification

| # | Task | Status |
|---|------|--------|
| 16 | Integration test (end-to-end) | DONE |
