"""TraceAnalyzer ABC and TraceResult dataclass."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class TraceResult:
    """Result of trace analysis for a single trace.

    Attributes:
        trace_id: Unique trace identifier.
        is_anomalous: Whether the trace is considered anomalous.
        bottleneck_service: The service identified as the bottleneck.
        critical_path: Ordered list of services on the critical path.
        latency_ms: Total observed latency in milliseconds.
        normal_latency_ms: Expected normal latency in milliseconds.
        anomalous_spans: List of dicts describing anomalous spans.
        analyzer_name: Name of the analyzer that produced this result.
        details: Arbitrary extra data (analyzer-specific).
    """

    trace_id: str
    is_anomalous: bool
    bottleneck_service: str
    critical_path: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    normal_latency_ms: float = 0.0
    anomalous_spans: list[dict] = field(default_factory=list)
    analyzer_name: str = ""
    details: dict = field(default_factory=dict)


class TraceAnalyzer(ABC):
    """Abstract base class for trace analyzers.

    Every analyzer (span latency, dependency graph, critical path)
    must subclass this and implement analyze() and reset().

    Class attributes:
        name: Short identifier for the analyzer.
        version: Semantic version string for the adapter.
    """

    name: str
    version: str

    @abstractmethod
    def analyze(self, spans_df: pd.DataFrame) -> list[TraceResult]:
        """Analyze trace spans.

        Args:
            spans_df: DataFrame with columns:
                      timestamp, cmdb_id, span_id, parent_id, trace_id, duration.

        Returns:
            List of TraceResult instances.
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """Clear all learned state for fair benchmark runs."""
        ...
