from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ClassPlanEntry, EvaluationReport, IterationDecision, IterationPolicyConfig
from .utils import read_json


METRIC_KEYS = ("ap", "precision", "recall")
CHEAP_ACTIONS = {"relabel", "re-critic", "rebalance", "stop", "promote"}


@dataclass
class BudgetState:
    current_iteration: int
    elapsed_runtime_seconds: float
    label_calls_used: int
    max_iterations: int
    max_runtime_seconds: int
    max_label_calls: int


def evaluate_iteration_policy(
    report: EvaluationReport,
    class_plan: list[ClassPlanEntry],
    config: IterationPolicyConfig | None = None,
    *,
    budget_state: BudgetState | None = None,
    target_classes: list[str] | None = None,
    baseline: dict[str, Any] | None = None,
) -> IterationDecision:
    policy = config or IterationPolicyConfig()
    targets = _ordered_targets(target_classes, class_plan, report)
    critical_classes = _critical_classes(policy, targets)
    budget = budget_state or BudgetState(
        current_iteration=policy.current_iteration,
        elapsed_runtime_seconds=0.0,
        label_calls_used=0,
        max_iterations=policy.max_iterations,
        max_runtime_seconds=policy.max_runtime_seconds,
        max_label_calls=policy.max_label_calls,
    )
    budget_snapshot = _budget_snapshot(budget)
    current_metrics = _current_metrics(report, targets)
    baseline_comparison = compare_to_baseline(report, targets, current_metrics, baseline)
    promotion_guard = build_promotion_guard(policy, critical_classes, baseline_comparison)
    failure_modes = _failure_modes(report, class_plan, policy, targets, current_metrics, baseline_comparison)

    budget_stop_reasons = _hard_budget_stop_reasons(budget_snapshot)
    if budget_stop_reasons:
        reasons = [*budget_stop_reasons, "No further iteration action is compliant with the hard budget caps."]
        return _decision(
            "stop",
            targets,
            reasons,
            promotion_guard.get("warnings", []),
            budget_snapshot,
            promotion_guard,
            baseline_comparison,
            failure_modes,
            critical_classes,
        )

    candidate_action, candidate_targets, candidate_reasons = _select_candidate_action(
        report,
        policy,
        targets,
        current_metrics,
        baseline_comparison,
        promotion_guard,
        failure_modes,
    )
    action, reasons = _apply_budget_degrade(candidate_action, candidate_reasons, budget_snapshot, failure_modes)

    if action == "stop" and not reasons:
        reasons = ["No deterministic policy rule found a compliant next action."]

    return _decision(
        action,
        candidate_targets if action not in {"promote", "stop"} else targets,
        reasons,
        promotion_guard.get("warnings", []),
        budget_snapshot,
        promotion_guard,
        baseline_comparison,
        failure_modes,
        critical_classes,
    )


def compare_to_baseline(
    report: EvaluationReport,
    target_classes: list[str],
    current_metrics: dict[str, dict[str, float | None]],
    baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    if not baseline:
        return {
            "available": False,
            "baseline_job_id": None,
            "target_classes": target_classes,
            "class_deltas": {},
            "overall": {
                "current_map50": report.map50,
                "baseline_map50": None,
                "map50_delta": None,
            },
            "notes": ["No promoted baseline metrics were found for this class context."],
        }

    baseline_metrics = baseline.get("per_class_metrics") if isinstance(baseline.get("per_class_metrics"), dict) else {}
    baseline_global = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else {}
    class_deltas: dict[str, Any] = {}

    for class_name in target_classes:
        current = current_metrics.get(class_name, {})
        raw_baseline_class = baseline_metrics.get(class_name, {}) if isinstance(baseline_metrics, dict) else {}
        baseline_class = {
            metric: _coerce_float(raw_baseline_class.get(metric) if isinstance(raw_baseline_class, dict) else None)
            for metric in METRIC_KEYS
        }
        if all(value is None for value in baseline_class.values()):
            baseline_class = {
                "ap": _coerce_float(baseline_global.get("map50")),
                "precision": _coerce_float(baseline_global.get("precision")),
                "recall": _coerce_float(baseline_global.get("recall")),
            }

        deltas = {
            metric: (
                round(float(current[metric]) - float(baseline_class[metric]), 6)
                if current.get(metric) is not None and baseline_class.get(metric) is not None
                else None
            )
            for metric in METRIC_KEYS
        }
        class_deltas[class_name] = {
            "current": current,
            "baseline": baseline_class,
            "delta": deltas,
        }

    baseline_map50 = _coerce_float(baseline_global.get("map50"))
    map50_delta = (
        round(float(report.map50) - baseline_map50, 6)
        if report.map50 is not None and baseline_map50 is not None
        else None
    )
    return {
        "available": True,
        "baseline_job_id": baseline.get("job_id"),
        "target_classes": target_classes,
        "class_deltas": class_deltas,
        "overall": {
            "current_map50": report.map50,
            "baseline_map50": baseline_map50,
            "map50_delta": map50_delta,
        },
        "notes": [],
    }


def build_promotion_guard(
    config: IterationPolicyConfig,
    critical_classes: list[str],
    baseline_comparison: dict[str, Any],
) -> dict[str, Any]:
    if not baseline_comparison.get("available"):
        return {
            "status": "not_applicable",
            "blocked": False,
            "critical_classes": critical_classes,
            "block_reasons": [],
            "warnings": [],
        }

    critical_set = set(critical_classes)
    block_reasons: list[str] = []
    warnings: list[str] = []
    class_deltas = baseline_comparison.get("class_deltas", {})
    if not isinstance(class_deltas, dict):
        class_deltas = {}

    for class_name in sorted(class_deltas):
        item = class_deltas[class_name]
        if not isinstance(item, dict):
            continue
        delta = item.get("delta", {})
        if not isinstance(delta, dict):
            continue
        for metric in METRIC_KEYS:
            value = _coerce_float(delta.get(metric))
            if value is None:
                continue
            tolerance = _delta_tolerance(config, class_name, metric)
            if value < -tolerance:
                message = (
                    f"{class_name} {metric} delta {value:.3f} is below allowed regression "
                    f"tolerance {-tolerance:.3f}."
                )
                if class_name in critical_set:
                    block_reasons.append(message)
                else:
                    warnings.append(message)

    if block_reasons:
        status = "blocked"
    elif warnings:
        status = "warning"
    else:
        status = "passed"
    return {
        "status": status,
        "blocked": bool(block_reasons),
        "critical_classes": critical_classes,
        "block_reasons": block_reasons,
        "warnings": warnings,
    }


def load_last_promoted_baseline(
    output_root: Path,
    *,
    current_job_id: str,
    target_classes: list[str],
) -> dict[str, Any] | None:
    if not output_root.exists():
        return None

    target_set = set(target_classes)
    candidates: list[tuple[float, dict[str, Any]]] = []
    for summary_path in output_root.glob("*/reports/run_summary.json"):
        if summary_path.parent.parent.name == current_job_id:
            continue
        try:
            summary = read_json(summary_path)
        except Exception:
            continue
        if not isinstance(summary, dict):
            continue
        policy = summary.get("iteration_policy")
        if not isinstance(policy, dict) or policy.get("selected_action") != "promote":
            continue
        admitted = summary.get("admitted_classes")
        requested = summary.get("requested_classes")
        class_context = admitted if isinstance(admitted, list) and admitted else requested
        class_set = {str(item) for item in class_context} if isinstance(class_context, list) else set()
        if target_set and not target_set.issubset(class_set):
            continue
        evaluation_path = summary_path.parent / "evaluation_report.json"
        evaluation = _load_evaluation_payload(evaluation_path)
        candidates.append(
            (
                summary_path.stat().st_mtime,
                {
                    "job_id": str(summary.get("job_id", summary_path.parent.parent.name)),
                    "metrics": _overall_metrics(evaluation),
                    "per_class_metrics": _per_class_metrics_from_payload(evaluation, target_classes),
                },
            )
        )

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _decision(
    action: str,
    target_classes: list[str],
    reasons: list[str],
    warnings: list[str],
    budget_snapshot: dict[str, object],
    promotion_guard: dict[str, Any],
    baseline_comparison: dict[str, Any],
    failure_modes: list[dict[str, Any]],
    critical_classes: list[str],
) -> IterationDecision:
    policy_report = {
        "selected_action": action,
        "target_classes": target_classes,
        "critical_classes": critical_classes,
        "reasons": reasons,
        "warnings": warnings,
        "failure_modes": failure_modes,
        "budget_snapshot": budget_snapshot,
        "regression_gate_status": promotion_guard.get("status", "not_evaluated"),
        "baseline_available": bool(baseline_comparison.get("available")),
    }
    return IterationDecision(
        action=action,
        target_classes=target_classes,
        reasons=reasons,
        warnings=warnings,
        budget_snapshot=budget_snapshot,
        regression_gate_status=str(promotion_guard.get("status", "not_evaluated")),
        policy_report=policy_report,
        baseline_comparison=baseline_comparison,
        promotion_guard=promotion_guard,
    )


def _select_candidate_action(
    report: EvaluationReport,
    policy: IterationPolicyConfig,
    targets: list[str],
    current_metrics: dict[str, dict[str, float | None]],
    baseline_comparison: dict[str, Any],
    promotion_guard: dict[str, Any],
    failure_modes: list[dict[str, Any]],
) -> tuple[str, list[str], list[str]]:
    if report.status == "skipped":
        return "re-ingest", targets, ["Training was skipped, so more usable data is required before promotion."]

    failing = _failing_classes(failure_modes)
    if _quality_sufficient(policy, targets, current_metrics):
        if promotion_guard.get("blocked"):
            return "stop", targets, [*promotion_guard.get("block_reasons", []), "Promotion is blocked by critical-class regression."]
        gain = baseline_comparison.get("overall", {}).get("map50_delta")
        if gain is None or gain >= policy.min_promote_map50_gain or not baseline_comparison.get("available"):
            return "promote", targets, ["Current metrics satisfy policy thresholds and promotion guard checks."]
        return "stop", targets, [
            f"Quality thresholds pass, but mAP@50 gain {gain:.3f} is below promotion threshold "
            f"{policy.min_promote_map50_gain:.3f}."
        ]

    for mode_name, action in (
        ("label_quality_weakness", "relabel"),
        ("precision_below_minimum", "relabel"),
        ("precision_regression", "relabel"),
        ("sample_scarcity", "re-ingest"),
        ("recall_below_minimum", "re-ingest"),
        ("recall_regression", "re-ingest"),
        ("ap_below_minimum", "rebalance"),
        ("ap_regression", "rebalance"),
    ):
        affected = [item["class_name"] for item in failure_modes if mode_name in item.get("modes", [])]
        if affected:
            return action, affected, [_action_reason(mode_name, action, affected)]

    if failing:
        return "retrain", failing, ["Metrics are weak without a more specific upstream data failure mode."]
    return "stop", targets, ["No failing classes were identified, but promotion thresholds were not satisfied."]


def _apply_budget_degrade(
    action: str,
    reasons: list[str],
    budget_snapshot: dict[str, object],
    failure_modes: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    exhausted = set(_string_list(budget_snapshot.get("exhausted_caps")))
    near = set(_string_list(budget_snapshot.get("near_limits")))
    if action == "relabel" and "label_calls" in exhausted:
        return "re-critic", [*reasons, "Label-call budget is exhausted, so policy degrades relabel to re-critic."]
    if action in {"re-ingest", "retrain"} and near:
        has_scarcity = any("sample_scarcity" in item.get("modes", []) for item in failure_modes)
        if not has_scarcity:
            return "rebalance", [*reasons, "Budget is near a hard cap, so policy selects cheaper rebalance."]
    if action not in CHEAP_ACTIONS and exhausted:
        return "stop", [*reasons, "Selected action would violate exhausted policy budget caps."]
    return action, reasons


def _failure_modes(
    report: EvaluationReport,
    class_plan: list[ClassPlanEntry],
    policy: IterationPolicyConfig,
    targets: list[str],
    current_metrics: dict[str, dict[str, float | None]],
    baseline_comparison: dict[str, Any],
) -> list[dict[str, Any]]:
    plan_by_name = {entry.name: entry for entry in class_plan}
    class_deltas = baseline_comparison.get("class_deltas", {})
    if not isinstance(class_deltas, dict):
        class_deltas = {}
    results: list[dict[str, Any]] = []
    for class_name in targets:
        modes: list[str] = []
        metrics = current_metrics.get(class_name, {})
        if _metric_below(policy, class_name, "ap", metrics.get("ap")):
            modes.append("ap_below_minimum")
        if _metric_below(policy, class_name, "precision", metrics.get("precision")):
            modes.append("precision_below_minimum")
        if _metric_below(policy, class_name, "recall", metrics.get("recall")):
            modes.append("recall_below_minimum")

        plan_entry = plan_by_name.get(class_name)
        if plan_entry is not None:
            if plan_entry.final_state != "ready":
                modes.append("sample_scarcity")
            if plan_entry.avg_label_confidence is not None and plan_entry.avg_label_confidence < policy.min_precision:
                modes.append("label_quality_weakness")

        delta = class_deltas.get(class_name, {}).get("delta", {}) if isinstance(class_deltas.get(class_name), dict) else {}
        if isinstance(delta, dict):
            for metric in METRIC_KEYS:
                value = _coerce_float(delta.get(metric))
                if value is not None and value < -_delta_tolerance(policy, class_name, metric):
                    modes.append(f"{metric}_regression")

        if modes:
            results.append(
                {
                    "class_name": class_name,
                    "modes": sorted(set(modes)),
                    "metrics": metrics,
                }
            )
    return results


def _budget_snapshot(budget: BudgetState) -> dict[str, object]:
    runtime_remaining = budget.max_runtime_seconds - budget.elapsed_runtime_seconds
    iteration_remaining = budget.max_iterations - budget.current_iteration
    label_remaining = budget.max_label_calls - budget.label_calls_used
    exhausted: list[str] = []
    if runtime_remaining <= 0:
        exhausted.append("runtime")
    if iteration_remaining <= 0:
        exhausted.append("iterations")
    if label_remaining <= 0:
        exhausted.append("label_calls")

    near_limits: list[str] = []
    if runtime_remaining > 0 and runtime_remaining <= max(1, budget.max_runtime_seconds * 0.2):
        near_limits.append("runtime")
    if iteration_remaining == 1:
        near_limits.append("iterations")
    if label_remaining > 0 and label_remaining <= max(1, budget.max_label_calls * 0.2):
        near_limits.append("label_calls")

    return {
        "current_iteration": budget.current_iteration,
        "max_iterations": budget.max_iterations,
        "elapsed_runtime_seconds": round(budget.elapsed_runtime_seconds, 3),
        "max_runtime_seconds": budget.max_runtime_seconds,
        "label_calls_used": budget.label_calls_used,
        "max_label_calls": budget.max_label_calls,
        "remaining_iterations": max(0, iteration_remaining),
        "remaining_runtime_seconds": max(0.0, round(runtime_remaining, 3)),
        "remaining_label_calls": max(0, label_remaining),
        "exhausted_caps": exhausted,
        "near_limits": near_limits,
    }


def _hard_budget_stop_reasons(snapshot: dict[str, object]) -> list[str]:
    exhausted = set(_string_list(snapshot.get("exhausted_caps")))
    reasons: list[str] = []
    if "runtime" in exhausted:
        reasons.append("Runtime policy cap is exhausted.")
    if "iterations" in exhausted:
        reasons.append("Iteration policy cap is exhausted.")
    if "label_calls" in exhausted:
        reasons.append("Label-call policy cap is exhausted.")
    return reasons


def _ordered_targets(
    target_classes: list[str] | None,
    class_plan: list[ClassPlanEntry],
    report: EvaluationReport,
) -> list[str]:
    raw = target_classes or [entry.name for entry in class_plan] or list(report.class_outcomes)
    return list(dict.fromkeys(str(item).strip().lower() for item in raw if str(item).strip()))


def _critical_classes(policy: IterationPolicyConfig, targets: list[str]) -> list[str]:
    configured = [item.strip().lower() for item in policy.critical_classes if item.strip()]
    return list(dict.fromkeys(configured or targets))


def _current_metrics(report: EvaluationReport, targets: list[str]) -> dict[str, dict[str, float | None]]:
    metrics: dict[str, dict[str, float | None]] = {}
    for class_name in targets:
        raw_class_metrics = report.per_class_metrics.get(class_name, {})
        metrics[class_name] = {
            "ap": _coerce_float(raw_class_metrics.get("ap", raw_class_metrics.get("map50"))) if raw_class_metrics else report.map50,
            "precision": _coerce_float(raw_class_metrics.get("precision")) if raw_class_metrics else report.precision,
            "recall": _coerce_float(raw_class_metrics.get("recall")) if raw_class_metrics else report.recall,
        }
    return metrics


def _quality_sufficient(
    policy: IterationPolicyConfig,
    targets: list[str],
    current_metrics: dict[str, dict[str, float | None]],
) -> bool:
    for class_name in targets:
        metrics = current_metrics.get(class_name, {})
        for metric in METRIC_KEYS:
            value = metrics.get(metric)
            if value is None or _metric_below(policy, class_name, metric, value):
                return False
    return True


def _metric_below(policy: IterationPolicyConfig, class_name: str, metric: str, value: float | None) -> bool:
    if value is None:
        return True
    return float(value) < _minimum(policy, class_name, metric)


def _minimum(policy: IterationPolicyConfig, class_name: str, metric: str) -> float:
    class_minimums = policy.per_class_minimums.get(class_name, {})
    if metric in class_minimums:
        return float(class_minimums[metric])
    if metric == "ap":
        return policy.min_ap
    if metric == "precision":
        return policy.min_precision
    return policy.min_recall


def _delta_tolerance(policy: IterationPolicyConfig, class_name: str, metric: str) -> float:
    class_tolerances = policy.per_class_delta_tolerances.get(class_name, {})
    if metric in class_tolerances:
        return float(class_tolerances[metric])
    if metric == "ap":
        return policy.max_negative_ap_delta
    if metric == "precision":
        return policy.max_negative_precision_delta
    return policy.max_negative_recall_delta


def _action_reason(mode_name: str, action: str, affected: list[str]) -> str:
    class_list = ", ".join(affected)
    return f"{mode_name.replace('_', ' ')} detected for {class_list}; selected {action} by fixed policy order."


def _failing_classes(failure_modes: list[dict[str, Any]]) -> list[str]:
    return [str(item["class_name"]) for item in failure_modes if item.get("class_name")]


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _load_evaluation_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _overall_metrics(payload: dict[str, Any]) -> dict[str, float | None]:
    return {
        "map50": _coerce_float(payload.get("map50")),
        "precision": _coerce_float(payload.get("precision")),
        "recall": _coerce_float(payload.get("recall")),
    }


def _per_class_metrics_from_payload(payload: dict[str, Any], target_classes: list[str]) -> dict[str, dict[str, float | None]]:
    raw = payload.get("per_class_metrics")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, float | None]] = {}
    for class_name in target_classes:
        item = raw.get(class_name)
        if not isinstance(item, dict):
            continue
        result[class_name] = {
            "ap": _coerce_float(item.get("ap", item.get("map50"))),
            "precision": _coerce_float(item.get("precision")),
            "recall": _coerce_float(item.get("recall")),
        }
    return result
