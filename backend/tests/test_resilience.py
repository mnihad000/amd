from __future__ import annotations

import base64
import json
import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from autonomous_dataset_agent.api import create_app
from autonomous_dataset_agent.config import JobConfig, LabelConfig, SourceConfig, TrainingConfig
from autonomous_dataset_agent.contracts import (
    BudgetLimits,
    ClassQualityConfig,
    CriticThresholds,
    EvaluationReport,
    ResilienceConfig,
    RunSummary,
    SourceMix,
)
from autonomous_dataset_agent.critic import score_and_filter_samples as original_score_and_filter_samples
from autonomous_dataset_agent.orchestrator import PipelineRunner
from autonomous_dataset_agent.resilience import build_sla_state
from autonomous_dataset_agent.run_lifecycle import PIPELINE_STAGES, PipelineRunContext
from autonomous_dataset_agent.utils import read_json, write_json


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9VE3M3UAAAAASUVORK5CYII="
)


class ResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("backend_test_resilience_tmp")
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_stage_replay_preserves_idempotent_outputs_under_retry(self) -> None:
        config = self._pipeline_config("retry-run", ["forklift"])
        calls = {"count": 0}

        def flaky_critic(samples, thresholds):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("transient critic failure")
            return original_score_and_filter_samples(samples, thresholds)

        with patch("autonomous_dataset_agent.orchestrator.score_and_filter_samples", side_effect=flaky_critic):
            summary = PipelineRunner(config).run()

        self.assertEqual(calls["count"], 2)
        self.assertIn("forklift", summary.admitted_classes)
        checkpoint_manifest = read_json(Path(summary.artifact_paths["checkpoint_manifest"]))
        critic_checkpoint = next(item for item in checkpoint_manifest["checkpoints"] if item["stage"] == "critic")
        self.assertEqual(critic_checkpoint["attempt"], 2)
        self.assertTrue(critic_checkpoint["replay_safe"])
        self.assertEqual(summary.orchestration_resilience["retry"]["next_resume_stage"], None)

    def test_dead_letter_routing_and_replay_endpoint_produce_deterministic_outcome(self) -> None:
        app = create_app(
            artifacts_root=self.root / "artifacts",
            index_path=self.root / "artifacts" / "run_index.json",
            build_config_fn=self._build_config_factory(max_stage_attempts=1),
            runner_factory=PipelineRunner,
        )

        with TestClient(app) as client:
            with patch("autonomous_dataset_agent.orchestrator.score_and_filter_samples", side_effect=RuntimeError("critic is down")):
                client.post("/runs", json={"prompt": "dead-letter-run", "classes": ["forklift"]})
                failed = self._wait_for_status(client, "dead-letter-run", "failed")
            self.assertEqual(failed["error"]["code"], "run_failed")

            dead_letter_path = self.root / "artifacts" / "dead-letter-run" / "reports" / "dead_letter.json"
            self.assertTrue(dead_letter_path.exists())
            dead_letter = read_json(dead_letter_path)
            self.assertEqual(dead_letter["stage"], "critic")
            self.assertEqual(dead_letter["replay"]["stage_sequence"][0], "critic")

            replay_response = client.post("/runs/dead-letter-run/dead-letter/replay")
            self.assertEqual(replay_response.status_code, 202)
            replay_job_id = replay_response.json()["job_id"]
            completed = self._wait_for_status(client, replay_job_id, "completed")
            self.assertEqual(completed["summary"]["job_id"], replay_job_id)

    def test_checkpoint_resume_manifest_restores_without_duplicate_side_effects(self) -> None:
        config = self._pipeline_config("checkpoint-run", ["forklift"])
        summary = PipelineRunner(config).run()

        checkpoint_manifest = read_json(Path(summary.artifact_paths["checkpoint_manifest"]))
        self.assertEqual(checkpoint_manifest["checkpoint_count"], len(PIPELINE_STAGES))
        self.assertIsNone(checkpoint_manifest["next_resume_stage"])
        self.assertEqual(len({item["stage"] for item in checkpoint_manifest["checkpoints"]}), len(PIPELINE_STAGES))

    def test_rollback_restores_last_stable_promoted_artifact_set(self) -> None:
        self._write_stable_summary("stable-run")
        config = self._pipeline_config("rollback-run", ["forklift"])
        with patch(
            "autonomous_dataset_agent.orchestrator.evaluate_run",
            return_value=EvaluationReport(
                status="completed",
                map50=0.1,
                precision=0.1,
                recall=0.1,
                class_outcomes={"forklift": "blocked"},
                per_class_metrics={"forklift": {"ap": 0.1, "precision": 0.1, "recall": 0.1}},
            ),
        ):
            summary = PipelineRunner(config).run()

        rollback_plan = read_json(Path(summary.artifact_paths["rollback_plan"]))
        self.assertEqual(rollback_plan["status"], "rollback_ready")
        self.assertEqual(rollback_plan["last_stable"]["job_id"], "stable-run")
        self.assertEqual(summary.orchestration_resilience["rollback"]["last_stable_job_id"], "stable-run")

    def test_backpressure_rejects_burst_when_queue_is_full(self) -> None:
        app = create_app(
            artifacts_root=self.root / "artifacts",
            index_path=self.root / "artifacts" / "run_index.json",
            build_config_fn=self._build_config_factory(),
            runner_factory=self._slow_runner_factory({"active-run": 0.4}),
            max_workers=1,
            max_queue_size=1,
        )

        with TestClient(app) as client:
            client.post("/runs", json={"prompt": "active-run", "classes": ["forklift"]})
            queued_response = client.post("/runs", json={"prompt": "queued-run", "classes": ["forklift"]})
            self.assertEqual(queued_response.status_code, 202)

            rejected_response = client.post("/runs", json={"prompt": "overflow-run", "classes": ["forklift"]})
            self.assertEqual(rejected_response.status_code, 503)
            self.assertIn("backpressure", rejected_response.json()["error"]["message"])

            health = client.get("/health").json()
            self.assertEqual(health["backpressure"]["backpressure_state"], "rejecting")

    def test_sla_state_maps_escalation_policy(self) -> None:
        state = build_sla_state(
            [{"stage": "training", "status": "completed", "duration_ms": 2000}],
            ResilienceConfig(default_stage_sla_seconds=1),
        )

        self.assertEqual(state["overall_state"], "escalated")
        self.assertEqual(state["stage_states"]["training"]["escalation"], "admin_incident_review")

    def test_legacy_run_without_resilience_fields_remains_readable(self) -> None:
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
        self.assertIsNone(response.json()["orchestration_resilience"])

    def _build_config_factory(self, *, max_stage_attempts: int = 2):
        def build_config(prompt: str, classes: list[str], output_root: str | Path | None, env_file, source_mode) -> JobConfig:
            del env_file
            resolved_output_root = Path(output_root) if output_root else self.root / "artifacts"
            manifest_path = self._write_manifest(prompt, classes)
            config = self._pipeline_config(prompt, classes, output_root=resolved_output_root, manifest_path=manifest_path)
            config.source.source_mode = source_mode or "manifest"
            config.resilience.max_stage_attempts = max_stage_attempts
            return config

        return build_config

    def _pipeline_config(
        self,
        job_id: str,
        classes: list[str],
        *,
        output_root: Path | None = None,
        manifest_path: Path | None = None,
    ) -> JobConfig:
        resolved_manifest = manifest_path or self._write_manifest(job_id, classes)
        return JobConfig(
            job_id=job_id,
            prompt=" and ".join(classes) + " in a warehouse",
            classes=classes,
            output_root=output_root or self.root / "artifacts",
            source=SourceConfig(source_mode="manifest", manifest_path=resolved_manifest),
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
            for index in range(2):
                source_id = f"{class_name.replace(' ', '_')}_{index}"
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

    def _write_stable_summary(self, job_id: str) -> None:
        summary_path = self.root / "artifacts" / job_id / "reports" / "run_summary.json"
        write_json(
            summary_path,
            {
                "job_id": job_id,
                "prompt": "stable forklift",
                "requested_classes": ["forklift"],
                "admitted_classes": ["forklift"],
                "deferred_classes": [],
                "blocked_classes": [],
                "source_breakdown": {},
                "budgets": {},
                "notes": [],
                "artifact_paths": {"run_summary": str(summary_path), "best_model": "models/best.pt"},
                "promotion_gate_summary": {"status": "passed"},
                "iteration_policy": {"selected_action": "promote"},
                "version_summary": {"dataset_version_id": "dataset_stable", "model_version_id": "model_stable"},
            },
        )

    @staticmethod
    def _valid_license(source_id: str) -> dict[str, object]:
        return {
            "origin": f"unit-test:{source_id}",
            "license_type": "internal_trainable",
            "usage_rights": ["dataset_training", "model_training"],
            "expiration": "2999-01-01",
            "restrictions": [],
        }

    def _slow_runner_factory(self, delays: dict[str, float]):
        class SlowRunner:
            def __init__(self, config: JobConfig) -> None:
                self.config = config
                self.run_context = PipelineRunContext()

            def set_run_context(self, run_context: PipelineRunContext) -> None:
                self.run_context = run_context

            def run(self) -> RunSummary:
                for stage_name in PIPELINE_STAGES:
                    self.run_context.start_stage(stage_name)
                    delay = delays.get(self.config.job_id, 0)
                    if stage_name == "bootstrap" and delay:
                        time.sleep(delay)
                    self.run_context.complete_stage(stage_name)
                summary_path = self.config.output_root / self.config.job_id / "reports" / "run_summary.json"
                summary = RunSummary(
                    job_id=self.config.job_id,
                    prompt=self.config.prompt,
                    requested_classes=self.config.classes,
                    admitted_classes=self.config.classes,
                    deferred_classes=[],
                    blocked_classes=[],
                    source_breakdown={},
                    budgets={},
                    artifact_paths={"run_summary": str(summary_path)},
                )
                write_json(summary_path, summary)
                return summary

        return SlowRunner

    def _wait_for_status(self, client: TestClient, job_id: str, expected_status: str, timeout_seconds: float = 4.0) -> dict[str, object]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            response = client.get(f"/runs/{job_id}")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            if body["status"] == expected_status:
                return body
            time.sleep(0.05)
        self.fail(f"Run '{job_id}' did not reach status '{expected_status}' in time.")


if __name__ == "__main__":
    unittest.main()
