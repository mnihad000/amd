from __future__ import annotations

import shutil
import sys
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autonomous_dataset_agent.api import create_app
from autonomous_dataset_agent.config import JobConfig, LabelConfig, SourceConfig, TrainingConfig
from autonomous_dataset_agent.contracts import BudgetLimits, CriticThresholds, RunSummary, SourceMix
from autonomous_dataset_agent.run_lifecycle import PIPELINE_STAGES, PipelineRunContext
from autonomous_dataset_agent.utils import write_json


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("backend_test_api_tmp")
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_root = self.root / "artifacts"
        self.index_path = self.artifacts_root / "run_index.json"

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_post_run_returns_queued_then_completes_and_serves_artifacts(self) -> None:
        app = create_app(
            artifacts_root=self.artifacts_root,
            index_path=self.index_path,
            build_config_fn=self._build_config_factory(),
            runner_factory=self._runner_factory(),
        )

        with TestClient(app) as client:
            response = client.post("/runs", json={"prompt": "job-success", "classes": ["forklift"]})

            self.assertEqual(response.status_code, 202)
            body = response.json()
            self.assertEqual(body["job_id"], "job-success")
            self.assertEqual(body["status"], "queued")
            self.assertEqual(body["progress"]["completed_stages"], 0)

            completed = self._wait_for_status(client, "job-success", "completed")
            self.assertEqual(completed["current_stage"], "finalize")
            self.assertIn("artifact_paths", completed["summary"])
            self.assertEqual(len(completed["stage_history"]), len(PIPELINE_STAGES))
            bootstrap_stage = next(item for item in completed["stage_history"] if item["name"] == "bootstrap")
            self.assertIsNotNone(bootstrap_stage["started_at"])
            self.assertIsNotNone(bootstrap_stage["completed_at"])
            self.assertIsNotNone(bootstrap_stage["duration_ms"])

            artifact_response = client.get("/runs/job-success/artifacts")
            self.assertEqual(artifact_response.status_code, 200)
            artifacts_body = artifact_response.json()
            self.assertIn("run_summary", artifacts_body["artifact_paths"])
            self.assertIn("api_url", artifacts_body["artifacts"]["run_summary"])
            self.assertIn("file_url", artifacts_body["artifacts"]["run_summary"])

            artifact_json = client.get("/runs/job-success/artifacts/run_summary")
            self.assertEqual(artifact_json.status_code, 200)
            self.assertEqual(artifact_json.json()["job_id"], "job-success")

            file_response = client.get("/runs/job-success/files/frames/preview.txt")
            self.assertEqual(file_response.status_code, 200)
            self.assertEqual(file_response.text, "preview")

    def test_post_run_rejects_blank_class_list_with_stable_400(self) -> None:
        app = create_app(
            artifacts_root=self.artifacts_root,
            index_path=self.index_path,
            build_config_fn=self._build_config_factory(),
            runner_factory=self._runner_factory(),
        )

        with TestClient(app) as client:
            response = client.post("/runs", json={"prompt": "job-invalid", "classes": [" ", ""]})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")

    def test_failure_is_persisted_and_visible_via_get(self) -> None:
        app = create_app(
            artifacts_root=self.artifacts_root,
            index_path=self.index_path,
            build_config_fn=self._build_config_factory(),
            runner_factory=self._runner_factory({"job-failed": {"raise_on_stage": "critic", "exception": RuntimeError("pipeline exploded")}}),
        )

        with TestClient(app) as client:
            client.post("/runs", json={"prompt": "job-failed", "classes": ["forklift"]})
            failed = self._wait_for_status(client, "job-failed", "failed")

        self.assertEqual(failed["error"]["code"], "run_failed")
        critic_stage = next(item for item in failed["stage_history"] if item["name"] == "critic")
        self.assertEqual(critic_stage["status"], "failed")

    def test_timeout_becomes_failed_with_run_timed_out(self) -> None:
        app = create_app(
            artifacts_root=self.artifacts_root,
            index_path=self.index_path,
            build_config_fn=self._build_config_factory(max_runtime_seconds=0),
            runner_factory=self._runner_factory({"job-timeout": {"stage_delays": {"bootstrap": 0.05}}}),
        )

        with TestClient(app) as client:
            client.post("/runs", json={"prompt": "job-timeout", "classes": ["forklift"]})
            failed = self._wait_for_status(client, "job-timeout", "failed")

        self.assertEqual(failed["error"]["code"], "run_timed_out")

    def test_cancel_on_queued_run_fails_with_run_cancelled(self) -> None:
        app = create_app(
            artifacts_root=self.artifacts_root,
            index_path=self.index_path,
            build_config_fn=self._build_config_factory(),
            runner_factory=self._runner_factory({"job-blocker": {"stage_delays": {"bootstrap": 0.4}}}),
            max_workers=1,
        )

        with TestClient(app) as client:
            client.post("/runs", json={"prompt": "job-blocker", "classes": ["forklift"]})
            queued_response = client.post("/runs", json={"prompt": "job-queued", "classes": ["forklift"]})
            self.assertEqual(queued_response.status_code, 202)
            self.assertEqual(queued_response.json()["status"], "queued")

            cancel_response = client.post("/runs/job-queued/cancel")
            self.assertEqual(cancel_response.status_code, 202)

            cancelled = self._wait_for_status(client, "job-queued", "failed")
            self.assertEqual(cancelled["error"]["code"], "run_cancelled")

    def test_cancel_on_running_run_is_cooperative(self) -> None:
        app = create_app(
            artifacts_root=self.artifacts_root,
            index_path=self.index_path,
            build_config_fn=self._build_config_factory(),
            runner_factory=self._runner_factory({"job-running": {"stage_delays": {"critic": 0.25}}}),
        )

        with TestClient(app) as client:
            client.post("/runs", json={"prompt": "job-running", "classes": ["forklift"]})
            self._wait_for_stage(client, "job-running", "critic")

            cancel_response = client.post("/runs/job-running/cancel")
            self.assertEqual(cancel_response.status_code, 202)

            cancelled = self._wait_for_status(client, "job-running", "failed")
            self.assertEqual(cancelled["error"]["code"], "run_cancelled")
            self.assertTrue(cancelled["cancel_requested"])

    def test_cancel_on_terminal_run_returns_409(self) -> None:
        app = create_app(
            artifacts_root=self.artifacts_root,
            index_path=self.index_path,
            build_config_fn=self._build_config_factory(),
            runner_factory=self._runner_factory(),
        )

        with TestClient(app) as client:
            client.post("/runs", json={"prompt": "job-terminal", "classes": ["forklift"]})
            self._wait_for_status(client, "job-terminal", "completed")
            response = client.post("/runs/job-terminal/cancel")

        self.assertEqual(response.status_code, 409)

    def test_restart_converts_incomplete_runs_to_failed_with_interrupted(self) -> None:
        run_root = self.artifacts_root / "job-restart"
        run_root.mkdir(parents=True, exist_ok=True)
        write_json(
            self.index_path,
            {
                "runs": {
                    "job-restart": {
                        "job_id": "job-restart",
                        "status": "running",
                        "output_root": str(self.artifacts_root),
                        "prompt": "job-restart",
                        "classes": ["forklift"],
                        "source_mode": "manifest",
                        "created_at": "2026-05-06T00:00:00+00:00",
                        "updated_at": "2026-05-06T00:00:00+00:00",
                    }
                }
            },
        )

        app = create_app(
            artifacts_root=self.artifacts_root,
            index_path=self.index_path,
            build_config_fn=self._build_config_factory(),
            runner_factory=self._runner_factory(),
        )

        with TestClient(app) as client:
            run_response = client.get("/runs/job-restart")

        self.assertEqual(run_response.status_code, 200)
        self.assertEqual(run_response.json()["status"], "failed")
        self.assertEqual(run_response.json()["error"]["code"], "run_interrupted")

    def test_get_runs_returns_recent_runs_in_descending_updated_order(self) -> None:
        app = create_app(
            artifacts_root=self.artifacts_root,
            index_path=self.index_path,
            build_config_fn=self._build_config_factory(),
            runner_factory=self._runner_factory({"job-first": {"stage_delays": {"bootstrap": 0.05}}}),
        )

        with TestClient(app) as client:
            client.post("/runs", json={"prompt": "job-first", "classes": ["forklift"]})
            self._wait_for_status(client, "job-first", "completed")

            client.post("/runs", json={"prompt": "job-second", "classes": ["forklift"]})
            self._wait_for_status(client, "job-second", "completed")

            response = client.get("/runs?limit=10")

        self.assertEqual(response.status_code, 200)
        runs = response.json()["runs"]
        self.assertEqual([item["job_id"] for item in runs[:2]], ["job-second", "job-first"])

    def test_health_reports_queue_and_worker_counts(self) -> None:
        app = create_app(
            artifacts_root=self.artifacts_root,
            index_path=self.index_path,
            build_config_fn=self._build_config_factory(),
            runner_factory=self._runner_factory({"job-active": {"stage_delays": {"bootstrap": 0.4}}}),
            max_workers=1,
        )

        with TestClient(app) as client:
            client.post("/runs", json={"prompt": "job-active", "classes": ["forklift"]})
            client.post("/runs", json={"prompt": "job-queued", "classes": ["forklift"]})
            health = self._wait_for_health(client, active=1, queued=1)

        self.assertEqual(health["status"], "ready")
        self.assertEqual(health["active_worker_count"], 1)
        self.assertEqual(health["queued_run_count"], 1)

    def test_unknown_artifact_and_path_traversal_are_rejected(self) -> None:
        app = create_app(
            artifacts_root=self.artifacts_root,
            index_path=self.index_path,
            build_config_fn=self._build_config_factory(),
            runner_factory=self._runner_factory(),
        )

        with TestClient(app) as client:
            client.post("/runs", json={"prompt": "job-safe", "classes": ["forklift"]})
            self._wait_for_status(client, "job-safe", "completed")

            artifact_response = client.get("/runs/job-safe/artifacts/missing")
            file_response = client.get("/runs/job-safe/files/%2E%2E/outside.txt")

        self.assertEqual(artifact_response.status_code, 404)
        self.assertEqual(artifact_response.json()["error"]["code"], "artifacts_not_found")
        self.assertEqual(file_response.status_code, 400)
        self.assertEqual(file_response.json()["error"]["code"], "invalid_request")

    def _build_config_factory(self, *, max_runtime_seconds: int = 2):
        def build_config(
            prompt: str,
            classes: list[str],
            output_root: str | Path | None,
            env_file: str | Path | None,
            source_mode: str | None,
        ) -> JobConfig:
            del env_file
            resolved_output_root = Path(output_root) if output_root else self.artifacts_root
            return JobConfig(
                job_id=prompt,
                prompt=prompt,
                classes=classes,
                output_root=resolved_output_root,
                source=SourceConfig(source_mode=source_mode or "manifest", manifest_path=None),
                label=LabelConfig(provider="mock", api_key=None, gemini_model="gemini-2.0-flash"),
                training=TrainingConfig(enabled=False, model="yolov8n.pt", epochs=1, image_size=640),
                budgets=BudgetLimits(max_runtime_seconds=max_runtime_seconds),
                critic=CriticThresholds(),
                mix=SourceMix(),
            )

        return build_config

    def _runner_factory(self, behaviors: dict[str, dict[str, object]] | None = None):
        behavior_map = behaviors or {}

        class StageAwareRunner:
            def __init__(self, config: JobConfig) -> None:
                self.config = config
                self.run_context = PipelineRunContext()
                self.behavior = behavior_map.get(config.job_id, {})

            def set_run_context(self, run_context: PipelineRunContext) -> None:
                self.run_context = run_context

            def run(self) -> RunSummary:
                preview_path = self.config.output_root / self.config.job_id / "frames" / "preview.txt"
                summary_path = self.config.output_root / self.config.job_id / "reports" / "run_summary.json"
                stage_delays = self.behavior.get("stage_delays", {})
                raise_on_stage = self.behavior.get("raise_on_stage")
                exception = self.behavior.get("exception")

                for stage_name in PIPELINE_STAGES:
                    self.run_context.start_stage(stage_name)
                    delay = stage_delays.get(stage_name, 0) if isinstance(stage_delays, dict) else 0
                    if delay:
                        time.sleep(float(delay))
                    if raise_on_stage == stage_name and isinstance(exception, Exception):
                        self.run_context.fail_stage(stage_name)
                        raise exception
                    if stage_name == "finalize":
                        preview_path.parent.mkdir(parents=True, exist_ok=True)
                        preview_path.write_text("preview", encoding="utf-8")
                        summary = RunSummary(
                            job_id=self.config.job_id,
                            prompt=self.config.prompt,
                            requested_classes=self.config.classes,
                            admitted_classes=list(self.config.classes),
                            deferred_classes=[],
                            blocked_classes=[],
                            source_breakdown={"web_image": 1},
                            budgets={"max_runtime_seconds": self.config.budgets.max_runtime_seconds},
                            notes=[],
                            artifact_paths={
                                "run_summary": str(summary_path),
                            },
                        )
                        write_json(summary_path, summary)
                        self.run_context.complete_stage(stage_name)
                        return summary
                    self.run_context.complete_stage(stage_name)

                raise RuntimeError("Runner exited without finalizing.")

        return StageAwareRunner

    def _wait_for_status(
        self,
        client: TestClient,
        job_id: str,
        expected_status: str,
        *,
        timeout_seconds: float = 3.0,
    ) -> dict[str, object]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            response = client.get(f"/runs/{job_id}")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            if body["status"] == expected_status:
                return body
            time.sleep(0.05)
        self.fail(f"Run '{job_id}' did not reach status '{expected_status}' in time.")

    def _wait_for_stage(
        self,
        client: TestClient,
        job_id: str,
        stage_name: str,
        *,
        timeout_seconds: float = 3.0,
    ) -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            response = client.get(f"/runs/{job_id}")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            if body.get("current_stage") == stage_name:
                return
            time.sleep(0.05)
        self.fail(f"Run '{job_id}' did not reach stage '{stage_name}' in time.")

    def _wait_for_health(
        self,
        client: TestClient,
        *,
        active: int,
        queued: int,
        timeout_seconds: float = 3.0,
    ) -> dict[str, object]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            if body["active_worker_count"] == active and body["queued_run_count"] == queued:
                return body
            time.sleep(0.05)
        self.fail("Health endpoint did not report the expected queue and worker counts in time.")


if __name__ == "__main__":
    unittest.main()
