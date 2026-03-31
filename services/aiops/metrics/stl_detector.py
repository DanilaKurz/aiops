"""STL detector -- seasonal decomposition for metric anomaly detection."""
import numpy as np
import pandas as pd
from metrics.base import MetricDetector, DetectionResult

try:
    from statsmodels.tsa.seasonal import STL
    _STL_AVAILABLE = True
except ImportError:
    _STL_AVAILABLE = False


class STLDetector(MetricDetector):
    name = "stl"
    version = "1.0"

    def __init__(self, period: int = 60, robust: bool = False,
                 anomaly_threshold: float = 3.0):
        self._period = period  # data points per seasonal cycle
        self._robust = robust  # False keeps outliers in remainder for detection
        self._threshold = anomaly_threshold  # N * std in remainder

    def detect(self, df: pd.DataFrame, component: str) -> list[DetectionResult]:
        results = []
        if not _STL_AVAILABLE or df.empty:
            return results
        comp_df = df[df["cmdb_id"] == component] if "cmdb_id" in df.columns else df
        for kpi in comp_df["kpi_name"].unique():
            kpi_df = comp_df[comp_df["kpi_name"] == kpi].sort_values("timestamp")
            values = kpi_df["value"].values.astype(float)
            # STL needs at least 2 full periods
            if len(values) < self._period * 2:
                continue
            try:
                stl = STL(values, period=self._period, robust=self._robust)
                decomposition = stl.fit()
                remainder = decomposition.resid
                trend = decomposition.trend
                std = np.std(remainder)
                if std < 1e-10:
                    continue
                # Flag points where remainder exceeds threshold
                anomaly_mask = np.abs(remainder) > self._threshold * std
                for idx in np.where(anomaly_mask)[0]:
                    ts_val = str(kpi_df.iloc[idx]["timestamp"]) if idx < len(kpi_df) else ""
                    results.append(DetectionResult(
                        component=component, metric=str(kpi),
                        anomaly_type="seasonal_deviation",
                        timestamp=ts_val,
                        value=float(values[idx]),
                        baseline=float(trend[idx]),
                        score=min(1.0, float(abs(remainder[idx]) / (self._threshold * std))),
                        detector_name=self.name,
                        details={
                            "remainder": float(remainder[idx]),
                            "trend": float(trend[idx]),
                            "std": float(std),
                            "period": self._period,
                        },
                    ))
            except Exception:
                continue
        return results

    def reset(self) -> None:
        pass
