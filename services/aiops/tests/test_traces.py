import pytest
import pandas as pd
from dataclasses import asdict

from traces.base import TraceResult, TraceAnalyzer


class TestTraceResult:
    def test_create(self):
        r = TraceResult(
            trace_id="t1",
            is_anomalous=True,
            bottleneck_service="Redis02",
            latency_ms=58000,
            normal_latency_ms=200,
        )
        assert r.is_anomalous is True
        assert r.bottleneck_service == "Redis02"

    def test_defaults(self):
        r = TraceResult(trace_id="t1", is_anomalous=False, bottleneck_service="")
        assert r.critical_path == []
        assert r.anomalous_spans == []


class TestTraceAnalyzerABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            TraceAnalyzer()

    def test_concrete_works(self):
        class FakeAnalyzer(TraceAnalyzer):
            name = "fake"
            version = "0.1"

            def analyze(self, spans_df):
                return [
                    TraceResult(
                        trace_id="t1",
                        is_anomalous=False,
                        bottleneck_service="svc1",
                        analyzer_name=self.name,
                    )
                ]

            def reset(self):
                pass

        a = FakeAnalyzer()
        results = a.analyze(pd.DataFrame())
        assert len(results) == 1


from traces.span_analyzer import SpanAnalyzer


class TestSpanAnalyzer:
    def test_is_trace_analyzer(self):
        a = SpanAnalyzer()
        assert isinstance(a, TraceAnalyzer)
        assert a.name == "span_analyzer"

    def test_detect_slow_span(self):
        df = pd.DataFrame({
            "timestamp": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "cmdb_id": ["svc1"] * 10,
            "span_id": [f"s{i}" for i in range(10)],
            "parent_id": [""] * 10,
            "trace_id": ["t1"] * 5 + ["t2"] * 5,
            "duration": [10, 12, 11, 13, 500, 10, 11, 12, 10, 11],
        })
        a = SpanAnalyzer(latency_threshold_multiplier=3.0)
        results = a.analyze(df)
        anomalous = [r for r in results if r.is_anomalous]
        assert len(anomalous) >= 1  # t1 has span with 500ms

    def test_no_anomaly_uniform(self):
        df = pd.DataFrame({
            "timestamp": range(10),
            "cmdb_id": ["svc1"] * 10,
            "span_id": [f"s{i}" for i in range(10)],
            "parent_id": [""] * 10,
            "trace_id": ["t1"] * 10,
            "duration": [10, 11, 10, 12, 10, 11, 10, 11, 10, 12],
        })
        a = SpanAnalyzer(latency_threshold_multiplier=3.0)
        results = a.analyze(df)
        assert all(not r.is_anomalous for r in results)

    def test_bottleneck_identified(self):
        df = pd.DataFrame({
            "timestamp": [1, 2, 3],
            "cmdb_id": ["fast", "fast", "slow"],
            "span_id": ["s1", "s2", "s3"],
            "parent_id": ["", "s1", "s1"],
            "trace_id": ["t1", "t1", "t1"],
            "duration": [5, 10, 500],
        })
        a = SpanAnalyzer()
        results = a.analyze(df)
        assert results[0].bottleneck_service == "slow"

    def test_empty_df(self):
        a = SpanAnalyzer()
        results = a.analyze(pd.DataFrame())
        assert results == []

    def test_reset(self):
        a = SpanAnalyzer()
        a.reset()


from traces.critical_path import CriticalPathAnalyzer


class TestCriticalPathAnalyzer:
    def test_is_trace_analyzer(self):
        a = CriticalPathAnalyzer()
        assert isinstance(a, TraceAnalyzer)
        assert a.name == "critical_path"

    def test_find_critical_path(self):
        # Tree: A(10) -> B(50), A(10) -> C(5)
        # Critical path: A -> B (duration 60)
        df = pd.DataFrame({
            "timestamp": [1, 2, 3],
            "cmdb_id": ["A", "B", "C"],
            "span_id": ["s1", "s2", "s3"],
            "parent_id": ["", "s1", "s1"],
            "trace_id": ["t1", "t1", "t1"],
            "duration": [10, 50, 5],
        })
        a = CriticalPathAnalyzer()
        results = a.analyze(df)
        assert len(results) == 1
        assert results[0].critical_path == ["A", "B"]
        assert results[0].latency_ms == 60

    def test_bottleneck_is_slowest(self):
        df = pd.DataFrame({
            "timestamp": [1, 2, 3],
            "cmdb_id": ["fast", "fast", "slow"],
            "span_id": ["s1", "s2", "s3"],
            "parent_id": ["", "s1", "s2"],
            "trace_id": ["t1", "t1", "t1"],
            "duration": [1, 2, 100],
        })
        a = CriticalPathAnalyzer()
        results = a.analyze(df)
        assert results[0].bottleneck_service == "slow"

    def test_multiple_traces(self):
        df = pd.DataFrame({
            "timestamp": [1, 2, 3, 4],
            "cmdb_id": ["A", "B", "C", "D"],
            "span_id": ["s1", "s2", "s3", "s4"],
            "parent_id": ["", "s1", "", "s3"],
            "trace_id": ["t1", "t1", "t2", "t2"],
            "duration": [10, 20, 5, 15],
        })
        a = CriticalPathAnalyzer()
        results = a.analyze(df)
        assert len(results) == 2

    def test_empty(self):
        a = CriticalPathAnalyzer()
        assert a.analyze(pd.DataFrame()) == []

    def test_reset(self):
        a = CriticalPathAnalyzer()
        a.reset()


from traces.dependency_builder import DependencyBuilder


class TestDependencyBuilder:
    def test_is_trace_analyzer(self):
        b = DependencyBuilder()
        assert isinstance(b, TraceAnalyzer)
        assert b.name == "dependency_builder"

    def test_build_graph(self):
        df = pd.DataFrame({
            "timestamp": [1, 2, 3, 4],
            "cmdb_id": ["frontend", "backend", "backend", "database"],
            "span_id": ["s1", "s2", "s3", "s4"],
            "parent_id": ["", "s1", "s1", "s2"],
            "trace_id": ["t1", "t1", "t1", "t1"],
            "duration": [100, 50, 30, 20],
        })
        b = DependencyBuilder()
        results = b.analyze(df)
        assert len(results) == 1
        graph = results[0].details
        assert graph["node_count"] == 3  # frontend, backend, database
        assert graph["edge_count"] == 2  # frontend->backend, backend->database

    def test_no_self_edges(self):
        df = pd.DataFrame({
            "timestamp": [1, 2],
            "cmdb_id": ["svc1", "svc1"],
            "span_id": ["s1", "s2"],
            "parent_id": ["", "s1"],
            "trace_id": ["t1", "t1"],
            "duration": [10, 5],
        })
        b = DependencyBuilder()
        results = b.analyze(df)
        assert results[0].details["edge_count"] == 0

    def test_empty_df(self):
        b = DependencyBuilder()
        results = b.analyze(pd.DataFrame())
        assert results == []

    def test_reset(self):
        b = DependencyBuilder()
        b.analyze(pd.DataFrame({
            "timestamp": [1], "cmdb_id": ["a"], "span_id": ["s1"],
            "parent_id": [""], "trace_id": ["t1"], "duration": [10]
        }))
        b.reset()
        assert b.get_graph() == {"nodes": [], "edges": []}
