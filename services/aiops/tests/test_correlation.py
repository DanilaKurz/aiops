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
