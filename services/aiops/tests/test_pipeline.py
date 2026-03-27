import pytest
import yaml
from pipeline.config import PipelineConfig, load_config, ParserConfig


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
