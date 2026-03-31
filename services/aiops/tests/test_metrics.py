import pytest
import pandas as pd
from dataclasses import asdict

from metrics.base import DetectionResult, MetricDetector


class TestDetectionResult:
    def test_create(self):
        r = DetectionResult(
            component="Redis02",
            metric="CPUCpuUtil",
            anomaly_type="change_point",
            timestamp="2021-03-04T07:01:00",
            value=91.9,
            baseline=1.7,
            score=0.95,
            detector_name="ruptures",
            details={},
        )
        assert r.component == "Redis02"
        assert r.score == 0.95

    def test_serializable(self):
        r = DetectionResult(
            component="X",
            metric="Y",
            anomaly_type="spike",
            timestamp="T",
            value=1.0,
            baseline=0.0,
            score=0.5,
            detector_name="test",
            details={"k": "v"},
        )
        d = asdict(r)
        assert d["details"]["k"] == "v"


class TestMetricDetectorABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            MetricDetector()

    def test_concrete_works(self):
        class FakeDetector(MetricDetector):
            name = "fake"
            version = "0.1"

            def detect(self, df, component):
                return [
                    DetectionResult(
                        component=component,
                        metric="test",
                        anomaly_type="test",
                        timestamp="T",
                        value=1.0,
                        baseline=0.0,
                        score=0.5,
                        detector_name=self.name,
                        details={},
                    )
                ]

            def reset(self):
                pass

        d = FakeDetector()
        results = d.detect(pd.DataFrame(), "X")
        assert len(results) == 1

    def test_detect_all_loops(self):
        class SimpleDetector(MetricDetector):
            name = "simple"
            version = "0.1"

            def detect(self, df, component):
                return [
                    DetectionResult(
                        component=component,
                        metric="m",
                        anomaly_type="t",
                        timestamp="T",
                        value=1.0,
                        baseline=0.0,
                        score=0.5,
                        detector_name=self.name,
                        details={},
                    )
                ]

            def reset(self):
                pass

        d = SimpleDetector()
        df = pd.DataFrame(
            {"cmdb_id": ["A", "A", "B"], "kpi_name": ["cpu"] * 3, "value": [1, 2, 3]}
        )
        results = d.detect_all(df)
        assert len(results) == 2  # one per component
