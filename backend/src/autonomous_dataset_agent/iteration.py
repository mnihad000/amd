from __future__ import annotations

from .contracts import ClassPlanEntry, EvaluationReport, IterationDecision


def decide_next_step(report: EvaluationReport, class_plan: list[ClassPlanEntry]) -> IterationDecision:
    weak_classes = [entry.name for entry in class_plan if entry.final_state != "ready"]
    low_confidence_classes = [
        entry.name
        for entry in class_plan
        if entry.avg_label_confidence is not None and entry.avg_label_confidence < 0.7
    ]

    if report.status == "skipped":
        if weak_classes:
            return IterationDecision(
                action="recollect",
                target_classes=weak_classes,
                reasons=["Training was skipped and some classes remain infeasible."],
            )
        return IterationDecision(action="accept", reasons=["Dataset pipeline completed without training."])

    if low_confidence_classes:
        return IterationDecision(
            action="relabel",
            target_classes=low_confidence_classes,
            reasons=["Low-confidence labels are the clearest current bottleneck."],
        )

    if report.map50 is not None and report.map50 < 0.75:
        return IterationDecision(
            action="recollect",
            target_classes=weak_classes or list(report.class_outcomes.keys()),
            reasons=["Detection quality is below the target threshold."],
        )

    return IterationDecision(action="accept", reasons=["Current run meets the default acceptance conditions."])
