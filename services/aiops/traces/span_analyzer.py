"""Span analyzer -- detect anomalous spans by latency."""

from __future__ import annotations

import pandas as pd

from traces.base import TraceAnalyzer, TraceResult


class SpanAnalyzer(TraceAnalyzer):
    """Detect anomalous spans where duration exceeds N * median for that service."""

    name = "span_analyzer"
    version = "1.0"

    def __init__(self, latency_threshold_multiplier: float = 3.0):
        self._threshold = latency_threshold_multiplier

    def analyze(self, spans_df: pd.DataFrame) -> list[TraceResult]:
        results: list[TraceResult] = []
        if spans_df.empty or "duration" not in spans_df.columns:
            return results

        # Compute median duration per service
        service_col = (
            "cmdb_id" if "cmdb_id" in spans_df.columns else spans_df.columns[1]
        )
        medians = spans_df.groupby(service_col)["duration"].median()

        # Group by trace
        trace_col = "trace_id" if "trace_id" in spans_df.columns else None
        if trace_col is None:
            return results

        for trace_id, trace_df in spans_df.groupby(trace_col):
            anomalous_spans: list[dict] = []
            total_duration = trace_df["duration"].sum()
            bottleneck = ""
            max_duration = 0.0

            for _, span in trace_df.iterrows():
                svc = span.get(service_col, "")
                dur = float(span.get("duration", 0))
                median_dur = float(medians.get(svc, dur))

                if dur > max_duration:
                    max_duration = dur
                    bottleneck = str(svc)

                if median_dur > 0 and dur > self._threshold * median_dur:
                    anomalous_spans.append(
                        {
                            "span_id": str(span.get("span_id", "")),
                            "service": str(svc),
                            "duration": dur,
                            "median": median_dur,
                            "multiplier": round(dur / median_dur, 1),
                        }
                    )

            is_anomalous = len(anomalous_spans) > 0
            normal_latency = float(medians.mean()) if len(medians) > 0 else 0.0

            results.append(
                TraceResult(
                    trace_id=str(trace_id),
                    is_anomalous=is_anomalous,
                    bottleneck_service=bottleneck,
                    latency_ms=float(total_duration),
                    normal_latency_ms=normal_latency,
                    anomalous_spans=anomalous_spans,
                    analyzer_name=self.name,
                )
            )
        return results

    def reset(self) -> None:
        pass
