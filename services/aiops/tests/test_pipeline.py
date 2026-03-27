import os
import pytest
import yaml
from pipeline.config import PipelineConfig, load_config, ParserConfig, ParsingConfig
from pipeline.trace import PipelineTrace, save_trace, load_trace
from pipeline.runner import PipelineRunner, register_parser, _init_parsers, PARSER_REGISTRY
from parsers.drain_parser import Drain3Parser


class TestPipelineConfig:
    def test_load_from_yaml(self, tmp_path):
        cfg = {
            "parsing": {
                "mode": "parallel",
                "voting": "majority",
                "parsers": [
                    {"name": "drain3", "enabled": True, "params": {"sim_th": 0.4}},
                    {"name": "loglshd", "enabled": True},
                ],
                "consolidator": {"name": "lemur", "enabled": False},
            },
            "context": {"formats": ["json", "narrative"]},
            "agent": {"model": "gpt-5.4", "max_iterations": 20},
            "benchmark": {"datasets": ["Bank"], "dates": ["2021_03_04"], "save_traces": True},
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(cfg))
        config = load_config(str(path))
        assert config.parsing.mode == "parallel"
        assert len(config.parsing.parsers) == 2
        assert config.parsing.parsers[0].name == "drain3"
        assert config.context.formats == ["json", "narrative"]
        assert config.agent.model == "gpt-5.4"

    def test_default_config_valid(self):
        config = load_config("pipeline_config.yaml")
        assert config.parsing.mode in ("parallel", "cascade", "single")
        assert len(config.parsing.parsers) > 0

    def test_parser_config_defaults(self):
        pc = ParserConfig(name="test")
        assert pc.enabled is True
        assert pc.params == {}

    def test_empty_config_uses_defaults(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text(yaml.dump({}))
        config = load_config(str(path))
        assert config.parsing.mode == "parallel"
        assert config.agent.model == "gpt-5.4"


class TestPipelineTrace:
    def test_create_trace(self):
        t = PipelineTrace(
            dataset="Bank", date="2021_03_04", hour=7,
            config_snapshot={"parsing": {"mode": "parallel"}},
        )
        assert t.trace_id  # auto-generated
        assert t.dataset == "Bank"
        assert t.raw_log_count == 0
        assert t.parse_results == {}

    def test_trace_has_all_sections(self):
        t = PipelineTrace(dataset="Bank", date="2021_03_04", hour=7, config_snapshot={})
        assert hasattr(t, "parse_results")
        assert hasattr(t, "anomalies")
        assert hasattr(t, "agent_contexts")
        assert hasattr(t, "agent_results")
        assert hasattr(t, "ground_truth")
        assert hasattr(t, "timing")

    def test_save_and_load(self, tmp_path):
        t = PipelineTrace(
            dataset="Bank", date="2021_03_04", hour=7,
            config_snapshot={"test": True},
        )
        t.raw_log_count = 100
        t.template_summary = {"drain3": 15}
        trace_dir = save_trace(t, str(tmp_path))
        loaded = load_trace(trace_dir)
        assert loaded.dataset == "Bank"
        assert loaded.config_snapshot == {"test": True}
        assert loaded.raw_log_count == 100
        assert loaded.template_summary == {"drain3": 15}

    def test_save_creates_directory(self, tmp_path):
        t = PipelineTrace(dataset="X", date="d", hour=0, config_snapshot={})
        trace_dir = save_trace(t, str(tmp_path))
        assert os.path.isdir(trace_dir)
        assert os.path.isfile(os.path.join(trace_dir, "trace.json"))


class TestPipelineRunner:
    def setup_method(self):
        """Register drain3 parser for each test."""
        PARSER_REGISTRY.clear()
        register_parser("drain3", Drain3Parser)

    def test_create_runner(self):
        runner = PipelineRunner(config_path="pipeline_config.yaml")
        assert runner.config.parsing.mode == "parallel"

    def test_init_parsers_from_config(self):
        config = PipelineConfig(
            parsing=ParsingConfig(
                parsers=[
                    ParserConfig(name="drain3", enabled=True),
                    ParserConfig(name="nonexistent", enabled=True),
                    ParserConfig(name="drain3", enabled=False),
                ]
            )
        )
        parsers = _init_parsers(config)
        assert len(parsers) == 1
        assert parsers[0].name == "drain3"

    def test_run_returns_trace(self):
        """Run with drain3 only on Bank H7 if data exists."""
        runner = PipelineRunner(config_path="pipeline_config.yaml")
        trace = runner.run(dataset="Bank", date="2021_03_04", hour=7)
        assert trace.dataset == "Bank"
        assert trace.trace_id
        # May be 0 if Bank data not available in test env
        assert isinstance(trace.raw_log_count, int)
        assert "parsing" in trace.timing or trace.raw_log_count == 0
