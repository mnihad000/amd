from __future__ import annotations

from typing import Any

from .contracts import ClassPlanEntry, EvaluationReport, IterationDecision, IterationPolicyConfig
from .iteration_policy import BudgetState, evaluate_iteration_policy


def decide_next_step(
    report: EvaluationReport,
    class_plan: list[ClassPlanEntry],
    policy_config: IterationPolicyConfig | None = None,
    *,
    budget_state: BudgetState | None = None,
    target_classes: list[str] | None = None,
    baseline: dict[str, Any] | None = None,
) -> IterationDecision:
    return evaluate_iteration_policy(
        report,
        class_plan,
        policy_config,
        budget_state=budget_state,
        target_classes=target_classes,
        baseline=baseline,
    )
