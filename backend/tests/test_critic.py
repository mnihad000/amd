from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autonomous_dataset_agent.contracts import CriticThresholds, SampleRecord
from autonomous_dataset_agent.critic import ImageSignals, score_and_filter_samples


class CriticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path("backend_test_critic_tmp")
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    @patch("autonomous_dataset_agent.critic._extract_image_signals")
    def test_accepts_valid_sample_and_emits_signal_fields(self, mock_extract: object) -> None:
        sample_path = self.root / "valid.bin"
        sample_path.write_bytes(b"v" * 256)
        mock_extract.return_value = ImageSignals(
            width=640,
            height=480,
            aspect_ratio=1.333,
            brightness_mean=120.0,
            contrast_std=36.0,
            sharpness_raw=40.0,
            analysis_mode="pillow",
        )
        sample = SampleRecord(
            id="sample_a",
            source_id="source_a",
            source_type="web_image",
            class_names=["forklift"],
            path=str(sample_path),
            metadata={"visibility_score": 0.9, "object_size_score": 0.8},
        )
        thresholds = CriticThresholds(min_quality_score=0.5)

        accepted, rejected, scores = score_and_filter_samples([sample], thresholds)

        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 0)
        self.assertIn("width", scores[0])
        self.assertIn("height", scores[0])
        self.assertIn("aspect_ratio", scores[0])
        self.assertIn("brightness_mean", scores[0])
        self.assertIn("contrast_std", scores[0])
        self.assertIn("sharpness_score", scores[0])
        self.assertIn("size_score", scores[0])
        self.assertEqual(scores[0]["decision"], "accept")

    @patch("autonomous_dataset_agent.critic._extract_image_signals")
    def test_rejects_sample_below_minimum_dimensions(self, mock_extract: object) -> None:
        sample_path = self.root / "small.bin"
        sample_path.write_bytes(b"s" * 256)
        mock_extract.return_value = ImageSignals(
            width=80,
            height=120,
            aspect_ratio=0.667,
            brightness_mean=110.0,
            contrast_std=22.0,
            sharpness_raw=30.0,
            analysis_mode="pillow",
        )
        sample = SampleRecord(
            id="sample_small",
            source_id="source_small",
            source_type="web_image",
            class_names=["forklift"],
            path=str(sample_path),
            metadata={"visibility_score": 0.8, "object_size_score": 0.8},
        )
        thresholds = CriticThresholds(min_quality_score=0.5, min_image_width=160, min_image_height=160)

        accepted, rejected, scores = score_and_filter_samples([sample], thresholds)

        self.assertEqual(len(accepted), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("sample width below minimum threshold", scores[0]["rejection_reasons"])

    @patch("autonomous_dataset_agent.critic._extract_image_signals")
    def test_rejects_exact_duplicate_sample(self, mock_extract: object) -> None:
        mock_extract.return_value = ImageSignals(
            width=640,
            height=480,
            aspect_ratio=1.333,
            brightness_mean=115.0,
            contrast_std=28.0,
            sharpness_raw=32.0,
            analysis_mode="pillow",
        )
        shared_payload = b"d" * 512
        first_path = self.root / "dup_a.bin"
        second_path = self.root / "dup_b.bin"
        first_path.write_bytes(shared_payload)
        second_path.write_bytes(shared_payload)

        first = SampleRecord(
            id="dup_first",
            source_id="source_first",
            source_type="web_image",
            class_names=["forklift"],
            path=str(first_path),
            metadata={"visibility_score": 0.8, "object_size_score": 0.8},
        )
        second = SampleRecord(
            id="dup_second",
            source_id="source_second",
            source_type="web_image",
            class_names=["forklift"],
            path=str(second_path),
            metadata={"visibility_score": 0.8, "object_size_score": 0.8},
        )
        thresholds = CriticThresholds(min_quality_score=0.5)

        accepted, rejected, scores = score_and_filter_samples([first, second], thresholds)

        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].id, "dup_second")
        self.assertIn("exact duplicate of earlier sample", scores[1]["rejection_reasons"])


if __name__ == "__main__":
    unittest.main()
