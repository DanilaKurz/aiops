"""Context formatter -- generates self-documenting agent context in JSON and Narrative formats.

Principle: every value is accompanied by three things:
  - What it is (human-readable name + component role)
  - What's normal (baseline/normal range)
  - Why it's suspicious (multiplier, trend, temporal correlation)
"""
import json
from typing import Optional


class ContextFormatter:
    """Generates agent context in JSON and Narrative formats."""

    def format_json(self, dataset: str, date: str, hour: int,
                    golden_signals: list[dict], components: list[dict],
                    topology: dict, ensemble_summary: Optional[dict] = None) -> str:
        """Generate JSON context with self-documenting fields."""
        context = {
            "incident": {
                "system": dataset,
                "system_description": self._get_system_description(dataset),
                "date": date,
                "hour": hour,
                "severity": self._determine_severity(golden_signals),
                "severity_reason": self._severity_reason(golden_signals),
            },
            "user_impact": self._format_user_impact_json(golden_signals),
            "suspicious_components": self._format_components_json(components),
            "topology": topology,
        }
        if ensemble_summary:
            context["ensemble_parsing"] = ensemble_summary
        return json.dumps(context, indent=2, ensure_ascii=False)

    def format_narrative(self, dataset: str, date: str, hour: int,
                         golden_signals: list[dict], components: list[dict],
                         topology: dict, ensemble_summary: Optional[dict] = None) -> str:
        """Generate narrative context with hierarchical sections."""
        lines = []
        lines.append("=== INCIDENT CONTEXT ===")
        lines.append(f"System: {dataset} ({self._get_system_description(dataset)})")
        lines.append(f"Date: {date}, Hour {hour} ({hour:02d}:00-{hour+1:02d}:00)")
        lines.append("")

        lines.append("=== WHAT USERS SEE (Golden Signals) ===")
        lines.append("(These measure the end-user experience)")
        lines.append("")
        for gs in golden_signals:
            svc = gs.get("service", "unknown")
            role = gs.get("role", "service health check")
            lines.append(f"{svc} ({role}):")
            if "sr_min" in gs:
                sr = gs["sr_min"]
                lines.append(f"  Success rate: {sr}%")
                lines.append("    (% of requests completing without error)")
                lines.append(f"    Normal: 99-100%. {'CRITICAL' if sr < 90 else 'WARNING'}: current {sr}%")
            if "mrt_max" in gs:
                mrt = gs["mrt_max"]
                normal_mrt = gs.get("mrt_normal", 350)
                mult = round(mrt / normal_mrt, 1) if normal_mrt > 0 else 0
                lines.append(f"  Response time: {mrt:.0f}ms")
                lines.append("    (average time to serve one request)")
                lines.append(f"    Normal: ~{normal_mrt}ms. Current = {mult}x slower.")
            lines.append("")

        lines.append("=== SUSPICIOUS COMPONENTS (ranked by severity) ===")
        lines.append("(Infrastructure anomalies that may explain the user impact above)")
        lines.append("")
        for i, comp in enumerate(components, 1):
            name = comp.get("name", "unknown")
            role = comp.get("role", "")
            severity = comp.get("severity", "info")
            is_new = comp.get("is_new", False)
            onset = comp.get("onset", "")

            status_tag = "NEW" if is_new else "CHRONIC"
            lines.append(f"[{i}] {name} -- {severity.upper()} ({status_tag})")
            if role:
                lines.append(f"    Role: {role}")
            if is_new:
                lines.append("    Status: was NOT anomalous in previous hours")
            else:
                lines.append("    Status: anomalous in previous hours (less likely root cause)")
            if onset:
                lines.append(f"    First anomaly: {onset}")
            lines.append("")

            for m in comp.get("metrics", []):
                mname = m.get("name", "metric")
                val = m.get("value", 0)
                unit = m.get("unit", "")
                normal = m.get("normal", "unknown")
                mult = m.get("multiplier", 0)
                trend = m.get("trend", "")
                history = m.get("history_hours", [])

                lines.append(f"    {mname}: {val}{unit}")
                lines.append(f"      Normal for this host: {normal}")
                if mult:
                    lines.append(f"      {mult}x above normal baseline")
                if history:
                    hist_str = ", ".join(f"{h}{unit}" for h in history)
                    lines.append(f"      Previous 3 hours: {hist_str}")
                if trend:
                    lines.append(f"      {trend}")
                lines.append("")

            for lt in comp.get("log_templates", []):
                tmpl = lt.get("template", "")
                count = lt.get("count", 0)
                meaning = lt.get("meaning", "")
                agreement = lt.get("agreement", 0)
                lines.append(f"    Log: \"{tmpl}\" -- {count} occurrences")
                if meaning:
                    lines.append(f"      ({meaning})")
                if agreement:
                    lines.append(f"      Parser agreement: {agreement*100:.0f}%")
                lines.append("")

            why = comp.get("why_suspicious", "")
            if why:
                lines.append(f"    Why suspicious: {why}")
                lines.append("")

        lines.append("=== SERVICE DEPENDENCIES ===")
        lines.append("(Arrows show 'depends on'. Problems propagate right-to-left.)")
        lines.append("")
        for edge in topology.get("edges", []):
            src = edge.get("source", "?")
            tgt = edge.get("target", "?")
            lines.append(f"  {src} -> {tgt}")
        lines.append("")

        if ensemble_summary:
            lines.append("=== ENSEMBLE PARSING SUMMARY ===")
            lines.append("(How confident is the log analysis)")
            lines.append("")
            parsers_used = ensemble_summary.get("parsers_used", [])
            overall_agreement = ensemble_summary.get("overall_agreement", 0)
            lines.append(f"Parsers used: {', '.join(parsers_used)}")
            lines.append(f"Overall agreement: {overall_agreement*100:.0f}%")
            for t in ensemble_summary.get("anomalous_templates", []):
                tmpl = t.get("template", "")
                count = t.get("count", 0)
                svc = t.get("service", "")
                agr = t.get("agreement", 0)
                lines.append(f"  \"{tmpl}\" -- {count}x in {svc} (agreement {agr*100:.0f}%)")
            lines.append("")

        return "\n".join(lines)

    def _get_system_description(self, dataset: str) -> str:
        descriptions = {
            "Bank": "4-tier architecture: ingress -> app servers -> middleware -> database/cache",
            "Market": "Kubernetes microservices with multiple replicas",
            "Telecom": "containerized services with minimal topology",
        }
        return descriptions.get(dataset, "distributed system")

    def _determine_severity(self, golden_signals: list[dict]) -> str:
        for gs in golden_signals:
            if gs.get("sr_min", 100) < 90:
                return "critical"
            if gs.get("sr_min", 100) < 95:
                return "warning"
        return "info"

    def _severity_reason(self, golden_signals: list[dict]) -> str:
        for gs in golden_signals:
            sr = gs.get("sr_min", 100)
            if sr < 90:
                return f"End-user success rate below 90% ({sr}%)"
            if sr < 95:
                return f"End-user success rate below 95% ({sr}%)"
        return "No critical degradation detected"

    def _format_user_impact_json(self, golden_signals: list[dict]) -> list[dict]:
        impacts = []
        for gs in golden_signals:
            impact = {
                "service": gs.get("service", "unknown"),
                "role": gs.get("role", "service health check"),
            }
            if "sr_min" in gs:
                impact["success_rate"] = {
                    "value": gs["sr_min"], "unit": "%",
                    "meaning": "% of requests completing without error",
                    "normal_range": "99-100%",
                    "verdict": f"{100 - gs['sr_min']:.1f}% of requests FAILING",
                }
            if "mrt_max" in gs:
                normal = gs.get("mrt_normal", 350)
                mult = round(gs["mrt_max"] / normal, 1) if normal > 0 else 0
                impact["response_time_ms"] = {
                    "value": gs["mrt_max"], "normal": normal,
                    "verdict": f"{mult}x slower than usual",
                }
            impacts.append(impact)
        return impacts

    def _format_components_json(self, components: list[dict]) -> list[dict]:
        formatted = []
        for comp in components:
            fc = {
                "name": comp.get("name", ""),
                "role": comp.get("role", ""),
                "tier": comp.get("tier", ""),
                "severity": comp.get("severity", "info"),
                "is_new": comp.get("is_new", False),
            }
            if comp.get("is_new"):
                fc["is_new_explanation"] = "was NOT anomalous in previous 6 hours"
            else:
                fc["is_new_explanation"] = "anomalous in previous hours (less likely root cause)"
            if comp.get("onset"):
                fc["onset"] = comp["onset"]
            fc["metrics"] = []
            for m in comp.get("metrics", []):
                fm = {
                    "name": m.get("name", ""),
                    "value": m.get("value", 0),
                    "unit": m.get("unit", ""),
                    "normal_range": m.get("normal", ""),
                }
                if m.get("multiplier"):
                    fm["multiplier"] = m["multiplier"]
                if m.get("trend"):
                    fm["trend"] = m["trend"]
                if m.get("history_hours"):
                    fm["history_hours"] = m["history_hours"]
                fc["metrics"].append(fm)
            if comp.get("log_templates"):
                fc["log_analysis"] = []
                for lt in comp["log_templates"]:
                    flt = {
                        "template": lt.get("template", ""),
                        "count": lt.get("count", 0),
                    }
                    if lt.get("meaning"):
                        flt["meaning"] = lt["meaning"]
                    if lt.get("agreement"):
                        flt["parser_agreement"] = lt["agreement"]
                    fc["log_analysis"].append(flt)
            if comp.get("why_suspicious"):
                fc["why_suspicious"] = comp["why_suspicious"]
            formatted.append(fc)
        return formatted
