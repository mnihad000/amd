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
from autonomous_dataset_agent.contracts import BudgetLimits, CriticThresholds, LabelBox, LabelRecord, SampleRecord, SourceMix
from autonomous_dataset_agent.orchestrator import PipelineRunner
from autonomous_dataset_agent.run_lifecycle import PIPELINE_STAGES, PipelineRunContext


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
                        "metadata": {"blur_score": 0.9, "visibility_score": 0.85, "object_size_score": 0.8},
                    },
                    {
                        "id": "forklift_b",
                        "source_type": "web_image",
                        "class_names": ["forklift"],
                        "title": "forklift b",
                        "local_path": str(image_paths[1]),
                        "metadata": {"blur_score": 0.9, "visibility_score": 0.85, "object_size_score": 0.8},
                    },
                    {
                        "id": "pallet_a",
                        "source_type": "web_image",
                        "class_names": ["pallet jack"],
                        "title": "pallet a",
                        "local_path": str(image_paths[2]),
                        "metadata": {"blur_score": 0.88, "visibility_score": 0.82, "object_size_score": 0.78},
                    },
                    {
                        "id": "pallet_b",
                        "source_type": "web_image",
                        "class_names": ["pallet jack"],
                        "title": "pallet b",
                        "local_path": str(image_paths[3]),
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


if __name__ == "__main__":
    unittest.main()
