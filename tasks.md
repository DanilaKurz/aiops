# AIOps MVP -- Task Board

> Координация параллельной работы агентов.
> Каждый агент берёт задачу, отмечает `IN PROGRESS`, по завершении -- `DONE`.
> Проверяйте зависимости перед началом работы.

**Plan:** `docs/superpowers/plans/2026-03-25-aiops-mvp.md`
**Spec:** `docs/superpowers/specs/2026-03-25-aiops-mvp-design.md`

---

## Batch 1 -- Foundation (no deps, parallel)

| # | Task | Status | Agent | Depends On |
|---|------|--------|-------|------------|
| 1 | Project scaffolding (config, models, db, requirements) | TODO | - | - |
| 2 | Docker Compose + Dockerfile | TODO | - | - |
| 12 | System prompt | TODO | - | - |

## Batch 2 -- Core Modules (depends on Task 1, parallel)

| # | Task | Status | Agent | Depends On |
|---|------|--------|-------|------------|
| 3 | OpenRCA data adapter | TODO | - | Task 1 |
| 4 | Drain parser | TODO | - | Task 1 |
| 5 | RAG module (ChromaDB) | TODO | - | Task 1 |

## Batch 3 -- Processing (mixed deps, parallel)

| # | Task | Status | Agent | Depends On |
|---|------|--------|-------|------------|
| 6 | Anomaly detection | TODO | - | Task 4 |
| 7 | Agent tools (6 tools) | TODO | - | Task 3 |

## Batch 4 -- Integration Modules (mixed deps, parallel)

| # | Task | Status | Agent | Depends On |
|---|------|--------|-------|------------|
| 8 | Keep alerter | TODO | - | Task 6 |
| 9 | AI Investigator | TODO | - | Task 5, 7 |

## Batch 5 -- API Layer (parallel)

| # | Task | Status | Agent | Depends On |
|---|------|--------|-------|------------|
| 10 | API routes -- pipeline (ingest, clusters, anomalies, stats) | TODO | - | Task 4, 6, 8 |
| 11 | API routes -- agent (investigate, reports, benchmark) | TODO | - | Task 9 |

## Batch 6 -- Assembly (parallel)

| # | Task | Status | Agent | Depends On |
|---|------|--------|-------|------------|
| 13 | FastAPI main.py (lifespan, routers) | TODO | - | Task 10, 11 |
| 14 | Keep setup script (full: API key + topology + rules) | TODO | - | Task 2, 3 |
| 15 | Grafana provisioning (5 dashboards) | TODO | - | Task 10, 11 |

## Batch 7 -- Verification

| # | Task | Status | Agent | Depends On |
|---|------|--------|-------|------------|
| 16 | Integration test (end-to-end) | TODO | - | All |

---

## Status Legend

- `TODO` -- Not started
- `IN PROGRESS` -- Agent working on it
- `DONE` -- Completed and committed
- `BLOCKED` -- Waiting on dependency
