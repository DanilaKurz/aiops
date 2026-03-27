"""Pipeline runner -- orchestrates the full ensemble pipeline."""
import time
import os
from typing import Optional

from pipeline.config import PipelineConfig, load_config
from pipeline.trace import PipelineTrace, save_trace
from pipeline.context_formatter import ContextFormatter
from parsers.base import LogParser
from parsers.ensemble import EnsembleParser


# Parser registry: name -> class
PARSER_REGISTRY: dict[str, type] = {}


def register_parser(name: str, cls: type):
    """Register a parser class by name for config-based instantiation."""
    PARSER_REGISTRY[name] = cls


def _init_parsers(config: PipelineConfig) -> list[LogParser]:
    """Initialize enabled parsers from config."""
    parsers = []
    for pc in config.parsing.parsers:
        if not pc.enabled:
            continue
        cls = PARSER_REGISTRY.get(pc.name)
        if cls is None:
            print(f"Warning: parser '{pc.name}' not registered, skipping")
            continue
        try:
            parser = cls(**pc.params) if pc.params else cls()
            parsers.append(parser)
        except Exception as e:
            print(f"Warning: failed to init parser '{pc.name}': {e}")
    return parsers


class PipelineRunner:
    """Runs the full ensemble pipeline for a given dataset/date/hour."""

    def __init__(self, config_path: str = "pipeline_config.yaml"):
        self.config = load_config(config_path)
        self.formatter = ContextFormatter()

    def run(self, dataset: str, date: str, hour: int,
            traces_dir: str = "traces") -> PipelineTrace:
        trace = PipelineTrace(
            dataset=dataset, date=date, hour=hour,
            config_snapshot=self.config.model_dump(),
        )

        # Stage 1: Init parsers
        t0 = time.time()
        parsers = _init_parsers(self.config)
        if not parsers:
            print("No parsers available, returning empty trace")
            return trace

        ensemble = EnsembleParser(
            parsers=parsers,
            mode=self.config.parsing.mode,
            voting=self.config.parsing.voting,
            cascade_threshold=self.config.parsing.cascade_threshold,
        )
        trace.timing["init"] = time.time() - t0

        # Stage 2: Load data
        t0 = time.time()
        log_lines = self._load_logs(dataset, date, hour)
        trace.raw_log_count = len(log_lines)
        trace.timing["load"] = time.time() - t0

        # Stage 3: Parse
        t0 = time.time()
        ensemble_results = ensemble.parse_batch(log_lines)
        trace.ensemble_results = [
            {
                "consensus_template": r.consensus_template,
                "agreement_ratio": r.agreement_ratio,
                "per_parser": {
                    name: {"template": pr.template, "confidence": pr.confidence}
                    for name, pr in r.per_parser.items()
                },
            }
            for r in ensemble_results
        ]
        # Template summary per parser
        for parser in parsers:
            templates = set()
            for r in ensemble_results:
                if parser.name in r.per_parser:
                    templates.add(r.per_parser[parser.name].template)
            trace.template_summary[parser.name] = len(templates)
        trace.timing["parsing"] = time.time() - t0

        # Stage 4: Generate context
        t0 = time.time()
        for fmt in self.config.context.formats:
            if fmt == "json":
                ctx = self.formatter.format_json(
                    dataset=dataset, date=date, hour=hour,
                    golden_signals=[], components=[], topology={"nodes": [], "edges": []},
                )
            elif fmt == "narrative":
                ctx = self.formatter.format_narrative(
                    dataset=dataset, date=date, hour=hour,
                    golden_signals=[], components=[], topology={"nodes": [], "edges": []},
                )
            else:
                continue
            trace.agent_contexts[fmt] = ctx
            trace.context_token_counts[fmt] = len(ctx.split())
        trace.timing["context"] = time.time() - t0

        # Save trace
        if self.config.benchmark.save_traces:
            save_trace(trace, traces_dir)

        return trace

    def _load_logs(self, dataset: str, date: str, hour: int) -> list[str]:
        """Load log lines from OpenRCA dataset."""
        import pandas as pd
        # Try standard paths
        possible_paths = [
            os.path.join(dataset, "telemetry", date, "log", "log_service.csv"),
            os.path.join("..", "..", dataset, "telemetry", date, "log", "log_service.csv"),
            os.path.join("data", "openrca", dataset, "telemetry", date, "log", "log_service.csv"),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                df = pd.read_csv(path)
                # Filter by hour if timestamp available
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
                    df = df.dropna(subset=["timestamp"])
                    df["hour"] = pd.to_datetime(df["timestamp"], unit="s").dt.hour
                    df = df[df["hour"] == hour]
                lines = df["value"].dropna().astype(str).tolist()
                return lines
        print(f"Warning: no log data found for {dataset}/{date}")
        return []
