from __future__ import annotations

import base64
import json
import shutil
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autonomous_dataset_agent.api import create_app
from autonomous_dataset_agent.config import JobConfig, LabelConfig, SourceConfig, TrainingConfig
from autonomous_dataset_agent.contracts import (
    BudgetLimits,
    CriticThresholds,
    DatasetBuildResult,
    EvaluationReport,
    GovernanceConfig,
    IterationDecision,
    LabelBox,
    LabelRecord,
    SampleRecord,
    SourceMix,
    SourceRecord,
    TrainingResult,
)
from autonomous_dataset_agent.governance import (
    build_audit_log,
    build_lineage_manifest,
    build_version_manifest,
    validate_source_licenses,
)
from autonomous_dataset_agent.orchestrator import PipelineRunner
from autonomous_dataset_agent.utils import read_json, write_json


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9VE3M3UAAAAASUVORK5CYII="
)


class GovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("backend_test_governance_tmp")
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_lineage_chain_is_complete_and_deterministic_for_identical_inputs(self) -> None:
        source = self._source("forklift_a", license_metadata=self._valid_license("forklift_a"))
        sample = SampleRecord(
            id="forklift_a",
            source_id="forklift_a",
            source_type="web_image",
            class_names=["forklift"],
            path="forklift_a.png",
            quality_score=0.9,
            decision="accept",
        )
        label = LabelRecord(
            sample_id="forklift_a",
            provider="mock",
            status="validated",
            label_path=str(self.root / "artifacts" / "run" / "datasets" / "dataset" / "labels" / "train" / "forklift_a.txt"),
            boxes=[LabelBox("forklift", 0, 0.5, 0.5, 0.4, 0.4, 0.95)],
        )
        dataset_result = DatasetBuildResult(status="completed", class_map={0: "forklift"}, split_counts={"train": 1})
        training_result = TrainingResult(status="skipped")
        decision = IterationDecision(action="promote")

        first_versions = build_version_manifest(
            job_id="run",
            source_manifest=[source],
            all_samples=[sample],
            accepted_samples=[sample],
            label_records=[label],
            dataset_result=dataset_result,
            training_result=training_result,
            iteration_decision=decision,
        )
        second_versions = build_version_manifest(
            job_id="run",
            source_manifest=[source],
            all_samples=[sample],
            accepted_samples=[sample],
            label_records=[label],
            dataset_result=dataset_result,
            training_result=training_result,
            iteration_decision=decision,
        )
        first_lineage = build_lineage_manifest(
            job_id="run",
            source_manifest=[source],
            all_samples=[sample],
            accepted_samples=[sample],
            label_records=[label],
            dataset_result=dataset_result,
            version_manifest=first_versions,
            iteration_decision=decision,
        )
        second_lineage = build_lineage_manifest(
            job_id="run",
            source_manifest=[source],
            all_samples=[sample],
            accepted_samples=[sample],
            label_records=[label],
            dataset_result=dataset_result,
            version_manifest=second_versions,
            iteration_decision=decision,
        )

        self.assertEqual(first_versions, second_versions)
        self.assertEqual(first_lineage, second_lineage)
        chain = first_lineage["lineage"][0]
        self.assertEqual(chain["source_id"], "forklift_a")
        self.assertEqual(chain["accepted_sample_id"], "forklift_a")
        self.assertEqual(chain["label_sample_id"], "forklift_a")
        self.assertEqual(chain["split"], "train")
        self.assertEqual(chain["dataset_version_id"], first_versions["dataset_version_id"])
        self.assertEqual(chain["model_version_id"], first_versions["model_version_id"])

    def test_checksum_version_ids_are_reproducible_and_immutable(self) -> None:
        source = self._source("forklift_a", license_metadata=self._valid_license("forklift_a"))
        sample = SampleRecord("forklift_a", "forklift_a", "web_image", ["forklift"], "forklift_a.png")
        label = LabelRecord("forklift_a", "mock", "validated", [LabelBox("forklift", 0, 0.5, 0.5, 0.4, 0.4, 0.95)])
        kwargs = {
            "job_id": "run",
            "source_manifest": [source],
            "all_samples": [sample],
            "accepted_samples": [sample],
            "label_records": [label],
            "dataset_result": DatasetBuildResult(status="completed"),
            "training_result": TrainingResult(status="skipped"),
            "iteration_decision": IterationDecision(action="promote"),
        }

        first = build_version_manifest(**kwargs)
        second = build_version_manifest(**kwargs)

        self.assertTrue(first["immutable"])
        self.assertEqual(first["dataset_version_id"], second["dataset_version_id"])
        self.assertEqual(first["model_version_id"], second["model_version_id"])
        self.assertTrue(first["dataset_version_id"].startswith("dataset_"))
        self.assertTrue(first["model_version_id"].startswith("model_"))

    def test_license_policy_blocks_missing_disallowed_expired_and_restricted_sources(self) -> None:
        sources = [
            self._source("missing"),
            self._source("wrong_right", license_metadata={**self._valid_license("wrong_right"), "usage_rights": ["display_only"]}),
            self._source("expired", license_metadata={**self._valid_license("expired"), "expiration": "2000-01-01"}),
            self._source("restricted", license_metadata={**self._valid_license("restricted"), "restrictions": ["no redistribution"]}),
        ]

        report = validate_source_licenses(sources, GovernanceConfig())

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["summary"]["blocked"], 4)
        reasons = {reason for violation in report["violations"] for reason in violation["reasons"]}
        self.assertIn("missing license metadata", reasons)
        self.assertIn("usage rights do not allow dataset/model training", reasons)
        self.assertIn("license expired", reasons)
        self.assertIn("license restrictions present", reasons)

    def test_valid_trainable_usage_rights_pass(self) -> None:
        report = validate_source_licenses(
            [self._source("forklift_a", license_metadata=self._valid_license("forklift_a"))],
            GovernanceConfig(),
        )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["summary"]["allowed"], 1)
        self.assertEqual(report["summary"]["blocked"], 0)

    def test_audit_log_captures_automated_and_human_actions(self) -> None:
        audit_log = build_audit_log(
            job_id="run",
            license_report={"summary": {"blocked": 0}},
            review_queue={
                "items": [
                    {
                        "id": "sample_1:0",
                        "sample_id": "sample_1",
                        "state": "approved",
                        "reviewer": "reviewer@example.com",
                        "decision_notes": ["looks correct"],
                    }
                ]
            },
            iteration_decision=IterationDecision(action="promote", reasons=["quality recovered"]),
        )

        self.assertEqual(audit_log["summary"]["automated_events"], 2)
        self.assertEqual(audit_log["summary"]["human_events"], 1)
        human_event = next(event for event in audit_log["events"] if event["event_type"] == "human_action")
        self.assertEqual(human_event["actor"], "reviewer@example.com")
        self.assertEqual(human_event["action"], "approved")

    def test_pipeline_writes_section_3_artifacts_and_blocks_missing_license(self) -> None:
        manifest_path = self._write_manifest(
            [
                ("forklift_a", ["forklift"], None),
            ]
        )
        summary = PipelineRunner(self._job_config("missing-license", manifest_path)).run()

        for artifact_name in (
            "lineage_manifest",
            "version_manifest",
            "license_compliance_report",
            "audit_log",
            "artifact_lifecycle",
        ):
            self.assertTrue(Path(summary.artifact_paths[artifact_name]).exists())

        compliance = read_json(Path(summary.artifact_paths["license_compliance_report"]))
        training = read_json(Path(summary.artifact_paths["training_results"]))
        self.assertEqual(compliance["status"], "blocked")
        self.assertEqual(summary.governance_summary["export_status"], "blocked")
        self.assertEqual(training["status"], "blocked")

    def test_pipeline_exposes_governance_summary_for_valid_sources(self) -> None:
        manifest_path = self._write_manifest(
            [
                ("forklift_a", ["forklift"], self._valid_license("forklift_a")),
                ("forklift_b", ["forklift"], self._valid_license("forklift_b")),
            ]
        )
        summary = PipelineRunner(self._job_config("valid-governance", manifest_path)).run()

        self.assertEqual(summary.governance_summary["export_status"], "passed")
        self.assertEqual(summary.license_compliance["summary"]["blocked"], 0)
        self.assertGreaterEqual(summary.lineage_summary["lineage_records"], 1)
        self.assertTrue(summary.version_summary["dataset_version_id"].startswith("dataset_"))
        self.assertEqual(summary.artifact_lifecycle["export_status"], "passed")

    def test_api_exposes_additive_governance_fields_and_old_runs_remain_readable(self) -> None:
        artifacts_root = self.root / "artifacts"
        summary_path = artifacts_root / "governed-run" / "reports" / "run_summary.json"
        write_json(
            summary_path,
            {
                "job_id": "governed-run",
                "prompt": "governed",
                "requested_classes": ["forklift"],
                "admitted_classes": ["forklift"],
                "deferred_classes": [],
                "blocked_classes": [],
                "source_breakdown": {},
                "budgets": {},
                "notes": [],
                "artifact_paths": {"run_summary": str(summary_path)},
                "governance_summary": {"export_status": "passed"},
                "lineage_summary": {"lineage_records": 1},
                "license_compliance": {"status": "passed"},
                "version_summary": {"dataset_version_id": "dataset_abc"},
                "artifact_lifecycle": {"export_status": "passed"},
            },
        )
        old_summary_path = artifacts_root / "old-run" / "reports" / "run_summary.json"
        write_json(
            old_summary_path,
            {
                "job_id": "old-run",
                "prompt": "old",
                "requested_classes": ["forklift"],
                "admitted_classes": ["forklift"],
                "deferred_classes": [],
                "blocked_classes": [],
                "source_breakdown": {},
                "budgets": {},
                "notes": [],
                "artifact_paths": {"run_summary": str(old_summary_path)},
            },
        )
        app = create_app(artifacts_root=artifacts_root, index_path=artifacts_root / "run_index.json")

        with TestClient(app) as client:
            governed = client.get("/runs/governed-run").json()
            old = client.get("/runs/old-run").json()

        self.assertEqual(governed["governance_summary"]["export_status"], "passed")
        self.assertEqual(governed["lineage_summary"]["lineage_records"], 1)
        self.assertEqual(governed["license_compliance"]["status"], "passed")
        self.assertEqual(governed["version_summary"]["dataset_version_id"], "dataset_abc")
        self.assertIsNone(old["governance_summary"])
        self.assertIsNone(old["lineage_summary"])
        self.assertIsNone(old["license_compliance"])
        self.assertIsNone(old["version_summary"])
        self.assertIsNone(old["artifact_lifecycle"])

    def _write_manifest(self, rows: list[tuple[str, list[str], dict[str, object] | None]]) -> Path:
        image_dir = self.root / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        sources = []
        for source_id, class_names, license_metadata in rows:
            image_path = image_dir / f"{source_id}.png"
            image_path.write_bytes(PNG_BYTES + source_id.encode("utf-8"))
            source = {
                "id": source_id,
                "source_type": "web_image",
                "class_names": class_names,
                "title": source_id,
                "local_path": str(image_path),
                "metadata": {
                    "blur_score": 0.9,
                    "visibility_score": 0.9,
                    "object_size_score": 0.9,
                    "mock_confidence": 0.95,
                },
            }
            if license_metadata is not None:
                source["license"] = license_metadata
            sources.append(source)
        manifest_path = self.root / "source_manifest.json"
        manifest_path.write_text(json.dumps({"sources": sources}), encoding="utf-8")
        return manifest_path

    def _job_config(self, job_id: str, manifest_path: Path) -> JobConfig:
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
            mix=SourceMix(web_target_ratio=1.0, video_target_ratio=0.0),
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

    @staticmethod
    def _source(source_id: str, license_metadata: dict[str, object] | None = None) -> SourceRecord:
        return SourceRecord(
            id=source_id,
            source_type="web_image",
            class_names=["forklift"],
            title=source_id,
            local_path=f"{source_id}.png",
            license=license_metadata or {},
        )


if __name__ == "__main__":
    unittest.main()
