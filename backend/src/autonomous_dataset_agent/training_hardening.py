from __future__ import annotations

import os
import platform
import random
import sys
from dataclasses import replace
from importlib import metadata
from pathlib import Path
from typing import Any

from .contracts import (
    BenchmarkConfig,
    ClassPlanEntry,
    DatasetBuildResult,
    EvaluationReport,
    IterationDecision,
    PromotionGateConfig,
    RuntimeProfileConfig,
)
from .governance import stable_checksum
from .utils import read_json


CORE_DEPENDENCIES = ("Pillow", "fastapi", "uvicorn", "ultralytics")


def apply_runtime_profile(profile: RuntimeProfileConfig) -> None:
    os.environ["PYTHONHASHSEED"] = str(profile.seed)
    random.seed(profile.seed)

    try:
        import numpy  # type: ignore

        numpy.random.seed(profile.seed)
    except Exception:
        pass

    try:
        import torch  # type: ignore

        torch.manual_seed(profile.seed)
        if hasattr(torch, "cuda"):
            torch.cuda.manual_seed_all(profile.seed)
        if profile.deterministic and hasattr(torch, "use_deterministic_algorithms"):
            torch.use_deterministic_algorithms(True, warn_only=True)
    except Exception:
        pass


def build_runtime_profile(
    profile: RuntimeProfileConfig,
    *,
    training_config: dict[str, object],
    evaluation_config: dict[str, object],
) -> dict[str, object]:
    dependency_versions = {name: _dependency_version(name) for name in CORE_DEPENDENCIES}
    dependency_pins = dict(sorted(profile.dependency_pins.items())) or {
        "Pillow": ">=10.0.0",
        "fastapi": ">=0.115.0",
        "uvicorn": ">=0.30.0",
        "ultralytics": ">=8.3.0",
    }
    payload = {
        "schema_version": 1,
        "seed": profile.seed,
        "deterministic": profile.deterministic,
        "python_hash_seed": str(profile.seed),
        "runtime": {
            "python_version": platform.python_version(),
            "python_executable": Path(sys.executable).name,
            "platform": platform.platform(),
        },
        "dependencies": {
            "declared_pins": dependency_pins,
            "installed_versions": dependency_versions,
        },
        "container_baseline": {
            "image": profile.container_image,
            "digest": profile.container_digest,
            "execution_baseline": profile.execution_baseline,
        },
        "training_config": training_config,
        "evaluation_config": evaluation_config,
    }
    payload["profile_id"] = f"runtime_{stable_checksum(payload)[:16]}"
    return payload


def build_benchmark_suite(
    report: EvaluationReport,
    dataset_result: DatasetBuildResult,
    benchmark: BenchmarkConfig,
    gate: PromotionGateConfig,
) -> dict[str, object]:
    if not benchmark.enabled:
        return {"schema_version": 1, "status": "disabled", "scenarios": [], "summary": {"failed": 0, "passed": 0}}
    if report.status != "completed":
        return {
            "schema_version": 1,
            "status": "not_applicable",
            "scenarios": [],
            "summary": {"failed": 0, "passed": 0, "not_applicable": 0},
            "notes": ["Benchmark suite did not run because evaluation metrics are unavailable."],
        }

    classes = _ordered_classes(dataset_result, report)
    scenarios = [
        _multi_class_scenario(report, classes, gate),
        _long_tail_scenario(report, dataset_result, classes, benchmark),
    ]
    summary = _scenario_summary(scenarios)
    return {
        "schema_version": 1,
        "status": "failed" if summary["failed"] else "passed",
        "scenarios": scenarios,
        "summary": summary,
    }


def check_benchmark_regression(
    report: EvaluationReport,
    benchmark: BenchmarkConfig,
) -> dict[str, object]:
    if not benchmark.enabled:
        return {"schema_version": 1, "status": "disabled", "available": False, "block_reasons": [], "comparisons": {}}
    if report.status != "completed":
        return {
            "schema_version": 1,
            "status": "not_applicable",
            "available": False,
            "block_reasons": [],
            "comparisons": {},
            "notes": ["Benchmark regression check did not run because evaluation metrics are unavailable."],
        }
    if benchmark.approved_snapshot_path is None:
        return {
            "schema_version": 1,
            "status": "not_applicable",
            "available": False,
            "block_reasons": [],
            "comparisons": {},
            "notes": ["No approved benchmark snapshot path was configured."],
        }
    if not benchmark.approved_snapshot_path.exists():
        return {
            "schema_version": 1,
            "status": "not_applicable",
            "available": False,
            "block_reasons": [],
            "comparisons": {},
            "notes": ["Configured approved benchmark snapshot does not exist."],
        }

    snapshot = read_json(benchmark.approved_snapshot_path)
    baseline = _snapshot_metrics(snapshot if isinstance(snapshot, dict) else {})
    current = {
        "map50": report.map50,
        "precision": report.precision,
        "recall": report.recall,
    }
    tolerances = {
        "map50": benchmark.max_map50_regression,
        "precision": benchmark.max_precision_regression,
        "recall": benchmark.max_recall_regression,
    }
    comparisons: dict[str, object] = {}
    block_reasons: list[str] = []
    for metric_name in ("map50", "precision", "recall"):
        current_value = _as_float(current.get(metric_name))
        baseline_value = _as_float(baseline.get(metric_name))
        delta = (
            round(current_value - baseline_value, 6)
            if current_value is not None and baseline_value is not None
            else None
        )
        blocked = delta is not None and delta < -tolerances[metric_name]
        comparisons[metric_name] = {
            "current": current_value,
            "approved_snapshot": baseline_value,
            "delta": delta,
            "max_allowed_regression": tolerances[metric_name],
            "status": "failed" if blocked else "passed",
        }
        if blocked:
            block_reasons.append(
                f"{metric_name} delta {delta:.3f} exceeds approved benchmark regression limit {-tolerances[metric_name]:.3f}."
            )

    return {
        "schema_version": 1,
        "status": "failed" if block_reasons else "passed",
        "available": True,
        "snapshot_path": str(benchmark.approved_snapshot_path),
        "block_reasons": block_reasons,
        "comparisons": comparisons,
    }


def build_promotion_gate(
    report: EvaluationReport,
    gate: PromotionGateConfig,
    benchmark_suite: dict[str, object],
    benchmark_regression: dict[str, object],
) -> dict[str, object]:
    if not gate.enabled:
        return {"schema_version": 1, "status": "disabled", "blocked": False, "block_reasons": [], "thresholds": {}}
    if report.status != "completed":
        return {
            "schema_version": 1,
            "status": "not_applicable",
            "blocked": False,
            "block_reasons": ["Promotion gate did not run because evaluation metrics are unavailable."],
            "thresholds": _gate_thresholds(gate),
        }

    block_reasons: list[str] = []
    _append_metric_threshold(block_reasons, "map50", report.map50, gate.min_map50)
    _append_metric_threshold(block_reasons, "precision", report.precision, gate.min_precision)
    _append_metric_threshold(block_reasons, "recall", report.recall, gate.min_recall)

    gate_classes = sorted(report.per_class_metrics) or [
        class_name for class_name, outcome in sorted(report.class_outcomes.items()) if outcome == "ready"
    ]
    for class_name in gate_classes:
        metrics = report.per_class_metrics.get(class_name, {})
        _append_metric_threshold(block_reasons, f"{class_name} ap", metrics.get("ap", metrics.get("map50")), gate.min_per_class_ap)
        _append_metric_threshold(block_reasons, f"{class_name} precision", metrics.get("precision"), gate.min_per_class_precision)
        _append_metric_threshold(block_reasons, f"{class_name} recall", metrics.get("recall"), gate.min_per_class_recall)

    if benchmark_suite.get("status") == "failed":
        block_reasons.append("Deterministic benchmark suite reported failed scenarios.")
    if gate.block_on_benchmark_regression and benchmark_regression.get("status") == "failed":
        block_reasons.extend(str(reason) for reason in benchmark_regression.get("block_reasons", []))

    return {
        "schema_version": 1,
        "status": "blocked" if block_reasons else "passed",
        "blocked": bool(block_reasons),
        "block_reasons": block_reasons,
        "thresholds": _gate_thresholds(gate),
        "benchmark_status": benchmark_suite.get("status"),
        "benchmark_regression_status": benchmark_regression.get("status"),
    }


def apply_promotion_gate_to_iteration(
    decision: IterationDecision,
    promotion_gate: dict[str, object],
) -> IterationDecision:
    if decision.action != "promote" or not promotion_gate.get("blocked"):
        return decision
    reasons = [
        *decision.reasons,
        "Promotion gate blocked promotion.",
        *(str(reason) for reason in promotion_gate.get("block_reasons", [])),
    ]
    policy_report = dict(decision.policy_report)
    policy_report["selected_action"] = "stop"
    policy_report["promotion_gate_status"] = promotion_gate.get("status")
    policy_report["promotion_gate_blocked"] = True
    policy_report["promotion_gate_reasons"] = promotion_gate.get("block_reasons", [])
    return replace(decision, action="stop", reasons=reasons, policy_report=policy_report)


def add_class_failure_diagnostics(
    report: EvaluationReport,
    class_plan: list[ClassPlanEntry],
    decision: IterationDecision,
    gate: PromotionGateConfig,
) -> EvaluationReport:
    diagnostics: dict[str, dict[str, object]] = {}
    plan_by_name = {entry.name: entry for entry in class_plan}
    failure_modes = {
        str(item.get("class_name")): item
        for item in decision.policy_report.get("failure_modes", [])
        if isinstance(item, dict) and item.get("class_name")
    }
    target_set = set(decision.target_classes)
    for class_name in sorted(report.class_outcomes):
        metrics = report.per_class_metrics.get(class_name, {})
        modes = list(failure_modes.get(class_name, {}).get("modes", []))
        recommended_action = decision.action if class_name in target_set or not target_set else "monitor"
        diagnostics[class_name] = {
            "status": "failing" if modes else "passing",
            "metrics": {
                "ap": _as_float(metrics.get("ap", metrics.get("map50", report.map50))),
                "precision": _as_float(metrics.get("precision", report.precision)),
                "recall": _as_float(metrics.get("recall", report.recall)),
            },
            "threshold_gaps": _threshold_gaps(metrics, report, gate),
            "failure_modes": modes,
            "iteration_action": recommended_action,
            "iteration_reasons": list(decision.reasons),
            "sample_state": plan_by_name.get(class_name).final_state if class_name in plan_by_name else report.class_outcomes.get(class_name),
        }
    return replace(report, class_failure_diagnostics=diagnostics)


def build_advanced_validation_summary(config: BenchmarkConfig, runtime_profile: RuntimeProfileConfig) -> dict[str, object]:
    return {
        "schema_version": 1,
        "repeated_seed_runs": {
            "enabled": config.repeated_seed_runs,
            "seeds": list(config.repeated_seed_values) if config.repeated_seed_runs else [],
            "status": "configured" if config.repeated_seed_runs else "disabled",
        },
        "cross_validation": {
            "enabled": config.cross_validation,
            "folds": config.cross_validation_folds if config.cross_validation else 0,
            "status": "configured" if config.cross_validation else "disabled",
        },
        "default_seed": runtime_profile.seed,
    }


def _dependency_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _multi_class_scenario(
    report: EvaluationReport,
    classes: list[str],
    gate: PromotionGateConfig,
) -> dict[str, object]:
    if len(classes) < 2:
        return {
            "name": "multi_class_thresholds",
            "status": "not_applicable",
            "classes": classes,
            "reasons": ["Multi-class benchmark requires at least two admitted classes."],
        }
    reasons: list[str] = []
    for class_name in classes:
        metrics = report.per_class_metrics.get(class_name, {})
        _append_metric_threshold(reasons, f"{class_name} ap", metrics.get("ap", metrics.get("map50")), gate.min_per_class_ap)
        _append_metric_threshold(reasons, f"{class_name} precision", metrics.get("precision"), gate.min_per_class_precision)
        _append_metric_threshold(reasons, f"{class_name} recall", metrics.get("recall"), gate.min_per_class_recall)
    return {
        "name": "multi_class_thresholds",
        "status": "failed" if reasons else "passed",
        "classes": classes,
        "reasons": reasons,
    }


def _long_tail_scenario(
    report: EvaluationReport,
    dataset_result: DatasetBuildResult,
    classes: list[str],
    benchmark: BenchmarkConfig,
) -> dict[str, object]:
    totals = {
        class_name: sum(int(counts.get(split, 0)) for split in ("train", "val", "test"))
        for class_name, counts in dataset_result.class_split_counts.items()
    }
    if not totals:
        return {
            "name": "long_tail_recall",
            "status": "not_applicable",
            "classes": classes,
            "reasons": ["No class split counts are available for long-tail stress checks."],
        }
    long_tail_class = sorted(totals.items(), key=lambda item: (item[1], item[0]))[0][0]
    recall = _as_float(report.per_class_metrics.get(long_tail_class, {}).get("recall", report.recall))
    failed = recall is None or recall < benchmark.long_tail_min_recall
    return {
        "name": "long_tail_recall",
        "status": "failed" if failed else "passed",
        "class_name": long_tail_class,
        "sample_count": totals[long_tail_class],
        "recall": recall,
        "threshold": benchmark.long_tail_min_recall,
        "reasons": [
            f"{long_tail_class} recall is unavailable or below long-tail threshold {benchmark.long_tail_min_recall:.3f}."
        ]
        if failed
        else [],
    }


def _scenario_summary(scenarios: list[dict[str, object]]) -> dict[str, int]:
    return {
        "passed": sum(1 for item in scenarios if item.get("status") == "passed"),
        "failed": sum(1 for item in scenarios if item.get("status") == "failed"),
        "not_applicable": sum(1 for item in scenarios if item.get("status") == "not_applicable"),
    }


def _ordered_classes(dataset_result: DatasetBuildResult, report: EvaluationReport) -> list[str]:
    classes = list(dataset_result.class_split_counts) or list(report.class_outcomes)
    return list(dict.fromkeys(str(item) for item in classes))


def _snapshot_metrics(snapshot: dict[str, Any]) -> dict[str, float | None]:
    if isinstance(snapshot.get("metrics"), dict):
        raw = snapshot["metrics"]
    elif isinstance(snapshot.get("overall"), dict):
        raw = snapshot["overall"]
    else:
        raw = snapshot
    return {
        "map50": _as_float(raw.get("map50", raw.get("mAP50")) if isinstance(raw, dict) else None),
        "precision": _as_float(raw.get("precision") if isinstance(raw, dict) else None),
        "recall": _as_float(raw.get("recall") if isinstance(raw, dict) else None),
    }


def _append_metric_threshold(reasons: list[str], name: str, value: object, threshold: float) -> None:
    metric_value = _as_float(value)
    if metric_value is None:
        reasons.append(f"{name} is unavailable; required minimum is {threshold:.3f}.")
    elif metric_value < threshold:
        reasons.append(f"{name} {metric_value:.3f} is below required minimum {threshold:.3f}.")


def _threshold_gaps(metrics: dict[str, float], report: EvaluationReport, gate: PromotionGateConfig) -> dict[str, float]:
    values = {
        "ap": _as_float(metrics.get("ap", metrics.get("map50", report.map50))),
        "precision": _as_float(metrics.get("precision", report.precision)),
        "recall": _as_float(metrics.get("recall", report.recall)),
    }
    thresholds = {
        "ap": gate.min_per_class_ap,
        "precision": gate.min_per_class_precision,
        "recall": gate.min_per_class_recall,
    }
    return {
        metric: round(float(value) - thresholds[metric], 6)
        for metric, value in values.items()
        if value is not None
    }


def _gate_thresholds(gate: PromotionGateConfig) -> dict[str, float]:
    return {
        "min_map50": gate.min_map50,
        "min_precision": gate.min_precision,
        "min_recall": gate.min_recall,
        "min_per_class_ap": gate.min_per_class_ap,
        "min_per_class_precision": gate.min_per_class_precision,
        "min_per_class_recall": gate.min_per_class_recall,
    }


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
