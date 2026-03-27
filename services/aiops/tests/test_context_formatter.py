"""Tests for context formatter -- JSON and Narrative self-documenting formats."""
import json
import pytest
from pipeline.context_formatter import ContextFormatter


SAMPLE_GOLDEN = [
    {"service": "ServiceTest3", "role": "end-to-end checkout health check",
     "sr_min": 88.7, "mrt_max": 13950, "mrt_normal": 350}
]
SAMPLE_COMPONENTS = [
    {
        "name": "Redis02",
        "role": "in-memory cache used by all Tomcat servers",
        "tier": "Tier 4 (backend)",
        "severity": "critical",
        "is_new": True,
        "onset": "07:01:00",
        "metrics": [
            {"name": "CPU utilization", "value": 91.9, "unit": "%",
             "normal": "1-3%", "multiplier": 53.8,
             "trend": "sudden spike from stable baseline",
             "history_hours": [1.0, 3.4, 0.8]}
        ],
        "log_templates": [
            {"template": "GC (Allocation Failure) <*>ms", "count": 247,
             "meaning": "Java GC struggling with memory pressure",
             "agreement": 0.85}
        ],
        "why_suspicious": "NEW spike + precedes user impact + upstream of degraded service",
    }
]
SAMPLE_TOPOLOGY = {
    "nodes": ["IG01", "Tomcat01", "Redis02"],
    "edges": [{"source": "IG01", "target": "Tomcat01"}, {"source": "Tomcat01", "target": "Redis02"}],
}


class TestContextFormatterJSON:
    def test_json_has_required_sections(self):
        fmt = ContextFormatter()
        ctx = fmt.format_json("Bank", "2021_03_04", 7,
                              SAMPLE_GOLDEN, SAMPLE_COMPONENTS, SAMPLE_TOPOLOGY)
        data = json.loads(ctx)
        assert "incident" in data
        assert "user_impact" in data
        assert "suspicious_components" in data
        assert "topology" in data

    def test_json_incident_metadata(self):
        fmt = ContextFormatter()
        ctx = fmt.format_json("Bank", "2021_03_04", 7,
                              SAMPLE_GOLDEN, SAMPLE_COMPONENTS, SAMPLE_TOPOLOGY)
        data = json.loads(ctx)
        assert data["incident"]["system"] == "Bank"
        assert data["incident"]["severity"] == "critical"
        assert "system_description" in data["incident"]

    def test_json_user_impact_self_documenting(self):
        fmt = ContextFormatter()
        ctx = fmt.format_json("Bank", "2021_03_04", 7,
                              SAMPLE_GOLDEN, SAMPLE_COMPONENTS, SAMPLE_TOPOLOGY)
        data = json.loads(ctx)
        impact = data["user_impact"][0]
        assert "meaning" in impact["success_rate"]
        assert "normal_range" in impact["success_rate"]
        assert "verdict" in impact["success_rate"]

    def test_json_component_has_role_and_explanation(self):
        fmt = ContextFormatter()
        ctx = fmt.format_json("Bank", "2021_03_04", 7,
                              SAMPLE_GOLDEN, SAMPLE_COMPONENTS, SAMPLE_TOPOLOGY)
        data = json.loads(ctx)
        comp = data["suspicious_components"][0]
        assert comp["role"] == "in-memory cache used by all Tomcat servers"
        assert comp["is_new_explanation"]
        assert comp["why_suspicious"]

    def test_json_metric_has_normal_range(self):
        fmt = ContextFormatter()
        ctx = fmt.format_json("Bank", "2021_03_04", 7,
                              SAMPLE_GOLDEN, SAMPLE_COMPONENTS, SAMPLE_TOPOLOGY)
        data = json.loads(ctx)
        metric = data["suspicious_components"][0]["metrics"][0]
        assert metric["normal_range"] == "1-3%"
        assert metric["multiplier"] == 53.8


class TestContextFormatterNarrative:
    def test_narrative_has_sections(self):
        fmt = ContextFormatter()
        ctx = fmt.format_narrative("Bank", "2021_03_04", 7,
                                   SAMPLE_GOLDEN, SAMPLE_COMPONENTS, SAMPLE_TOPOLOGY)
        assert "INCIDENT CONTEXT" in ctx
        assert "WHAT USERS SEE" in ctx
        assert "SUSPICIOUS COMPONENTS" in ctx
        assert "SERVICE DEPENDENCIES" in ctx

    def test_narrative_contains_component(self):
        fmt = ContextFormatter()
        ctx = fmt.format_narrative("Bank", "2021_03_04", 7,
                                   SAMPLE_GOLDEN, SAMPLE_COMPONENTS, SAMPLE_TOPOLOGY)
        assert "Redis02" in ctx
        assert "in-memory cache" in ctx
        assert "91.9" in ctx

    def test_narrative_explains_metrics(self):
        fmt = ContextFormatter()
        ctx = fmt.format_narrative("Bank", "2021_03_04", 7,
                                   SAMPLE_GOLDEN, SAMPLE_COMPONENTS, SAMPLE_TOPOLOGY)
        assert "Normal for this host: 1-3%" in ctx
        assert "53.8x above normal baseline" in ctx

    def test_narrative_has_topology(self):
        fmt = ContextFormatter()
        ctx = fmt.format_narrative("Bank", "2021_03_04", 7,
                                   SAMPLE_GOLDEN, SAMPLE_COMPONENTS, SAMPLE_TOPOLOGY)
        assert "IG01 -> Tomcat01" in ctx
        assert "Tomcat01 -> Redis02" in ctx

    def test_narrative_ensemble_summary(self):
        fmt = ContextFormatter()
        ensemble = {
            "parsers_used": ["drain3", "loglshd"],
            "overall_agreement": 0.82,
            "anomalous_templates": [
                {"template": "GC <*>ms", "count": 247, "service": "Redis02", "agreement": 0.85}
            ],
        }
        ctx = fmt.format_narrative("Bank", "2021_03_04", 7,
                                   SAMPLE_GOLDEN, SAMPLE_COMPONENTS, SAMPLE_TOPOLOGY,
                                   ensemble_summary=ensemble)
        assert "ENSEMBLE PARSING SUMMARY" in ctx
        assert "drain3" in ctx
        assert "82%" in ctx


class TestContextFormatterEdgeCases:
    def test_empty_components(self):
        fmt = ContextFormatter()
        ctx = fmt.format_json("Bank", "2021_03_04", 7, [], [], {"nodes": [], "edges": []})
        data = json.loads(ctx)
        assert data["suspicious_components"] == []

    def test_unknown_dataset(self):
        fmt = ContextFormatter()
        ctx = fmt.format_narrative("Unknown", "2021_01_01", 0, [], [], {"nodes": [], "edges": []})
        assert "distributed system" in ctx
