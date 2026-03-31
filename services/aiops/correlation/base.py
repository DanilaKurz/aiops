"""Correlator ABC and Incident dataclass."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import uuid


@dataclass
class Incident:
    """Correlated incident combining signals from logs, metrics, and traces.

    Attributes:
        severity: One of "critical", "warning", "info".
        components: List of affected component ids.
        root_cause_candidate: Best guess for the root cause component.
        onset: Timestamp of the earliest correlated signal.
        signals: Dict mapping signal type to list of anomalies,
                 e.g. {"logs": [...], "metrics": [...], "traces": [...]}.
        confidence: Correlation confidence score in [0.0, 1.0].
        correlator_name: Name of the correlator that produced this incident.
        incident_id: Auto-generated short UUID for tracking.
        details: Arbitrary extra data (correlator-specific).
    """

    severity: str
    components: list[str] = field(default_factory=list)
    root_cause_candidate: str = ""
    onset: str = ""
    signals: dict = field(default_factory=dict)
    confidence: float = 0.0
    correlator_name: str = ""
    incident_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    details: dict = field(default_factory=dict)


class Correlator(ABC):
    """Abstract base class for cross-signal correlators.

    Every correlator (temporal co-occurrence, topological walk)
    must subclass this and implement correlate() and reset().

    Class attributes:
        name: Short identifier for the correlator.
        version: Semantic version string for the adapter.
    """

    name: str
    version: str

    @abstractmethod
    def correlate(
        self,
        log_anomalies: list,
        metric_anomalies: list,
        trace_anomalies: list,
        topology: dict,
    ) -> list[Incident]:
        """Correlate anomalies from all signal types.

        Args:
            log_anomalies: List of log-level anomalies.
            metric_anomalies: List of DetectionResult instances.
            trace_anomalies: List of TraceResult instances.
            topology: Service dependency graph as adjacency dict.

        Returns:
            List of Incident instances.
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """Clear all learned state for fair benchmark runs."""
        ...
