from __future__ import annotations

import base64
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from autonomous_dataset_agent.api import create_app
from autonomous_dataset_agent.config import JobConfig, LabelConfig, SourceConfig, TrainingConfig
from autonomous_dataset_agent.contracts import (
    BudgetLimits,
    ClassPlanEntry,
    CriticThresholds,
    EvaluationReport,
    IterationPolicyConfig,
    SampleRecord,
    SourceMix,
    TrainingResult,
)
from autonomous_dataset_agent.iteration_policy import BudgetState, evaluate_iteration_policy
from autonomous_dataset_agent.orchestrator import PipelineRunner
from autonomous_dataset_agent.utils import write_json


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9VE3M3UAAAAASUVORK5CYII="
)


class IterationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("backend_test_iteration_tmp")
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_deterministic_ordering_returns_same_decision(self) -> None:
        report = self._report({"forklift": {"ap": 0.6, "precision": 0.8, "recall": 0.8}})
        plan = [self._plan("forklift")]

        first = evaluate_iteration_policy(report, plan)
        second = evaluate_iteration_policy(report, plan)

        self.assertEqual(first.action, second.action)
        self.assertEqual(first.target_classes, second.target_classes)
        self.assertEqual(first.reasons, second.reasons)
        self.assertEqual(first.policy_report, second.policy_report)

    def test_failure_mode_mapping_selects_expected_actions(self) -> None:
        plan = [self._plan("forklift")]

        precision = evaluate_iteration_policy(
            self._report({"forklift": {"ap": 0.8, "precision": 0.5, "recall": 0.8}}),
            plan,
        )
        recall = evaluate_iteration_policy(
            self._report({"forklift": {"ap": 0.8, "precision": 0.8, "recall": 0.5}}),
            plan,
        )
        low_ap = evaluate_iteration_policy(
            self._report({"forklift": {"ap": 0.5, "precision": 0.8, "recall": 0.8}}),
            plan,
        )

        self.assertEqual(precision.action, "relabel")
        self.assertEqual(recall.action, "re-ingest")
        self.assertEqual(low_ap.action, "rebalance")

    def test_critical_class_regression_blocks_promote(self) -> None:
        report = self._report({"forklift": {"ap": 0.82, "precision": 0.82, "recall": 0.82}}, map50=0.82)
        baseline = {
            "job_id": "baseline",
            "metrics": {"map50": 0.8, "precision": 0.8, "recall": 0.8},
            "per_class_metrics": {"forklift": {"ap": 0.9, "precision": 0.82, "recall": 0.82}},
        }

        decision = evaluate_iteration_policy(
            report,
            [self._plan("forklift")],
            IterationPolicyConfig(critical_classes=["forklift"]),
            baseline=baseline,
        )

        self.assertEqual(decision.action, "stop")
        self.assertEqual(decision.regression_gate_status, "blocked")
        self.assertTrue(decision.promotion_guard["blocked"])

    def test_non_critical_regression_warns_only(self) -> None:
        report = self._report(
            {
                "forklift": {"ap": 0.82, "precision": 0.82, "recall": 0.82},
                "pallet jack": {"ap": 0.82, "precision": 0.82, "recall": 0.82},
            },
            map50=0.82,
        )
        baseline = {
            "job_id": "baseline",
            "metrics": {"map50": 0.8, "precision": 0.8, "recall": 0.8},
            "per_class_metrics": {
                "forklift": {"ap": 0.82, "precision": 0.82, "recall": 0.82},
                "pallet jack": {"ap": 0.9, "precision": 0.82, "recall": 0.82},
            },
        }

        decision = evaluate_iteration_policy(
            report,
            [self._plan("forklift"), self._plan("pallet jack")],
            IterationPolicyConfig(critical_classes=["forklift"]),
            baseline=baseline,
        )

        self.assertEqual(decision.action, "promote")
        self.assertEqual(decision.regression_gate_status, "warning")
        self.assertFalse(decision.promotion_guard["blocked"])
        self.assertTrue(decision.warnings)

    def test_budget_cap_forces_stop(self) -> None:
        decision = evaluate_iteration_policy(
            self._report({"forklift": {"ap": 0.5, "precision": 0.8, "recall": 0.8}}),
            [self._plan("forklift")],
            IterationPolicyConfig(max_iterations=2),
            budget_state=BudgetState(
                current_iteration=2,
                elapsed_runtime_seconds=1,
                label_calls_used=0,
                max_iterations=2,
                max_runtime_seconds=100,
                max_label_calls=10,
            ),
        )

        self.assertEqual(decision.action, "stop")
        self.assertIn("iterations", decision.budget_snapshot["exhausted_caps"])

    def test_weak_per_class_ap_triggers_targeted_action(self) -> None:
        decision = evaluate_iteration_policy(
            self._report(
                {
                    "forklift": {"ap": 0.5, "precision": 0.8, "recall": 0.8},
                    "pallet jack": {"ap": 0.8, "precision": 0.8, "recall": 0.8},
                }
            ),
            [self._plan("forklift"), self._plan("pallet jack")],
        )

        self.assertEqual(decision.action, "rebalance")
        self.assertEqual(decision.target_classes, ["forklift"])

    def test_pipeline_writes_no_baseline_policy_artifacts(self) -> None:
        config = self._pipeline_config("no-baseline")

        with patch(
            "autonomous_dataset_agent.orchestrator.evaluate_run",
            return_value=self._report({"forklift": {"ap": 0.5, "precision": 0.8, "recall": 0.8}}),
        ):
            summary = PipelineRunner(config).run()

        self.assertIn(summary.iteration_policy["selected_action"], {"re-ingest", "rebalance"})
        self.assertFalse(summary.baseline_comparison_summary["available"])
        for artifact_name in ("iteration_policy_report", "baseline_comparison", "promotion_guard"):
            self.assertTrue(Path(summary.artifact_paths[artifact_name]).exists())

    def test_pipeline_blocks_critical_baseline_regression(self) -> None:
        self._write_promoted_baseline()
        config = self._pipeline_config("critical-regression")
        config.iteration_policy.critical_classes = ["forklift"]

        with patch(
            "autonomous_dataset_agent.orchestrator.evaluate_run",
            return_value=self._report({"forklift": {"ap": 0.82, "precision": 0.82, "recall": 0.82}}, map50=0.82),
        ):
            summary = PipelineRunner(config).run()

        self.assertEqual(summary.iteration_policy["selected_action"], "stop")
        self.assertEqual(summary.promotion_guard_summary["status"], "blocked")

    def test_label_call_budget_exhaustion_stops_with_explicit_reason(self) -> None:
        decision = evaluate_iteration_policy(
            self._report({"forklift": {"ap": 0.5, "precision": 0.8, "recall": 0.8}}),
            [self._plan("forklift")],
            budget_state=BudgetState(
                current_iteration=1,
                elapsed_runtime_seconds=1,
                label_calls_used=10,
                max_iterations=3,
                max_runtime_seconds=100,
                max_label_calls=10,
            ),
        )

        self.assertEqual(decision.action, "stop")
        self.assertIn("label_calls", decision.budget_snapshot["exhausted_caps"])

    def test_old_run_summary_remains_readable_via_api(self) -> None:
        artifacts_root = self.root / "artifacts"
        summary_path = artifacts_root / "old-run" / "reports" / "run_summary.json"
        write_json(
            summary_path,
            {
                "job_id": "old-run",
                "prompt": "old run",
                "requested_classes": ["forklift"],
                "admitted_classes": ["forklift"],
                "deferred_classes": [],
                "blocked_classes": [],
                "source_breakdown": {},
                "budgets": {},
                "notes": [],
                "artifact_paths": {"run_summary": str(summary_path)},
            },
        )
        app = create_app(artifacts_root=artifacts_root, index_path=artifacts_root / "run_index.json")

        with TestClient(app) as client:
            response = client.get("/runs/old-run")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertIsNone(body["iteration_policy"])
        self.assertIsNone(body["baseline_comparison"])
        self.assertIsNone(body["promotion_guard"])

    @staticmethod
    def _plan(class_name: str) -> ClassPlanEntry:
        return ClassPlanEntry(
            name=class_name,
            initial_state="ready",
            final_state="ready",
            feasibility_score=1.0,
            accepted_samples=4,
            avg_label_confidence=0.9,
        )

    @staticmethod
    def _report(per_class_metrics: dict[str, dict[str, float]], *, map50: float = 0.8) -> EvaluationReport:
        return EvaluationReport(
            status="completed",
            map50=map50,
            precision=0.8,
            recall=0.8,
            class_outcomes={class_name: "ready" for class_name in per_class_metrics},
            per_class_metrics=per_class_metrics,
        )

    def _pipeline_config(self, job_id: str) -> JobConfig:
        image_dir = self.root / job_id / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / "forklift.png"
        image_path.write_bytes(PNG_BYTES + job_id.encode("utf-8"))
        manifest_path = self.root / job_id / "source_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "id": "forklift_a",
                            "source_type": "web_image",
                            "class_names": ["forklift"],
                            "title": "forklift a",
                            "local_path": str(image_path),
                            "license": {
                                "origin": "unit-test:forklift_a",
                                "license_type": "internal_trainable",
                                "usage_rights": ["dataset_training", "model_training"],
                                "expiration": "2999-01-01",
                                "restrictions": [],
                            },
                            "metadata": {"blur_score": 0.9, "visibility_score": 0.85, "object_size_score": 0.8},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return JobConfig(
            job_id=job_id,
            prompt="forklift in a warehouse",
            classes=["forklift"],
            output_root=self.root / "artifacts",
            source=SourceConfig(source_mode="manifest", manifest_path=manifest_path),
            label=LabelConfig(provider="mock", api_key=None, gemini_model="gemini-2.0-flash"),
            training=TrainingConfig(enabled=False, model="yolov8n.pt", epochs=1, image_size=640),
            budgets=BudgetLimits(max_label_calls=10, max_accepted_samples=5),
            critic=CriticThresholds(min_quality_score=0.5, min_samples_to_label=1, min_samples_for_training=1),
            mix=SourceMix(),
        )

    def _write_promoted_baseline(self) -> None:
        report_dir = self.root / "artifacts" / "baseline-run" / "reports"
        write_json(
            report_dir / "run_summary.json",
            {
                "job_id": "baseline-run",
                "requested_classes": ["forklift"],
                "admitted_classes": ["forklift"],
                "iteration_policy": {"selected_action": "promote"},
            },
        )
        write_json(
            report_dir / "evaluation_report.json",
            {
                "status": "completed",
                "map50": 0.8,
                "precision": 0.8,
                "recall": 0.8,
                "per_class_metrics": {"forklift": {"ap": 0.9, "precision": 0.82, "recall": 0.82}},
            },
        )


if __name__ == "__main__":
    unittest.main()
