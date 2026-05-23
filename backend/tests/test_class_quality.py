from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autonomous_dataset_agent.class_quality import (
    build_class_quota_gate,
    mine_hard_negative_candidates,
    review_gate,
    select_class_aware_samples,
)
from autonomous_dataset_agent.contracts import (
    ClassQualityConfig,
    DatasetBuildResult,
    LabelBox,
    LabelRecord,
    SampleRecord,
    SourceMix,
)
from autonomous_dataset_agent.labeling import validate_label_records_with_review
from autonomous_dataset_agent.utils import write_json


class ClassQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("backend_test_class_quality_tmp")
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def test_class_aware_sampler_preserves_minority_classes_under_mixed_quality(self) -> None:
        samples = [
            self._sample(f"forklift_{index}", ["forklift"], quality=0.95 - index * 0.01)
            for index in range(5)
        ] + [
            self._sample(f"pallet_{index}", ["pallet jack"], quality=0.45 - index * 0.01)
            for index in range(2)
        ]

        selected, report = select_class_aware_samples(
            samples,
            classes=["forklift", "pallet jack"],
            mix=SourceMix(web_target_ratio=1.0, video_target_ratio=0.0),
            max_samples=4,
            min_candidate_pool=2,
        )

        selected_ids = {sample.id for sample in selected}
        self.assertEqual(report["after_distribution"]["pallet jack"], 2)
        self.assertTrue({"pallet_0", "pallet_1"}.issubset(selected_ids))
        self.assertTrue(all("class_coverage_delta" in sample.metadata for sample in selected))

    def test_quota_gate_blocks_training_when_any_class_misses_minimum_split_counts(self) -> None:
        dataset_result = DatasetBuildResult(
            status="completed",
            class_split_counts={
                "forklift": {"train": 2, "val": 1},
                "pallet jack": {"train": 1, "val": 0},
            },
        )

        gate = build_class_quota_gate(
            dataset_result,
            ["forklift", "pallet jack"],
            ClassQualityConfig(min_train_samples=2, min_val_samples=1),
        )

        self.assertEqual(gate["status"], "blocked")
        self.assertEqual(gate["per_class"]["forklift"]["status"], "passed")
        self.assertEqual(gate["per_class"]["pallet jack"]["status"], "blocked")

    def test_label_validator_routes_low_confidence_and_conflicts_into_review_queue(self) -> None:
        records = [
            LabelRecord(
                sample_id="sample_1",
                provider="mock",
                status="ok",
                boxes=[
                    LabelBox("forklift", 0, 0.5, 0.5, 0.4, 0.4, 0.99),
                    LabelBox("pallet jack", 1, 0.5, 0.5, 0.4, 0.4, 0.99),
                    LabelBox("forklift", 0, 0.2, 0.2, 0.2, 0.2, 0.2),
                ],
            )
        ]

        valid, invalid, queue = validate_label_records_with_review(
            records,
            ["forklift", "pallet jack"],
            min_confidence=0.7,
            class_quality=ClassQualityConfig(review_confidence_threshold=0.8, conflict_iou_threshold=0.5),
        )

        reasons = {reason for item in queue["items"] for reason in item["reasons"]}
        self.assertEqual(valid, [])
        self.assertEqual(len(invalid), 1)
        self.assertIn("low confidence", reasons)
        self.assertIn("cross-class conflict", reasons)
        self.assertEqual(review_gate(queue)["status"], "blocked")

    def test_hard_negative_miner_returns_deterministic_top_k_candidates(self) -> None:
        reports = self.root / "prior-run" / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        write_json(
            reports / "labels_manifest.json",
            {
                "valid": [
                    {
                        "sample_id": "sample_b",
                        "boxes": [{"class_name": "forklift", "confidence": 0.6}],
                    },
                    {
                        "sample_id": "sample_a",
                        "boxes": [{"class_name": "forklift", "confidence": 0.5}],
                    },
                ]
            },
        )
        write_json(reports / "evaluation_report.json", {"weak_classes": ["pallet jack"]})

        result = mine_hard_negative_candidates(
            self.root,
            current_job_id="current-run",
            classes=["forklift", "pallet jack"],
            top_k=1,
        )

        self.assertEqual(result["summary"]["count"], 1)
        self.assertEqual(result["candidates"][0]["sample_id"], "sample_a")
        self.assertEqual(result["candidates"][0]["confused_with"], "pallet jack")

    @staticmethod
    def _sample(sample_id: str, classes: list[str], quality: float) -> SampleRecord:
        return SampleRecord(
            id=sample_id,
            source_id=sample_id,
            source_type="web_image",
            class_names=classes,
            path=f"{sample_id}.jpg",
            quality_score=quality,
            decision="accept",
        )


if __name__ == "__main__":
    unittest.main()
