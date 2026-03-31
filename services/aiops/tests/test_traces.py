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
