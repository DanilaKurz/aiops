"""Pipeline configuration -- YAML loader with Pydantic validation."""
import yaml
from pydantic import BaseModel
from typing import Optional


class ParserConfig(BaseModel):
    name: str
    enabled: bool = True
    params: dict = {}


class ConsolidatorConfig(BaseModel):
    name: str
    enabled: bool = False
    params: dict = {}


class ParsingConfig(BaseModel):
    mode: str = "parallel"
    voting: str = "majority"
    cascade_threshold: float = 0.7
    parsers: list[ParserConfig] = []
    consolidator: Optional[ConsolidatorConfig] = None


class ContextConfig(BaseModel):
    formats: list[str] = ["json", "narrative"]


class AgentConfig(BaseModel):
    model: str = "gpt-5.4"
    fallback_model: str = "gpt-4.1"
    max_iterations: int = 20


class BenchmarkConfig(BaseModel):
    datasets: list[str] = ["Bank"]
    dates: list[str] = ["2021_03_04"]
    hours: list[int] = [7]
    save_traces: bool = True


class PipelineConfig(BaseModel):
    parsing: ParsingConfig = ParsingConfig()
    context: ContextConfig = ContextConfig()
    agent: AgentConfig = AgentConfig()
    benchmark: BenchmarkConfig = BenchmarkConfig()


def load_config(path: str) -> PipelineConfig:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return PipelineConfig(**raw)
