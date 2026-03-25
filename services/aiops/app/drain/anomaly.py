import numpy as np
from sklearn.ensemble import IsolationForest


class AnomalyDetector:
    def __init__(self, window_seconds: int = 300, contamination: float = 0.1):
        self.window_seconds = window_seconds
        self.contamination = contamination

    def detect(self, windows: list[dict]) -> list[dict]:
        """Run IsolationForest on template count windows.

        Args:
            windows: list of {window_start: str, template_counts: {template_id: count}}

        Returns:
            list of anomalous windows with scores and contributing templates.
        """
        if len(windows) < 2:
            return []

        # Build count matrix
        all_templates = set()
        for w in windows:
            all_templates.update(w["template_counts"].keys())
        template_list = sorted(all_templates)

        matrix = np.zeros((len(windows), len(template_list)))
        for i, w in enumerate(windows):
            for j, tid in enumerate(template_list):
                matrix[i, j] = w["template_counts"].get(tid, 0)

        # Run IsolationForest
        clf = IsolationForest(contamination=self.contamination, random_state=42)
        predictions = clf.fit_predict(matrix)
        scores = clf.decision_function(matrix)

        anomalies = []
        for i, (pred, score) in enumerate(zip(predictions, scores)):
            if pred == -1:  # anomaly
                # Find contributing templates (highest deviation from mean)
                means = matrix.mean(axis=0)
                deviations = {}
                for j, tid in enumerate(template_list):
                    if means[j] > 0:
                        dev = matrix[i, j] / means[j]
                        if dev > 2.0:
                            deviations[tid] = round(dev, 2)

                anomalies.append({
                    "window_start": windows[i]["window_start"],
                    "score": round(float(-score), 4),  # higher = more anomalous
                    "anomaly_type": "isolation_forest",
                    "contributing_templates": deviations,
                })

        # Sort by score descending
        anomalies.sort(key=lambda x: x["score"], reverse=True)
        return anomalies

    def detect_new_templates(self, known_templates: set, current_templates: set) -> list[dict]:
        """Flag new template IDs that weren't seen before."""
        new_ids = current_templates - known_templates
        return [
            {"cluster_id": tid, "anomaly_type": "new_template"}
            for tid in new_ids
        ]
