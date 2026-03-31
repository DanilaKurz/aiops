import pytest

from correlation.base import Incident, Correlator


class TestIncident:
    def test_create(self):
        inc = Incident(
            severity="critical",
            components=["Redis02", "Tomcat01"],
            root_cause_candidate="Redis02",
            onset="07:01:00",
            confidence=0.9,
        )
        assert inc.severity == "critical"
        assert inc.incident_id  # auto-generated

    def test_auto_id_unique(self):
        inc1 = Incident(severity="info")
        inc2 = Incident(severity="info")
        assert inc1.incident_id != inc2.incident_id


class TestCorrelatorABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            Correlator()

    def test_concrete_works(self):
        class FakeCorrelator(Correlator):
            name = "fake"
            version = "0.1"

            def correlate(self, log_a, metric_a, trace_a, topology):
                return [
                    Incident(
                        severity="info",
                        components=["A"],
                        correlator_name=self.name,
                    )
                ]

            def reset(self):
                pass

        c = FakeCorrelator()
        results = c.correlate([], [], [], {})
        assert len(results) == 1


from correlation.temporal import TemporalCorrelator


class TestTemporalCorrelator:
    def test_is_correlator(self):
        c = TemporalCorrelator()
        assert isinstance(c, Correlator)
        assert c.name == "temporal"

    def test_group_close_events(self):
        metrics = [
            {"timestamp": "100", "component": "Redis02", "metric": "cpu"},
            {"timestamp": "120", "component": "Tomcat01", "metric": "mrt"},
        ]
        c = TemporalCorrelator(window_seconds=300)
        incidents = c.correlate([], metrics, [], {})
        assert len(incidents) == 1
        assert "Redis02" in incidents[0].components
        assert "Tomcat01" in incidents[0].components

    def test_split_distant_events(self):
        metrics = [
            {"timestamp": "100", "component": "A"},
            {"timestamp": "1000", "component": "B"},
        ]
        c = TemporalCorrelator(window_seconds=300)
        incidents = c.correlate([], metrics, [], {})
        assert len(incidents) == 2

    def test_empty_input(self):
        c = TemporalCorrelator()
        assert c.correlate([], [], [], {}) == []

    def test_reset(self):
        c = TemporalCorrelator()
        c.reset()


from correlation.topological import TopologicalCorrelator


class TestTopologicalCorrelator:
    def test_is_correlator(self):
        c = TopologicalCorrelator()
        assert isinstance(c, Correlator)
        assert c.name == "topological"

    def test_find_upstream_root_cause(self):
        topology = {
            "edges": [
                {"source": "frontend", "target": "backend"},
                {"source": "backend", "target": "database"},
            ]
        }
        metrics = [
            {"component": "frontend", "timestamp": "100"},
            {"component": "backend", "timestamp": "100"},
            {"component": "database", "timestamp": "100"},
        ]
        c = TopologicalCorrelator()
        incidents = c.correlate([], metrics, [], topology)
        assert len(incidents) == 1
        assert incidents[0].root_cause_candidate == "database"

    def test_leaf_only_anomaly(self):
        topology = {"edges": [{"source": "A", "target": "B"}]}
        metrics = [{"component": "B", "timestamp": "100"}]
        c = TopologicalCorrelator()
        incidents = c.correlate([], metrics, [], topology)
        assert incidents[0].root_cause_candidate == "B"

    def test_empty_topology(self):
        c = TopologicalCorrelator()
        incidents = c.correlate([], [{"component": "X"}], [], {})
        assert incidents == []

    def test_no_anomalies(self):
        c = TopologicalCorrelator()
        assert c.correlate([], [], [], {"edges": []}) == []

    def test_reset(self):
        c = TopologicalCorrelator()
        c.reset()


from correlation.noise_filter import NoiseFilter


class TestNoiseFilter:
    def test_is_correlator(self):
        f = NoiseFilter()
        assert isinstance(f, Correlator)
        assert f.name == "noise_filter"

    def test_filter_chronic(self):
        metrics = [{"component": "noisy", "timestamp": str(i)} for i in range(10)]
        metrics.append({"component": "real_issue", "timestamp": "100"})
        f = NoiseFilter(chronic_hours=6)
        incidents = f.correlate([], metrics, [], {})
        if incidents:
            assert "real_issue" in incidents[0].components
            assert incidents[0].details["chronic_count"] > 0

    def test_all_acute(self):
        metrics = [
            {"component": "A", "timestamp": "100"},
            {"component": "B", "timestamp": "200"},
        ]
        f = NoiseFilter(chronic_hours=6)
        incidents = f.correlate([], metrics, [], {})
        assert len(incidents) == 1
        assert len(incidents[0].components) == 2

    def test_empty(self):
        f = NoiseFilter()
        assert f.correlate([], [], [], {}) == []

    def test_noise_reduction_stats(self):
        metrics = [{"component": "noisy", "timestamp": str(i)} for i in range(20)]
        metrics.append({"component": "signal", "timestamp": "100"})
        f = NoiseFilter(chronic_hours=6)
        incidents = f.correlate([], metrics, [], {})
        if incidents:
            assert "noise_reduction" in incidents[0].details

    def test_reset(self):
        f = NoiseFilter()
        f.reset()
