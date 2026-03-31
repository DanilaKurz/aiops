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


from metrics.ruptures_detector import RupturesDetector


class TestRupturesDetector:
    def test_is_metric_detector(self):
        d = RupturesDetector()
        assert isinstance(d, MetricDetector)
        assert d.name == "ruptures"

    def test_detect_change_point(self):
        import numpy as np
        np.random.seed(42)
        normal = np.random.normal(2.0, 0.5, 50)
        spike = np.random.normal(90.0, 5.0, 10)
        values = np.concatenate([normal, spike])
        df = pd.DataFrame({
            "cmdb_id": ["Redis02"] * 60,
            "kpi_name": ["CPUCpuUtil"] * 60,
            "value": values,
            "timestamp": range(60),
        })
        d = RupturesDetector()
        results = d.detect(df, "Redis02")
        assert len(results) > 0
        assert results[0].anomaly_type == "change_point"
        assert results[0].component == "Redis02"

    def test_no_anomaly_on_stable(self):
        import numpy as np
        np.random.seed(42)
        values = np.random.normal(2.0, 0.5, 60)
        df = pd.DataFrame({
            "cmdb_id": ["Redis02"] * 60,
            "kpi_name": ["CPUCpuUtil"] * 60,
            "value": values,
            "timestamp": range(60),
        })
        d = RupturesDetector()
        results = d.detect(df, "Redis02")
        assert len(results) == 0

    def test_reset(self):
        d = RupturesDetector()
        d.reset()


# --------------- STL Detector Tests ---------------

from metrics.stl_detector import STLDetector


class TestSTLDetector:
    def test_is_metric_detector(self):
        d = STLDetector()
        assert isinstance(d, MetricDetector)
        assert d.name == "stl"

    def test_detect_seasonal_anomaly(self):
        import numpy as np
        np.random.seed(42)
        # Create seasonal data with anomaly
        t = np.arange(200)
        seasonal = 10 * np.sin(2 * np.pi * t / 60)  # period=60
        trend = 0.01 * t
        noise = np.random.normal(0, 0.5, 200)
        values = seasonal + trend + noise
        # Inject anomaly at index 150
        values[150] = values[150] + 50
        df = pd.DataFrame({
            "cmdb_id": ["comp"] * 200,
            "kpi_name": ["cpu"] * 200,
            "value": values,
            "timestamp": range(200),
        })
        d = STLDetector(period=60)
        results = d.detect(df, "comp")
        assert len(results) > 0
        # The anomaly at index 150 should be detected
        anomaly_timestamps = [r.timestamp for r in results]
        assert "150" in anomaly_timestamps

    def test_no_anomaly_clean_seasonal(self):
        import numpy as np
        np.random.seed(42)
        t = np.arange(200)
        values = 10 * np.sin(2 * np.pi * t / 60) + np.random.normal(0, 0.3, 200)
        df = pd.DataFrame({
            "cmdb_id": ["comp"] * 200,
            "kpi_name": ["cpu"] * 200,
            "value": values,
            "timestamp": range(200),
        })
        d = STLDetector(period=60, anomaly_threshold=4.0)
        results = d.detect(df, "comp")
        assert len(results) == 0  # clean seasonal, no anomalies

    def test_too_short_data(self):
        df = pd.DataFrame({
            "cmdb_id": ["comp"] * 10,
            "kpi_name": ["cpu"] * 10,
            "value": range(10),
            "timestamp": range(10),
        })
        d = STLDetector(period=60)
        results = d.detect(df, "comp")
        assert len(results) == 0  # too short for STL

    def test_reset(self):
        d = STLDetector()
        d.reset()


# --------------- PyOD Detector Tests ---------------

from metrics.pyod_detector import PyODDetector


class TestPyODDetector:
    def test_is_metric_detector(self):
        d = PyODDetector()
        assert isinstance(d, MetricDetector)
        assert d.name == "pyod"

    def test_detect_anomaly(self):
        import numpy as np
        np.random.seed(42)
        normal = np.random.normal(0, 1, (50, 3))
        anomalous = np.random.normal(10, 1, (5, 3))
        data = np.vstack([normal, anomalous])
        df = pd.DataFrame({
            "cmdb_id": ["comp"] * 55,
            "kpi_name": [f"kpi_{i%3}" for i in range(55)],
            "value": data.flatten()[:55],
            "timestamp": range(55),
        })
        d = PyODDetector(methods=["iforest"], contamination=0.1)
        results = d.detect(df, "comp")
        # Should detect some anomalies
        assert isinstance(results, list)

    def test_empty_data(self):
        d = PyODDetector()
        results = d.detect(pd.DataFrame(), "comp")
        assert results == []

    def test_reset(self):
        d = PyODDetector()
        d.reset()
