"""Topological correlator -- upstream walk for root cause."""
from collections import defaultdict
from correlation.base import Correlator, Incident


class TopologicalCorrelator(Correlator):
    name = "topological"
    version = "1.0"

    def correlate(self, log_anomalies: list, metric_anomalies: list,
                  trace_anomalies: list, topology: dict) -> list[Incident]:
        # Collect anomalous components
        anomalous = set()
        for a in metric_anomalies:
            comp = a.get("component", a.component if hasattr(a, "component") else "")
            if comp:
                anomalous.add(comp)
        for a in log_anomalies:
            comp = a.get("component", "") if isinstance(a, dict) else ""
            if comp:
                anomalous.add(comp)

        if not anomalous or not topology:
            return []

        # Build reverse graph (child -> parents)
        edges = topology.get("edges", [])
        parents = defaultdict(set)  # child -> set of parents
        for e in edges:
            src = e.get("source", "")
            tgt = e.get("target", "")
            if src and tgt:
                parents[src].add(tgt)

        # For each anomalous component, walk upstream to find deepest anomalous ancestor
        root_candidates = {}
        for comp in anomalous:
            depth, root = self._find_deepest_upstream(comp, anomalous, parents, set())
            root_candidates[comp] = {"root": root, "depth": depth}

        # The component that is deepest upstream AND anomalous = root cause
        if root_candidates:
            best = max(root_candidates.values(), key=lambda x: x["depth"])
            root_cause = best["root"]
        else:
            root_cause = list(anomalous)[0] if anomalous else ""

        return [Incident(
            severity="critical" if len(anomalous) >= 3 else "warning",
            components=sorted(anomalous),
            root_cause_candidate=root_cause,
            onset="",
            signals={"anomalous_components": sorted(anomalous)},
            confidence=min(1.0, len(anomalous) / 5),
            correlator_name=self.name,
            details={"root_candidates": root_candidates},
        )]

    def _find_deepest_upstream(self, component, anomalous, parents, visited):
        """DFS upstream: find deepest anomalous ancestor."""
        if component in visited:
            return 0, component
        visited.add(component)

        best_depth = 0
        best_root = component

        for parent in parents.get(component, set()):
            if parent in anomalous:
                depth, root = self._find_deepest_upstream(parent, anomalous, parents, visited)
                if depth + 1 > best_depth:
                    best_depth = depth + 1
                    best_root = root

        return best_depth, best_root

    def reset(self) -> None:
        pass
