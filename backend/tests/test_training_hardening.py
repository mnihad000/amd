from __future__ import annotations

import base64
import json
import random
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
    BenchmarkConfig,
    BudgetLimits,
    ClassQualityConfig,
    CriticThresholds,
    DatasetBuildResult,
    EvaluationReport,
    PromotionGateConfig,
    RuntimeProfileConfig,
    SourceMix,
)
from autonomous_dataset_agent.orchestrator import PipelineRunner
from autonomous_dataset_agent.training_hardening import (
    apply_runtime_profile,
    build_benchmark_suite,
    build_promotion_gate,
    build_runtime_profile,
    check_benchmark_regression,
)
from autonomous_dataset_agent.utils import read_json, write_json


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9VE3M3UAAAAASUVORK5CYII="
)


class TrainingHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("backend_test_training_hardening_tmp")
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_seeded_runtime_profile_is_reproducible(self) -> None:
        profile = RuntimeProfileConfig(seed=123, dependency_pins={"fastapi": ">=0.115.0"})

        apply_runtime_profile(profile)
        first_values = [random.random() for _ in range(5)]
        first_profile = build_runtime_profile(profile, training_config={"enabled": False}, evaluation_config={})

        apply_runtime_profile(profile)
        second_values = [random.random() for _ in range(5)]
        second_profile = build_runtime_profile(profile, training_config={"enabled": False}, evaluation_config={})

        self.assertEqual(first_values, second_values)
        self.assertEqual(first_profile["profile_id"], second_profile["profile_id"])
        self.assertEqual(first_profile["seed"], 123)
        self.assertEqual(first_profile["container_baseline"]["image"], "python:3.11-slim")

    def test_promotion_gate_blocks_failing_metric_thresholds(self) -> None:
        report = self._report({"forklift": {"ap": 0.8, "precision": 0.8, "recall": 0.8}}, map50=0.6)
        gate = build_promotion_gate(
            report,
            PromotionGateConfig(min_map50=0.75),
            {"status": "passed"},
            {"status": "passed"},
        )

        self.assertEqual(gate["status"], "blocked")
        self.assertTrue(gate["blocked"])
        self.assertTrue(any("map50" in reason for reason in gate["block_reasons"]))

    def test_benchmark_regression_checker_blocks_degraded_models(self) -> None:
        snapshot_path = self.root / "approved_benchmark.json"
        write_json(snapshot_path, {"metrics": {"map50": 0.9, "precision": 0.85, "recall": 0.84}})
        report = self._report({"forklift": {"ap": 0.8, "precision": 0.8, "recall": 0.8}}, map50=0.82)

        regression = check_benchmark_regression(
            report,
            BenchmarkConfig(approved_snapshot_path=snapshot_path, max_map50_regression=0.02),
        )

        self.assertEqual(regression["status"], "failed")
        self.assertTrue(any("map50" in reason for reason in regression["block_reasons"]))

    def test_benchmark_suite_covers_multi_class_and_long_tail_scenarios(self) -> None:
        report = self._report(
            {
                "forklift": {"ap": 0.8, "precision": 0.8, "recall": 0.8},
                "pallet jack": {"ap": 0.8, "precision": 0.8, "recall": 0.5},
            },
            map50=0.8,
        )
        dataset = DatasetBuildResult(
            status="completed",
            class_split_counts={
                "forklift": {"train": 10, "val": 3, "test": 2},
                "pallet jack": {"train": 1, "val": 1, "test": 0},
            },
        )

        suite = build_benchmark_suite(
            report,
            dataset,
            BenchmarkConfig(long_tail_min_recall=0.65),
            PromotionGateConfig(),
        )

        self.assertEqual(suite["status"], "failed")
        scenario_names = {scenario["name"] for scenario in suite["scenarios"]}
        self.assertEqual(scenario_names, {"multi_class_thresholds", "long_tail_recall"})

    def test_evaluation_artifact_includes_actionable_class_failure_diagnostics(self) -> None:
        config = self._pipeline_config("diagnostics-run", ["forklift"])
        with patch(
            "autonomous_dataset_agent.orchestrator.evaluate_run",
            return_value=self._report({"forklift": {"ap": 0.5, "precision": 0.8, "recall": 0.8}}, map50=0.5),
        ):
            summary = PipelineRunner(config).run()

        evaluation = read_json(Path(summary.artifact_paths["evaluation_report"]))
        diagnostics = evaluation["class_failure_diagnostics"]["forklift"]
        self.assertEqual(diagnostics["iteration_action"], "rebalance")
        self.assertIn("ap_below_minimum", diagnostics["failure_modes"])
        self.assertLess(diagnostics["threshold_gaps"]["ap"], 0)

    def test_single_and_multi_class_flows_complete_when_thresholds_pass(self) -> None:
        single = self._pipeline_config("single-pass", ["forklift"])
        with patch(
            "autonomous_dataset_agent.orchestrator.evaluate_run",
            return_value=self._report({"forklift": {"ap": 0.82, "precision": 0.8, "recall": 0.8}}, map50=0.82),
        ):
            single_summary = PipelineRunner(single).run()

        multi = self._pipeline_config("multi-pass", ["forklift", "pallet jack"])
        with patch(
            "autonomous_dataset_agent.orchestrator.evaluate_run",
            return_value=self._report(
                {
                    "forklift": {"ap": 0.82, "precision": 0.8, "recall": 0.8},
                    "pallet jack": {"ap": 0.82, "precision": 0.8, "recall": 0.8},
                },
                map50=0.82,
            ),
        ):
            multi_summary = PipelineRunner(multi).run()

        self.assertEqual(single_summary.promotion_gate_summary["status"], "passed")
        self.assertEqual(multi_summary.promotion_gate_summary["status"], "passed")
        self.assertIn("runtime_profile", single_summary.artifact_paths)
        self.assertIn("benchmark_suite", multi_summary.artifact_paths)

    def test_legacy_runs_without_section_4_fields_remain_readable_via_api(self) -> None:
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
        self.assertIsNone(body["runtime_profile"])
        self.assertIsNone(body["promotion_gate"])
        self.assertIsNone(body["benchmark_summary"])

    def _pipeline_config(self, job_id: str, classes: list[str]) -> JobConfig:
        manifest_path = self._write_manifest(job_id, classes)
        return JobConfig(
            job_id=job_id,
            prompt=" and ".join(classes) + " in a warehouse",
            classes=classes,
            output_root=self.root / "artifacts",
            source=SourceConfig(source_mode="manifest", manifest_path=manifest_path),
            label=LabelConfig(provider="mock", api_key=None, gemini_model="gemini-2.0-flash"),
            training=TrainingConfig(enabled=False, model="yolov8n.pt", epochs=1, image_size=640),
            budgets=BudgetLimits(max_label_calls=20, max_accepted_samples=20),
            critic=CriticThresholds(min_quality_score=0.5, min_samples_to_label=1, min_samples_for_training=1),
            mix=SourceMix(web_target_ratio=1.0, video_target_ratio=0.0),
            class_quality=ClassQualityConfig(min_train_samples=1, min_val_samples=1),
        )

    def _write_manifest(self, job_id: str, classes: list[str]) -> Path:
        image_dir = self.root / job_id / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        sources = []
        for class_name in classes:
            class_slug = class_name.replace(" ", "_")
            for index in range(2):
                source_id = f"{class_slug}_{index}"
                image_path = image_dir / f"{source_id}.png"
                image_path.write_bytes(PNG_BYTES + source_id.encode("utf-8"))
                sources.append(
                    {
                        "id": source_id,
                        "source_type": "web_image",
                        "class_names": [class_name],
                        "title": source_id,
                        "local_path": str(image_path),
                        "license": self._valid_license(source_id),
                        "metadata": {
                            "blur_score": 0.9,
                            "visibility_score": 0.9,
                            "object_size_score": 0.9,
                            "mock_confidence": 0.95,
                        },
                    }
                )
        manifest_path = self.root / job_id / "source_manifest.json"
        manifest_path.write_text(json.dumps({"sources": sources}), encoding="utf-8")
        return manifest_path

    @staticmethod
    def _valid_license(source_id: str) -> dict[str, object]:
        return {
            "origin": f"unit-test:{source_id}",
            "license_type": "internal_trainable",
            "usage_rights": ["dataset_training", "model_training"],
            "expiration": "2999-01-01",
            "restrictions": [],
        }

    @staticmethod
    def _report(per_class_metrics: dict[str, dict[str, float]], *, map50: float) -> EvaluationReport:
        return EvaluationReport(
            status="completed",
            map50=map50,
            precision=0.8,
            recall=0.8,
            class_outcomes={class_name: "ready" for class_name in per_class_metrics},
            per_class_metrics=per_class_metrics,
        )


if __name__ == "__main__":
    unittest.main()
