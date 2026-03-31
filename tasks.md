# AIOps -- Task Board

## Phase 1: MVP (COMPLETE)

**Spec:** `docs/superpowers/specs/2026-03-25-aiops-mvp-design.md`
**Status: COMPLETE**

---

## Phase 2: Ensemble Pipeline (COMPLETE)

**Spec:** `docs/superpowers/specs/2026-03-27-ensemble-pipeline-design.md`
**Status: COMPLETE -- 129/129 tests**

---

## Phase 3: Monitoring Tools (Tier 1)

**Spec:** `docs/superpowers/specs/2026-03-31-monitoring-tools-design.md`
**Plan:** `docs/superpowers/plans/2026-03-31-monitoring-tools.md`
**Status: IN PROGRESS**

### Batch 1 -- Foundation

| # | Task | Status | Files | Verify |
|---|------|--------|-------|--------|
| 1 | ABC interfaces (MetricDetector, TraceAnalyzer, Correlator) + dirs | TODO | metrics/base.py, traces/base.py, correlation/base.py | pytest |

### Batch 2 -- Metric Detectors (parallel)

| # | Task | Status | Files | Verify |
|---|------|--------|-------|--------|
| 2 | ruptures/PELT change point detection | TODO | metrics/ruptures_detector.py | Bank metrics |
| 3 | STL/MSTL seasonal decomposition | TODO | metrics/stl_detector.py | Bank metrics |
| 4 | OneShotSTL streaming decomposition | TODO | metrics/oneshot_stl_detector.py | Bank metrics |
| 5 | PyOD ensemble (IForest+LOF+OCSVM) | TODO | metrics/pyod_detector.py | Bank metrics |
| 6 | BARO root cause ranking | TODO | metrics/baro_detector.py | Bank metrics |
| 7 | MetricEnsemble (combine detectors) | TODO | metrics/ensemble.py | pytest |

### Batch 3 -- Trace Analyzers (parallel)

| # | Task | Status | Files | Verify |
|---|------|--------|-------|--------|
| 8 | Span latency/error analyzer | TODO | traces/span_analyzer.py | Bank traces |
| 9 | Service dependency graph builder | TODO | traces/dependency_builder.py | Bank traces |
| 10 | Critical path extraction | TODO | traces/critical_path.py | Bank traces |

### Batch 4 -- Correlators (parallel)

| # | Task | Status | Files | Verify |
|---|------|--------|-------|--------|
| 11 | Temporal co-occurrence | TODO | correlation/temporal.py | pytest |
| 12 | Topological upstream walk | TODO | correlation/topological.py | pytest |
| 13 | Noise filter (chronic/acute + entropy) | TODO | correlation/noise_filter.py | pytest |

### Batch 5 -- Pipeline Integration

| # | Task | Status | Files | Verify |
|---|------|--------|-------|--------|
| 14 | Pipeline config (+ metrics/traces/correlation YAML) | TODO | pipeline/config.py, pipeline_config.yaml | pytest |
| 15 | Pipeline runner + trace (new stages) | TODO | pipeline/runner.py, pipeline/trace.py | Bank H7 e2e |

### Batch 6 -- Output

| # | Task | Status | Files | Verify |
|---|------|--------|-------|--------|
| 16 | Full comparison run + Excel report | TODO | run_monitoring_comparison.py | Excel |
| 17 | Update tasks.md + README | TODO | tasks.md, README.md | review |
