"""CLI entrypoint for the AIOps ensemble pipeline."""
import argparse
import sys
import os

# Add services/aiops to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from pipeline.runner import PipelineRunner, register_parser
from parsers.drain_parser import Drain3Parser


def main():
    parser = argparse.ArgumentParser(description="AIOps Ensemble Pipeline")
    parser.add_argument("--config", default="pipeline_config.yaml")
    parser.add_argument("--dataset", default="Bank")
    parser.add_argument("--date", default="2021_03_04")
    parser.add_argument("--hour", type=int, default=7)
    parser.add_argument("--traces-dir", default="traces")
    args = parser.parse_args()

    # Register available parsers
    register_parser("drain3", Drain3Parser)
    # register_parser("loglshd", LogLSHDParser)  # TODO: add after integration
    # register_parser("lilac", LILACParser)

    runner = PipelineRunner(config_path=args.config)
    trace = runner.run(
        dataset=args.dataset, date=args.date,
        hour=args.hour, traces_dir=args.traces_dir,
    )
    print(f"Pipeline complete. Trace: {trace.trace_id}")
    print(f"  Logs parsed: {trace.raw_log_count}")
    print(f"  Templates: {trace.template_summary}")
    print(f"  Timing: {trace.timing}")


if __name__ == "__main__":
    main()
