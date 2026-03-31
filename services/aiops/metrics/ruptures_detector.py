"""ruptures detector -- PELT change point detection for metrics."""
import ruptures
import numpy as np
import pandas as pd
from metrics.base import MetricDetector, DetectionResult


class RupturesDetector(MetricDetector):
    name = "ruptures"
    version = "1.0"

    def __init__(self, method: str = "pelt", penalty: str = "rbf",
                 min_size: int = 5, pen_value: float = 1.0):
        self._method = method
        self._penalty = penalty
        self._min_size = min_size
        self._pen_value = pen_value

    def detect(self, df: pd.DataFrame, component: str) -> list[DetectionResult]:
        results = []
        if df.empty:
            return results
        comp_df = df[df["cmdb_id"] == component] if "cmdb_id" in df.columns else df
        for kpi in comp_df["kpi_name"].unique():
            kpi_df = comp_df[comp_df["kpi_name"] == kpi].sort_values("timestamp")
            values = kpi_df["value"].values.astype(float)
            if len(values) < self._min_size * 2:
                continue
            try:
                algo = ruptures.Pelt(model=self._penalty, min_size=self._min_size)
                change_points = algo.fit_predict(values, pen=self._pen_value)
                for cp in change_points[:-1]:
                    before = values[max(0, cp - self._min_size):cp]
                    after = values[cp:min(len(values), cp + self._min_size)]
                    if len(before) > 0 and len(after) > 0:
                        baseline = float(np.median(before))
                        current = float(np.median(after))
                        if abs(current - baseline) > 2 * max(np.std(before), 0.01):
                            ts_val = str(kpi_df.iloc[min(cp, len(kpi_df) - 1)]["timestamp"])
                            results.append(DetectionResult(
                                component=component, metric=str(kpi),
                                anomaly_type="change_point", timestamp=ts_val,
                                value=current, baseline=baseline,
                                score=min(1.0, abs(current - baseline) / max(abs(baseline), 0.01)),
                                detector_name=self.name,
                                details={"change_point_index": cp, "method": self._method},
                            ))
            except Exception:
                continue
        return results

    def reset(self) -> None:
        pass
