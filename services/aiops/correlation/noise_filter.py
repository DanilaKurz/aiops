"""Noise filter -- chronic/acute separation + entropy filtering."""
import math
from collections import Counter

from correlation.base import Correlator, Incident


class NoiseFilter(Correlator):
    name = "noise_filter"
    version = "1.0"

    def __init__(self, chronic_hours: int = 6, entropy_threshold: float = 0.3):
        self._chronic_hours = chronic_hours
        self._entropy_threshold = entropy_threshold

    def correlate(self, log_anomalies: list, metric_anomalies: list,
                  trace_anomalies: list, topology: dict) -> list[Incident]:
        """Filter anomalies: mark chronic as noise, keep acute as signal."""
        all_anomalies = []
        for a in metric_anomalies:
            comp = a.get("component", a.component if hasattr(a, "component") else "")
            all_anomalies.append({"component": comp, "source": "metrics", "data": a})
        for a in log_anomalies:
            comp = a.get("component", "") if isinstance(a, dict) else ""
            all_anomalies.append({"component": comp, "source": "logs", "data": a})

        if not all_anomalies:
            return []

        component_counts = Counter(a["component"] for a in all_anomalies if a["component"])

        acute = []
        chronic = []
        for a in all_anomalies:
            comp = a["component"]
            if not comp:
                continue
            if component_counts[comp] > self._chronic_hours:
                chronic.append(a)
            else:
                acute.append(a)

        # Entropy filtering on acute alerts
        filtered_acute = []
        if acute:
            source_counts = Counter(a["source"] for a in acute)
            entropy = self._compute_entropy(source_counts)
            if entropy >= self._entropy_threshold or len(acute) <= 2:
                filtered_acute = acute
            else:
                seen = set()
                for a in acute:
                    if a["component"] not in seen:
                        filtered_acute.append(a)
                        seen.add(a["component"])

        acute_components = sorted(set(a["component"] for a in filtered_acute if a["component"]))
        chronic_components = sorted(set(a["component"] for a in chronic if a["component"]))

        incidents = []
        if acute_components:
            incidents.append(Incident(
                severity="critical" if len(acute_components) >= 3 else "warning",
                components=acute_components,
                root_cause_candidate=acute_components[0] if acute_components else "",
                onset="",
                signals={"acute": acute_components, "chronic_filtered": chronic_components},
                confidence=0.8,
                correlator_name=self.name,
                details={
                    "total_anomalies": len(all_anomalies),
                    "acute_count": len(filtered_acute),
                    "chronic_count": len(chronic),
                    "filtered_count": len(all_anomalies) - len(filtered_acute),
                    "noise_reduction": round(1 - len(filtered_acute) / max(len(all_anomalies), 1), 2),
                },
            ))
        return incidents

    def _compute_entropy(self, counts: Counter) -> float:
        total = sum(counts.values())
        if total <= 1:
            return 0.0
        entropy = 0.0
        for count in counts.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    def reset(self) -> None:
        pass
