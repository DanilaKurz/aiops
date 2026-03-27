"""PipelineTrace -- full record of a pipeline run."""
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class PipelineTrace:
    dataset: str
    date: str
    hour: int
    config_snapshot: dict

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Parsing
    raw_log_count: int = 0
    parse_results: dict = field(default_factory=dict)
    ensemble_results: list = field(default_factory=list)
    template_summary: dict = field(default_factory=dict)

    # Detection
    anomalies: list = field(default_factory=list)
    golden_signals: list = field(default_factory=list)
    infra_alerts: list = field(default_factory=list)
    incidents: list = field(default_factory=list)

    # Context
    agent_contexts: dict = field(default_factory=dict)
    context_token_counts: dict = field(default_factory=dict)

    # Investigation
    agent_results: dict = field(default_factory=dict)
    tool_call_log: list = field(default_factory=list)

    # Evaluation
    ground_truth: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)

    # Performance
    timing: dict = field(default_factory=dict)


def save_trace(trace: PipelineTrace, base_dir: str) -> str:
    trace_dir = os.path.join(base_dir, trace.trace_id)
    os.makedirs(trace_dir, exist_ok=True)
    with open(os.path.join(trace_dir, "trace.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(trace), f, indent=2, default=str, ensure_ascii=False)
    return trace_dir


def load_trace(trace_dir: str) -> PipelineTrace:
    with open(os.path.join(trace_dir, "trace.json"), encoding="utf-8") as f:
        data = json.load(f)
    return PipelineTrace(**data)
