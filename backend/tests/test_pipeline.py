from __future__ import annotations

import base64
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autonomous_dataset_agent.class_planner import build_initial_class_plan, finalize_class_plan
from autonomous_dataset_agent.config import JobConfig, LabelConfig, SourceConfig, TrainingConfig
from autonomous_dataset_agent.contracts import BudgetLimits, ClassQualityConfig, CriticThresholds, LabelBox, LabelRecord, SampleRecord, SourceMix
from autonomous_dataset_agent.orchestrator import PipelineRunner
from autonomous_dataset_agent.run_lifecycle import PIPELINE_STAGES, PipelineRunContext
from autonomous_dataset_agent.utils import read_json


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9VE3M3UAAAAASUVORK5CYII="
)


class PipelineTests(unittest.TestCase):
    def test_initial_class_plan_marks_generic_classes_as_risky(self) -> None:
        plan = build_initial_class_plan("forklift in a warehouse", ["forklift", "object"])
        states = {entry.name: entry.initial_state for entry in plan}
        self.assertEqual(states["forklift"], "ready")
        self.assertEqual(states["object"], "risky")

    def test_finalize_class_plan_blocks_classes_without_samples(self) -> None:
        plan = build_initial_class_plan("forklift", ["forklift", "ghost"])
        samples = [
            SampleRecord(
                id="forklift_1",
                source_id="forklift_1",
                source_type="web_image",
                class_names=["forklift"],
                path="sample.png",
            )
        ]
        labels = [
            LabelRecord(
                sample_id="forklift_1",
                provider="mock",
                status="validated",
                boxes=[
                    LabelBox(
                        class_name="forklift",
                        class_id=0,
                        x_center=0.5,
                        y_center=0.5,
                        width=0.4,
                        height=0.4,
                        confidence=0.9,
                    )
                ],
            )
        ]
        finalized = finalize_class_plan(
            plan,
            samples,
            labels,
            CriticThresholds(min_samples_to_label=1, min_samples_for_training=1),
        )
        states = {entry.name: entry.final_state for entry in finalized}
        self.assertEqual(states["forklift"], "ready")
        self.assertEqual(states["ghost"], "blocked")

    def test_pipeline_runner_creates_run_summary_and_blocks_missing_class(self) -> None:
        root = Path("backend_test_tmp")
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            image_dir = root / "images"
            image_dir.mkdir(parents=True, exist_ok=True)

            image_paths: list[Path] = []
            for name in ("forklift_a.png", "forklift_b.png", "pallet_a.png", "pallet_b.png"):
                path = image_dir / name
                path.write_bytes(PNG_BYTES + name.encode("utf-8"))
                image_paths.append(path)

            manifest_path = root / "source_manifest.json"
            manifest_payload = {
                "sources": [
                    {
                        "id": "forklift_a",
                        "source_type": "web_image",
                        "class_names": ["forklift"],
                        "title": "forklift a",
                        "local_path": str(image_paths[0]),
                        "license": self._valid_license("forklift_a"),
                        "metadata": {"blur_score": 0.9, "visibility_score": 0.85, "object_size_score": 0.8},
                    },
                    {
                        "id": "forklift_b",
                        "source_type": "web_image",
                        "class_names": ["forklift"],
                        "title": "forklift b",
                        "local_path": str(image_paths[1]),
                        "license": self._valid_license("forklift_b"),
                        "metadata": {"blur_score": 0.9, "visibility_score": 0.85, "object_size_score": 0.8},
                    },
                    {
                        "id": "pallet_a",
                        "source_type": "web_image",
                        "class_names": ["pallet jack"],
                        "title": "pallet a",
                        "local_path": str(image_paths[2]),
                        "license": self._valid_license("pallet_a"),
                        "metadata": {"blur_score": 0.88, "visibility_score": 0.82, "object_size_score": 0.78},
                    },
                    {
                        "id": "pallet_b",
                        "source_type": "web_image",
                        "class_names": ["pallet jack"],
                        "title": "pallet b",
                        "local_path": str(image_paths[3]),
                        "license": self._valid_license("pallet_b"),
                        "metadata": {"blur_score": 0.88, "visibility_score": 0.82, "object_size_score": 0.78},
                    },
                ]
            }
            manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")

            config = JobConfig(
                job_id="test-run",
                prompt="forklift and pallet jack in a warehouse",
                classes=["forklift", "pallet jack", "ghost"],
                output_root=root / "artifacts",
                source=SourceConfig(
                    manifest_path=manifest_path,
                    ffmpeg_path="ffmpeg",
                    frames_per_second=0.5,
                    max_frames_per_video=5,
                ),
                label=LabelConfig(provider="mock", api_key=None, gemini_model="gemini-2.0-flash"),
                training=TrainingConfig(enabled=False, model="yolov8n.pt", epochs=1, image_size=640),
                budgets=BudgetLimits(max_label_calls=20, max_accepted_samples=10),
                critic=CriticThresholds(
                    min_quality_score=0.5,
                    min_label_confidence=0.7,
                    min_samples_to_label=1,
                    min_samples_for_training=1,
                ),
                mix=SourceMix(),
            )

            stage_events: list[tuple[str, str]] = []
            summary = PipelineRunner(
                config,
                run_context=PipelineRunContext(
                    stage_update=lambda stage_name, status: stage_events.append((stage_name, status))
                ),
            ).run()
            self.assertIn("forklift", summary.admitted_classes)
            self.assertIn("pallet jack", summary.admitted_classes)
            self.assertIn("ghost", summary.blocked_classes)
            self.assertTrue(Path(summary.artifact_paths["run_summary"]).exists())
            started_stages = [stage_name for stage_name, status in stage_events if status == "running"]
            self.assertEqual(started_stages, list(PIPELINE_STAGES))
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_integration_multi_class_imbalance_run_is_blocked_by_quota_gate(self) -> None:
        root = Path("backend_test_quota_tmp")
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            manifest_path = self._write_manifest_with_images(
                root,
                [
                    ("forklift_a", ["forklift"], 0.95),
                    ("forklift_b", ["forklift"], 0.95),
                    ("forklift_c", ["forklift"], 0.95),
                    ("pallet_a", ["pallet jack"], 0.95),
                ],
            )
            config = self._job_config(
                root,
                manifest_path,
                ["forklift", "pallet jack"],
                ClassQualityConfig(min_train_samples=2, min_val_samples=1),
            )

            summary = PipelineRunner(config).run()
            quota_gate = read_json(Path(summary.artifact_paths["class_quota_gate"]))
            training_results = read_json(Path(summary.artifact_paths["training_results"]))

            self.assertEqual(quota_gate["status"], "blocked")
            self.assertEqual(quota_gate["per_class"]["pallet jack"]["status"], "blocked")
            self.assertEqual(training_results["status"], "blocked")
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_integration_pending_review_items_block_training(self) -> None:
        root = Path("backend_test_review_tmp")
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            manifest_path = self._write_manifest_with_images(
                root,
                [
                    ("forklift_a", ["forklift"], 0.2),
                    ("forklift_b", ["forklift"], 0.2),
                ],
            )
            config = self._job_config(
                root,
                manifest_path,
                ["forklift"],
                ClassQualityConfig(min_train_samples=1, min_val_samples=0, review_confidence_threshold=0.8),
            )

            summary = PipelineRunner(config).run()
            review_queue = read_json(Path(summary.artifact_paths["review_queue"]))
            training_results = read_json(Path(summary.artifact_paths["training_results"]))

            self.assertEqual(len(review_queue["items"]), 2)
            self.assertTrue(all(item["state"] == "pending" for item in review_queue["items"]))
            self.assertEqual(training_results["status"], "blocked")
            self.assertIn("review item", " ".join(training_results["notes"]))
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_regression_legacy_mode_preserves_training_skip_behavior(self) -> None:
        root = Path("backend_test_legacy_tmp")
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            manifest_path = self._write_manifest_with_images(
                root,
                [("forklift_a", ["forklift"], 0.2)],
            )
            config = self._job_config(
                root,
                manifest_path,
                ["forklift"],
                ClassQualityConfig(enabled=True, opt_out_legacy_mode=True),
            )

            summary = PipelineRunner(config).run()
            training_results = read_json(Path(summary.artifact_paths["training_results"]))
            class_quality_report = read_json(Path(summary.artifact_paths["class_quality_report"]))

            self.assertEqual(training_results["status"], "skipped")
            self.assertFalse(class_quality_report["enabled"])
            self.assertTrue(class_quality_report["legacy_mode"])
        finally:
            if root.exists():
                shutil.rmtree(root)

    def test_regression_single_class_baseline_run_still_succeeds(self) -> None:
        root = Path("backend_test_single_tmp")
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            manifest_path = self._write_manifest_with_images(
                root,
                [
                    ("forklift_a", ["forklift"], 0.95),
                    ("forklift_b", ["forklift"], 0.95),
                    ("forklift_c", ["forklift"], 0.95),
                ],
            )
            config = self._job_config(
                root,
                manifest_path,
                ["forklift"],
                ClassQualityConfig(min_train_samples=1, min_val_samples=1),
            )

            summary = PipelineRunner(config).run()
            self.assertIn("forklift", summary.admitted_classes)
            self.assertEqual(summary.quota_status["status"], "passed")
            self.assertEqual(summary.review_queue_summary["pending"], 0)
        finally:
            if root.exists():
                shutil.rmtree(root)

    def _write_manifest_with_images(
        self,
        root: Path,
        rows: list[tuple[str, list[str], float]],
    ) -> Path:
        image_dir = root / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        sources = []
        for source_id, class_names, confidence in rows:
            image_path = image_dir / f"{source_id}.png"
            image_path.write_bytes(PNG_BYTES + source_id.encode("utf-8"))
            sources.append(
                {
                    "id": source_id,
                    "source_type": "web_image",
                    "class_names": class_names,
                    "title": source_id,
                    "local_path": str(image_path),
                    "license": self._valid_license(source_id),
                    "metadata": {
                        "blur_score": 0.9,
                        "visibility_score": 0.9,
                        "object_size_score": 0.9,
                        "mock_confidence": confidence,
                    },
                }
            )
        manifest_path = root / "source_manifest.json"
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

    def _job_config(
        self,
        root: Path,
        manifest_path: Path,
        classes: list[str],
        class_quality: ClassQualityConfig,
    ) -> JobConfig:
        return JobConfig(
            job_id="test-run",
            prompt="forklift and pallet jack in a warehouse",
            classes=classes,
            output_root=root / "artifacts",
            source=SourceConfig(manifest_path=manifest_path),
            label=LabelConfig(provider="mock", api_key=None, gemini_model="gemini-2.0-flash"),
            training=TrainingConfig(enabled=False, model="yolov8n.pt", epochs=1, image_size=640),
            budgets=BudgetLimits(max_label_calls=20, max_accepted_samples=10),
            critic=CriticThresholds(
                min_quality_score=0.5,
                min_label_confidence=0.7,
                min_samples_to_label=1,
                min_samples_for_training=1,
            ),
            mix=SourceMix(web_target_ratio=1.0, video_target_ratio=0.0),
            class_quality=class_quality,
        )


if __name__ == "__main__":
    unittest.main()
