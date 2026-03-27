"""Scoring metrics for pipeline benchmark -- per-incident, per-parser, cross-config."""


def score_incident(predicted: dict, ground_truth: dict) -> dict:
    """Score a single incident prediction against ground truth.

    Args:
        predicted: {"component": "Redis02", "reason": "high CPU", "onset_time": "07:01"}
        ground_truth: {"component": "Redis02", "reason": "high CPU usage"}

    Returns dict with:
        component_match: bool
        reason_similarity: float (0-1, simple word overlap)
    """
    pred_comp = str(predicted.get("component", "")).lower().strip()
    gt_comp = str(ground_truth.get("component", "")).lower().strip()
    component_match = pred_comp == gt_comp

    # Simple word overlap for reason similarity
    pred_words = set(str(predicted.get("reason", "")).lower().split())
    gt_words = set(str(ground_truth.get("reason", "")).lower().split())
    if pred_words and gt_words:
        overlap = len(pred_words & gt_words)
        reason_similarity = overlap / max(len(pred_words), len(gt_words))
    else:
        reason_similarity = 0.0

    return {
        "component_match": component_match,
        "reason_similarity": round(reason_similarity, 3),
    }


def score_parser(template_count: int, parsing_time: float,
                 llm_calls: int = 0, total_lines: int = 0) -> dict:
    """Score a single parser's performance.

    Returns dict with:
        template_count: int
        parsing_time: float
        llm_calls: int
        lines_per_second: float
    """
    return {
        "template_count": template_count,
        "parsing_time": round(parsing_time, 3),
        "llm_calls": llm_calls,
        "lines_per_second": round(total_lines / parsing_time, 1) if parsing_time > 0 else 0,
    }


def compare_configs(traces: list[dict]) -> dict:
    """Compare results across different pipeline configurations.

    Args:
        traces: list of trace summaries, each with:
            config_name, accuracy, total_llm_calls, total_time, context_tokens

    Returns comparison report.
    """
    if not traces:
        return {"error": "no traces to compare"}

    report = {
        "configs_compared": len(traces),
        "results": [],
    }
    best_accuracy = 0
    best_config = ""

    for t in traces:
        name = t.get("config_name", "unknown")
        accuracy = t.get("accuracy", 0)
        result = {
            "config": name,
            "accuracy": accuracy,
            "llm_calls": t.get("total_llm_calls", 0),
            "total_time": t.get("total_time", 0),
            "context_tokens": t.get("context_tokens", 0),
        }
        report["results"].append(result)
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            best_config = name

    report["best_config"] = best_config
    report["best_accuracy"] = best_accuracy
    return report
