from __future__ import annotations

from .contracts import ClassPlanEntry, EvaluationReport, TrainingResult


def evaluate_run(training_result: TrainingResult, class_plan: list[ClassPlanEntry]) -> EvaluationReport:
    class_outcomes = {entry.name: entry.final_state for entry in class_plan}
    weak_classes = [entry.name for entry in class_plan if entry.final_state != "ready"]

    if training_result.status != "completed":
        return EvaluationReport(
            status="skipped",
            weak_classes=weak_classes,
            class_outcomes=class_outcomes,
            notes=["Training did not run, so model metrics are unavailable."],
        )

    map50 = training_result.metrics.get("metrics/mAP50(B)")
    precision = training_result.metrics.get("metrics/precision(B)")
    recall = training_result.metrics.get("metrics/recall(B)")

    notes: list[str] = []
    if map50 is not None and map50 < 0.75:
        notes.append("mAP@50 is below the default target threshold.")
    if precision is not None and precision < 0.7:
        notes.append("Precision is below the default target threshold.")
    if recall is not None and recall < 0.7:
        notes.append("Recall is below the default target threshold.")

    return EvaluationReport(
        status="completed",
        map50=map50,
        precision=precision,
        recall=recall,
        weak_classes=weak_classes,
        class_outcomes=class_outcomes,
        notes=notes,
    )
