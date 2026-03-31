"""MetricDetector ABC and DetectionResult."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class DetectionResult:
    """Result of anomaly detection on a single metric time series.

    Attributes:
        component: Infrastructure component id, e.g. "Redis02".
        metric: KPI name, e.g. "CPUCpuUtil".
        anomaly_type: One of "change_point", "spike", "seasonal_deviation".
        timestamp: ISO timestamp or unix epoch of the anomaly.
        value: Observed value at the anomaly point.
        baseline: Expected normal value.
        score: Anomaly confidence score in [0.0, 1.0].
        detector_name: Name of the detector that produced this result.
        details: Arbitrary extra data (detector-specific).
    """

    component: str
    metric: str
    anomaly_type: str
    timestamp: str
    value: float
    baseline: float
    score: float
    detector_name: str
    details: dict = field(default_factory=dict)


class MetricDetector(ABC):
    """Abstract base class for metric anomaly detectors.

    Every detector (ruptures, PyOD, STL, OneShotSTL, BARO)
    must subclass this and implement detect() and reset().

    Class attributes:
        name: Short identifier for the detector (e.g. "ruptures").
        version: Semantic version string for the adapter.
    """

    name: str
    version: str

    @abstractmethod
    def detect(self, df: pd.DataFrame, component: str) -> list[DetectionResult]:
        """Detect anomalies in metrics for a specific component.

        Args:
            df: DataFrame with columns: timestamp, cmdb_id, kpi_name, value (long format).
            component: The component id to detect anomalies for.

        Returns:
            List of DetectionResult instances.
        """
        ...

    def detect_all(self, df: pd.DataFrame) -> list[DetectionResult]:
        """Detect anomalies across all components in the dataframe."""
        results = []
        if "cmdb_id" in df.columns:
            for comp in df["cmdb_id"].unique():
                comp_df = df[df["cmdb_id"] == comp]
                results.extend(self.detect(comp_df, str(comp)))
        return results

    @abstractmethod
    def reset(self) -> None:
        """Clear all learned state for fair benchmark runs."""
        ...
