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
    ClassQualityConfig,
    CriticThresholds,
    EvaluationReport,
    ObservabilityConfig,
    SourceMix,
)
from autonomous_dataset_agent.orchestrator import PipelineRunner
from autonomous_dataset_agent.telemetry import (
    TELEMETRY_CONTRACT,
    build_alert_policy_definitions,
    evaluate_alerts,
    validate_telemetry_envelope,
)
from autonomous_dataset_agent.utils import read_json, write_json


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9VE3M3UAAAAASUVORK5CYII="
)


class TelemetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("backend_test_telemetry_tmp")
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_telemetry_contract_and_log_envelope_validation(self) -> None:
        self.assertEqual(TELEMETRY_CONTRACT["primary_correlation_key"], "job_id")
        self.assertIn("stage_latency_ms", TELEMETRY_CONTRACT["metric_families"]["stage"])
        envelope = {
            "schema_version": 1,
            "timestamp": "sequence:0001",
            "severity": "info",
            "service": "autonomous-dataset-agent",
            "job_id": "job-1",
            "run_id": "job-1",
            "stage": "critic",
            "trace_id": "trace",
            "span_id": "span",
            "event_name": "stage.completed",
            "message": "Stage critic completed.",
            "attributes": {"duration_ms": 10},
        }

        self.assertEqual(validate_telemetry_envelope(envelope), [])
        broken = dict(envelope)
        broken.pop("job_id")
        broken["severity"] = "loud"
        self.assertEqual(validate_telemetry_envelope(broken), ["missing:job_id", "invalid:severity", "invalid:job_id"])

    def test_pipeline_emits_prometheus_loki_grafana_and_monitoring_summary(self) -> None:
        config = self._pipeline_config("telemetry-run", ["forklift"])
        with patch(
            "autonomous_dataset_agent.orchestrator.evaluate_run",
            return_value=EvaluationReport(
                status="completed",
                map50=0.82,
                precision=0.8,
                recall=0.8,
                class_outcomes={"forklift": "ready"},
                per_class_metrics={"forklift": {"ap": 0.82, "precision": 0.8, "recall": 0.8}},
            ),
        ):
            summary = PipelineRunner(config).run()

        for artifact_name in (
            "telemetry_contract",
            "otel_traces",
            "prometheus_metrics",
            "loki_log_envelopes",
            "grafana_dashboard",
            "alert_policies",
            "alert_evaluation",
        ):
            self.assertIn(artifact_name, summary.artifact_paths)
            self.assertTrue(Path(summary.artifact_paths[artifact_name]).exists())

        prometheus = Path(summary.artifact_paths["prometheus_metrics"]).read_text(encoding="utf-8")
        self.assertIn('ada_stage_latency_ms{job_id="telemetry-run"', prometheus)
        self.assertIn('ada_class_acceptance_rate{class_name="forklift",job_id="telemetry-run"}', prometheus)

        logs = read_json(Path(summary.artifact_paths["loki_log_envelopes"]))
        self.assertEqual(logs["job_id"], "telemetry-run")
        self.assertTrue(all(item["job_id"] == "telemetry-run" for item in logs["entries"]))

        dashboard = read_json(Path(summary.artifact_paths["grafana_dashboard"]))
        self.assertGreaterEqual(len(dashboard["panels"]), 5)
        self.assertEqual(summary.monitoring_summary["correlation_key"], "job_id")
        self.assertEqual(summary.monitoring_summary["alerts"]["status"], "clear")

    def test_alert_rules_trigger_for_failure_drift_and_budget_anomalies(self) -> None:
        config = ObservabilityConfig(repeated_stage_failure_threshold=2, class_regression_ap_delta=0.05, budget_spend_ratio=0.9)
        policies = build_alert_policy_definitions(config)
        self.assertEqual({item["name"] for item in policies["policies"]}, {"stuck_run", "repeated_stage_failures", "class_regression_drift_anomaly", "budget_anomaly"})

        evaluation = evaluate_alerts(
            metrics=[
                {"name": "class_ap_drift", "value": -0.07, "labels": {"class_name": "forklift"}},
                {"name": "budget_spend_ratio", "value": 0.95, "labels": {"budget": "label_calls"}},
            ],
            stage_telemetry=[
                {"stage": "critic", "status": "failed", "duration_ms": 1, "attempt": 1},
                {"stage": "labeling", "status": "failed", "duration_ms": 1, "attempt": 1},
            ],
            config=config,
        )

        self.assertEqual(evaluation["status"], "triggered")
        self.assertEqual(
            {item["name"] for item in evaluation["triggered"]},
            {"repeated_stage_failures", "class_regression_drift_anomaly", "budget_anomaly"},
        )

    def test_run_flow_survives_unavailable_observability_sink(self) -> None:
        config = self._pipeline_config("sink-unavailable", ["forklift"])
        config.observability = ObservabilityConfig(otel_exporter_endpoint="http://127.0.0.1:4318")
        summary = PipelineRunner(config).run()

        self.assertEqual(summary.job_id, "sink-unavailable")
        self.assertEqual(summary.monitoring_summary["otel"]["sink_status"], "configured")
        self.assertTrue(Path(summary.artifact_paths["otel_traces"]).exists())

    def test_legacy_run_without_monitoring_fields_remains_readable(self) -> None:
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
        self.assertIsNone(response.json()["monitoring_summary"])

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

    @staticmethod
    def _valid_license(source_id: str) -> dict[str, object]:
        return {
            "origin": f"unit-test:{source_id}",
            "license_type": "internal_trainable",
            "usage_rights": ["dataset_training", "model_training"],
            "expiration": "2999-01-01",
            "restrictions": [],
        }


if __name__ == "__main__":
    unittest.main()
