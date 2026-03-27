"""Benchmark runner -- batch experiments and configuration comparison."""
import os
import json
import time
from typing import Optional

from pipeline.config import load_config, PipelineConfig
from pipeline.trace import PipelineTrace, save_trace, load_trace
from benchmark.scoring import score_incident, compare_configs


class BenchmarkRunner:
    """Run experiments across datasets, dates, and configurations."""

    def __init__(self, config_path: str = "pipeline_config.yaml"):
        self.config = load_config(config_path)

    def run_experiment(self, pipeline_runner, traces_dir: str = "traces") -> list[PipelineTrace]:
        """Run pipeline for all incidents defined in config.benchmark."""
        traces = []
        for dataset in self.config.benchmark.datasets:
            for date in self.config.benchmark.dates:
                for hour in self.config.benchmark.hours:
                    print(f"Running: {dataset}/{date} hour {hour}")
                    trace = pipeline_runner.run(
                        dataset=dataset, date=date, hour=hour,
                        traces_dir=traces_dir,
                    )
                    traces.append(trace)
        return traces

    def score_traces(self, traces: list[PipelineTrace],
                     ground_truth_map: dict) -> dict:
        """Score a list of traces against ground truth.

        Args:
            ground_truth_map: {(dataset, date, hour): {"component": "X", "reason": "Y"}}
        """
        total = len(traces)
        correct = 0
        results = []

        for trace in traces:
            key = (trace.dataset, trace.date, trace.hour)
            gt = ground_truth_map.get(key, {})

            # Get predicted from agent results (any format)
            predicted = {}
            for fmt, result in trace.agent_results.items():
                if isinstance(result, dict) and "root_cause" in result:
                    predicted = result["root_cause"]
                    break

            if gt and predicted:
                score = score_incident(predicted, gt)
                if score["component_match"]:
                    correct += 1
                results.append({
                    "dataset": trace.dataset,
                    "date": trace.date,
                    "hour": trace.hour,
                    "predicted": predicted,
                    "ground_truth": gt,
                    "score": score,
                })

        accuracy = correct / total if total > 0 else 0
        return {
            "total_incidents": total,
            "correct": correct,
            "accuracy": round(accuracy, 4),
            "per_incident": results,
        }
