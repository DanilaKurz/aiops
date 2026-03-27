"""Tests for benchmark runner and scoring."""
import pytest
from benchmark.scoring import score_incident, score_parser, compare_configs


class TestScoreIncident:
    def test_correct_component(self):
        score = score_incident(
            predicted={"component": "Redis02", "reason": "high CPU"},
            ground_truth={"component": "Redis02", "reason": "high CPU usage"},
        )
        assert score["component_match"] is True
        assert score["reason_similarity"] > 0.5

    def test_wrong_component(self):
        score = score_incident(
            predicted={"component": "Tomcat01"},
            ground_truth={"component": "Redis02"},
        )
        assert score["component_match"] is False

    def test_case_insensitive(self):
        score = score_incident(
            predicted={"component": "redis02"},
            ground_truth={"component": "Redis02"},
        )
        assert score["component_match"] is True

    def test_empty_prediction(self):
        score = score_incident(predicted={}, ground_truth={"component": "Redis02"})
        assert score["component_match"] is False
        assert score["reason_similarity"] == 0.0


class TestScoreParser:
    def test_basic_scoring(self):
        result = score_parser(template_count=47, parsing_time=12.3, total_lines=45000)
        assert result["template_count"] == 47
        assert result["parsing_time"] == 12.3
        assert result["lines_per_second"] > 0

    def test_zero_time(self):
        result = score_parser(template_count=10, parsing_time=0)
        assert result["lines_per_second"] == 0


class TestCompareConfigs:
    def test_compare_two_configs(self):
        traces = [
            {"config_name": "drain_only", "accuracy": 0.7, "total_llm_calls": 0},
            {"config_name": "ensemble", "accuracy": 0.85, "total_llm_calls": 100},
        ]
        report = compare_configs(traces)
        assert report["configs_compared"] == 2
        assert report["best_config"] == "ensemble"
        assert report["best_accuracy"] == 0.85

    def test_empty_traces(self):
        report = compare_configs([])
        assert "error" in report
