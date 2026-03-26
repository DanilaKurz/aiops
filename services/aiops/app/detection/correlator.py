"""Incident Correlator -- groups alerts into incidents using topology and timing."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Incident:
    id: str
    severity: str  # "critical" | "warning" | "info"
    components: list
    golden_signal_alerts: list
    infra_alerts: list
    root_cause_candidate: Optional[str]
    summary: str
    requires_investigation: bool

    def to_agent_context(self, topology: dict = None) -> str:
        """Build concise context string for the AI agent."""
        lines = [f"INCIDENT: {self.summary}"]
        lines.append(f"Severity: {self.severity}")
        lines.append(f"Components affected: {', '.join(self.components)}")

        if self.golden_signal_alerts:
            lines.append("\nSERVICE IMPACT (Golden Signals):")
            for gs in self.golden_signal_alerts:
                lines.append(f"  - {gs.description}")

        if self.infra_alerts:
            lines.append("\nINFRASTRUCTURE ANOMALIES:")
            for ia in self.infra_alerts:
                lines.append(f"  - {ia.description}")
                for kpi in ia.top_kpis[:3]:
                    lines.append(f"    * {kpi['kpi'][:40]}: {kpi['value']} (baseline {kpi['baseline']}, {kpi['deviation']}x)")

        if self.root_cause_candidate:
            lines.append(f"\nSUSPECTED ROOT CAUSE COMPONENT: {self.root_cause_candidate}")

        return "\n".join(lines)


class IncidentCorrelator:
    """Groups golden signal alerts and infra alerts into incidents.

    Decision logic:
    - Golden signals degraded + infra anomalies on related components -> CRITICAL, investigate
    - 3+ related infra components anomalous -> WARNING, investigate
    - 1-2 unrelated components -> INFO, NO investigation (agent decides NO_ACTION)
    - Nothing significant -> no incident at all
    """

    def __init__(self, time_window_seconds=600):
        self.time_window = time_window_seconds

    def correlate(self, golden_alerts: list, infra_alerts: list,
                  topology: dict, dataset: str, date: str, hour: int) -> list[Incident]:
        neighbors = {}
        for node in topology.get("nodes", []):
            neighbors[node] = set()
        for edge in topology.get("edges", []):
            neighbors.setdefault(edge["source"], set()).add(edge["target"])
            neighbors.setdefault(edge["target"], set()).add(edge["source"])

        incidents = []
        used_infra = set()

        # 1. Golden signal drop + related infra = CRITICAL
        critical_gs = [g for g in golden_alerts if g.severity == "critical"]
        if critical_gs:
            affected = set()
            for ia in infra_alerts:
                if ia.component in neighbors:
                    affected.add(ia.component)
                    used_infra.add(ia.component)

            if affected:
                root = self._find_deepest(affected, neighbors)
                incidents.append(Incident(
                    id=f"INC-{dataset}-{date}-h{hour}-critical",
                    severity="critical",
                    components=sorted(affected),
                    golden_signal_alerts=critical_gs,
                    infra_alerts=[ia for ia in infra_alerts if ia.component in affected],
                    root_cause_candidate=root,
                    summary=f"Service degradation: {len(critical_gs)} golden signal drops, {len(affected)} infra components affected.",
                    requires_investigation=True,
                ))

        # 2. Cluster remaining infra alerts by topology
        remaining = [ia for ia in infra_alerts
                     if ia.component not in used_infra
                     and ia.severity in ("critical", "warning")]

        if len(remaining) >= 3:
            clusters = self._cluster_by_topology(remaining, neighbors)
            for cluster in clusters:
                if len(cluster) >= 3:
                    comps = sorted(ia.component for ia in cluster)
                    root = self._find_deepest(set(comps), neighbors)
                    incidents.append(Incident(
                        id=f"INC-{dataset}-{date}-h{hour}-infra",
                        severity="warning",
                        components=comps,
                        golden_signal_alerts=[],
                        infra_alerts=cluster,
                        root_cause_candidate=root,
                        summary=f"Infrastructure anomaly cluster: {len(comps)} related components.",
                        requires_investigation=True,
                    ))

        # 3. Minor observations -- no investigation
        if not incidents and (golden_alerts or infra_alerts):
            incidents.append(Incident(
                id=f"INC-{dataset}-{date}-h{hour}-obs",
                severity="info",
                components=[ia.component for ia in infra_alerts],
                golden_signal_alerts=golden_alerts,
                infra_alerts=infra_alerts,
                root_cause_candidate=None,
                summary="Minor anomalies, no correlated pattern.",
                requires_investigation=False,
            ))

        return incidents

    def _find_deepest(self, components: set, neighbors: dict) -> Optional[str]:
        """Component with fewest outgoing edges to other affected = likely root cause."""
        if not components:
            return None
        scores = {}
        for comp in components:
            scores[comp] = sum(1 for n in neighbors.get(comp, set()) if n in components)
        return min(scores, key=scores.get) if scores else next(iter(components))

    def _cluster_by_topology(self, alerts: list, neighbors: dict) -> list[list]:
        components = {ia.component for ia in alerts}
        comp_map = {ia.component: ia for ia in alerts}
        visited = set()
        clusters = []

        for comp in components:
            if comp in visited:
                continue
            cluster = set()
            queue = [comp]
            while queue:
                cur = queue.pop(0)
                if cur in visited:
                    continue
                visited.add(cur)
                if cur in components:
                    cluster.add(cur)
                    for n in neighbors.get(cur, set()):
                        if n in components and n not in visited:
                            queue.append(n)
            if cluster:
                clusters.append([comp_map[c] for c in cluster if c in comp_map])

        return clusters
