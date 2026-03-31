"""PyOD detector -- ensemble anomaly detection for metrics."""
import numpy as np
import pandas as pd
from metrics.base import MetricDetector, DetectionResult

try:
    from pyod.models.iforest import IForest
    from pyod.models.lof import LOF
    from pyod.models.ocsvm import OCSVM
    _PYOD_AVAILABLE = True
except ImportError:
    _PYOD_AVAILABLE = False


class PyODDetector(MetricDetector):
    name = "pyod"
    version = "1.0"

    def __init__(self, methods: list[str] = None, contamination: float = 0.1):
        self._methods = methods or ["iforest", "lof", "ocsvm"]
        self._contamination = contamination

    def detect(self, df: pd.DataFrame, component: str) -> list[DetectionResult]:
        results = []
        if not _PYOD_AVAILABLE or df.empty:
            return results
        comp_df = df[df["cmdb_id"] == component] if "cmdb_id" in df.columns else df
        if comp_df.empty:
            return results

        # Pivot: rows=timestamp, columns=kpi_name, values=value
        try:
            pivot = comp_df.pivot_table(index="timestamp", columns="kpi_name",
                                         values="value", aggfunc="first")
            pivot = pivot.fillna(0).values
            if pivot.shape[0] < 10 or pivot.shape[1] < 1:
                return results
        except Exception:
            return results

        # Run each method, collect scores
        all_scores = []
        model_map = {
            "iforest": lambda: IForest(contamination=self._contamination, random_state=42),
            "lof": lambda: LOF(contamination=self._contamination),
            "ocsvm": lambda: OCSVM(contamination=self._contamination),
        }
        for method_name in self._methods:
            if method_name not in model_map:
                continue
            try:
                model = model_map[method_name]()
                model.fit(pivot)
                scores = model.decision_scores_
                all_scores.append(scores)
            except Exception:
                continue

        if not all_scores:
            return results

        # Ensemble: average scores, flag top anomalies
        avg_scores = np.mean(all_scores, axis=0)
        threshold = np.percentile(avg_scores, (1 - self._contamination) * 100)
        timestamps = comp_df.pivot_table(index="timestamp", columns="kpi_name",
                                          values="value", aggfunc="first").index

        for i, score in enumerate(avg_scores):
            if score > threshold:
                ts_val = str(timestamps[i]) if i < len(timestamps) else ""
                results.append(DetectionResult(
                    component=component, metric="multi_kpi",
                    anomaly_type="ensemble_anomaly",
                    timestamp=ts_val,
                    value=float(score), baseline=float(threshold),
                    score=min(1.0, float(score / max(threshold, 0.01))),
                    detector_name=self.name,
                    details={"methods": self._methods, "n_kpis": pivot.shape[1]},
                ))
        return results

    def reset(self) -> None:
        pass
