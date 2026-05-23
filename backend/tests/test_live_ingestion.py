from __future__ import annotations

import base64
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autonomous_dataset_agent.config import JobConfig, LabelConfig, SourceConfig, TrainingConfig
from autonomous_dataset_agent.contracts import BudgetLimits, CriticThresholds, SampleRecord, SourceMix, SourceRecord
from autonomous_dataset_agent.downloaders import normalize_url, round_robin_select
from autonomous_dataset_agent.orchestrator import PipelineRunner
from autonomous_dataset_agent.query_generation import generate_queries_for_class
from autonomous_dataset_agent.web_search import search_web_image_candidates


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9VE3M3UAAAAASUVORK5CYII="
)


class LiveIngestionTests(unittest.TestCase):
    def tearDown(self) -> None:
        for path_name in ("backend_test_live_tmp", "backend_test_live_video_tmp"):
            root = Path(path_name)
            if root.exists():
                shutil.rmtree(root)

    def test_generate_queries_for_class_is_deterministic_and_deduplicated(self) -> None:
        queries = generate_queries_for_class("forklift in a warehouse", "forklift")
        self.assertEqual(queries[0], "forklift in a warehouse")
        self.assertIn("forklift", queries)
        self.assertIn("forklift side view", queries)
        self.assertIn("worker using forklift in a warehouse", queries)
        self.assertEqual(len(queries), len(set(queries)))

    def test_normalize_url_sorts_query_parameters_for_deduplication(self) -> None:
        left = normalize_url("https://example.com/image.jpg?b=2&a=1")
        right = normalize_url("https://EXAMPLE.com/image.jpg?a=1&b=2")
        self.assertEqual(left, right)

    def test_round_robin_select_enforces_global_budget_across_classes(self) -> None:
        grouped = {
            "forklift": [
                SourceRecord(id="f1", source_type="web_image", class_names=["forklift"], title="f1"),
                SourceRecord(id="f2", source_type="web_image", class_names=["forklift"], title="f2"),
            ],
            "pallet jack": [
                SourceRecord(id="p1", source_type="web_image", class_names=["pallet jack"], title="p1"),
                SourceRecord(id="p2", source_type="web_image", class_names=["pallet jack"], title="p2"),
            ],
        }
        selected = round_robin_select(grouped, global_limit=3)
        self.assertEqual([item.id for item in selected], ["f1", "p1", "f2"])

    @patch("autonomous_dataset_agent.web_search.BingImageSearchProvider.search_images")
    @patch("autonomous_dataset_agent.web_search.DuckDuckGoImageSearchProvider.search_images")
    def test_web_search_falls_back_to_bing(self, mock_duckduckgo: object, mock_bing: object) -> None:
        mock_duckduckgo.side_effect = RuntimeError("ddg unavailable")
        mock_bing.return_value = [
            {
                "url": "https://cdn.example.com/forklift.jpg",
                "title": "Forklift image",
                "domain": "cdn.example.com",
                "source_page": "https://example.com/forklift",
            }
        ]
        config = SourceConfig(
            source_mode="live",
            web_search_provider_order=["duckduckgo", "bing"],
            bing_search_api_key="test-key",
        )
        grouped, notes = search_web_image_candidates(
            ["forklift"],
            {"forklift": ["forklift warehouse"]},
            config,
        )
        self.assertEqual(grouped["forklift"][0].metadata["provider"], "bing")
        self.assertTrue(any("duckduckgo" in note.lower() for note in notes))

    def test_live_mode_zero_sources_blocks_classes(self) -> None:
        root = Path("backend_test_live_tmp")
        config = self._build_live_config(root, prompt="forklift in a warehouse", classes=["forklift"])

        with patch("autonomous_dataset_agent.orchestrator.search_web_image_candidates", return_value=({}, [])):
            with patch("autonomous_dataset_agent.orchestrator.search_youtube_candidates", return_value=({}, [])):
                summary = PipelineRunner(config).run()

        self.assertIn("forklift", summary.blocked_classes)
        source_manifest_path = Path(summary.artifact_paths["source_manifest"])
        self.assertTrue(source_manifest_path.exists())
        self.assertEqual(json.loads(source_manifest_path.read_text(encoding="utf-8")), [])

    def test_live_mode_downloads_web_sources_and_writes_provenance_manifest(self) -> None:
        root = Path("backend_test_live_tmp")
        config = self._build_live_config(root, prompt="forklift in a warehouse", classes=["forklift"])
        web_candidate = SourceRecord(
            id="web_forklift_1",
            source_type="web_image",
            class_names=["forklift"],
            title="Forklift warehouse photo",
            url="https://example.com/forklift.jpg",
            license={
                "origin": "https://example.com/forklift.jpg",
                "license_type": "internal_trainable",
                "usage_rights": ["dataset_training", "model_training"],
                "expiration": "2999-01-01",
                "restrictions": [],
            },
            metadata={
                "provider": "duckduckgo",
                "query": "forklift warehouse",
                "domain": "example.com",
                "rank": 1,
            },
        )

        def fake_download_image_sources(sources: list[SourceRecord], job_paths: object, source_config: object) -> tuple[list[SourceRecord], list[str]]:
            for source in sources:
                output_path = Path(job_paths.downloads) / "web" / "forklift-test.png"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(PNG_BYTES + b"forklift-web")
                source.local_path = str(output_path)
                source.metadata["download_status"] = "downloaded"
                source.metadata["download_error"] = None
            return sources, []

        with patch(
            "autonomous_dataset_agent.orchestrator.search_web_image_candidates",
            return_value=({"forklift": [web_candidate]}, []),
        ):
            with patch("autonomous_dataset_agent.orchestrator.search_youtube_candidates", return_value=({}, [])):
                with patch(
                    "autonomous_dataset_agent.orchestrator.download_image_sources",
                    side_effect=fake_download_image_sources,
                ):
                    summary = PipelineRunner(config).run()

        self.assertIn("forklift", summary.admitted_classes)
        source_manifest = json.loads(
            Path(summary.artifact_paths["source_manifest"]).read_text(encoding="utf-8")
        )
        self.assertEqual(source_manifest[0]["metadata"]["provider"], "duckduckgo")
        self.assertEqual(source_manifest[0]["metadata"]["query"], "forklift warehouse")
        self.assertEqual(source_manifest[0]["metadata"]["download_status"], "downloaded")
        self.assertTrue(source_manifest[0]["local_path"])

    def test_live_mode_youtube_download_flows_into_frame_extraction(self) -> None:
        root = Path("backend_test_live_video_tmp")
        config = self._build_live_config(root, prompt="forklift in a warehouse", classes=["forklift"])
        youtube_candidate = SourceRecord(
            id="yt_forklift_1",
            source_type="youtube_video",
            class_names=["forklift"],
            title="Forklift walkthrough",
            url="https://www.youtube.com/watch?v=abc123",
            license={
                "origin": "https://www.youtube.com/watch?v=abc123",
                "license_type": "internal_trainable",
                "usage_rights": ["dataset_training", "model_training"],
                "expiration": "2999-01-01",
                "restrictions": [],
            },
            metadata={
                "provider": "yt-dlp",
                "query": "forklift warehouse",
                "domain": "youtube.com",
                "rank": 1,
                "video_id": "abc123",
            },
        )

        def fake_download_youtube_sources(sources: list[SourceRecord], job_paths: object, source_config: object, yt_dlp_available: bool) -> tuple[list[SourceRecord], list[str]]:
            for source in sources:
                output_path = Path(job_paths.downloads) / "youtube" / "forklift.mp4"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes((b"0" * 128) + b"video")
                source.local_path = str(output_path)
                source.metadata["download_status"] = "downloaded"
                source.metadata["download_error"] = None
            return sources, []

        def fake_extract_video_frames(sources: list[SourceRecord], job_paths: object, job_config: object, ffmpeg_available: bool) -> tuple[list[SampleRecord], list[str]]:
            frame_path = Path(job_paths.frames) / "frame_0001.png"
            frame_path.parent.mkdir(parents=True, exist_ok=True)
            frame_path.write_bytes(PNG_BYTES + b"frame")
            return (
                [
                    SampleRecord(
                        id="yt_forklift_1_f_0001",
                        source_id="yt_forklift_1",
                        source_type="video_frame",
                        class_names=["forklift"],
                        path=str(frame_path),
                        metadata={"mock_confidence": 0.95},
                        derived_from="yt_forklift_1",
                        timestamp_sec=1.0,
                    )
                ],
                [],
            )

        with patch("autonomous_dataset_agent.orchestrator.search_web_image_candidates", return_value=({}, [])):
            with patch(
                "autonomous_dataset_agent.orchestrator.search_youtube_candidates",
                return_value=({"forklift": [youtube_candidate]}, []),
            ):
                with patch(
                    "autonomous_dataset_agent.orchestrator.download_youtube_sources",
                    side_effect=fake_download_youtube_sources,
                ):
                    with patch(
                        "autonomous_dataset_agent.orchestrator.extract_video_frames",
                        side_effect=fake_extract_video_frames,
                    ):
                        summary = PipelineRunner(config).run()

        self.assertIn("forklift", summary.admitted_classes)
        sample_manifest = json.loads(
            Path(summary.artifact_paths["sample_manifest"]).read_text(encoding="utf-8")
        )
        self.assertEqual(sample_manifest[0]["source_type"], "video_frame")
        self.assertEqual(sample_manifest[0]["derived_from"], "yt_forklift_1")

    @staticmethod
    def _build_live_config(root: Path, prompt: str, classes: list[str]) -> JobConfig:
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        return JobConfig(
            job_id=f"{root.name}-job",
            prompt=prompt,
            classes=classes,
            output_root=root / "artifacts",
            source=SourceConfig(
                source_mode="live",
                web_search_provider_order=["duckduckgo", "bing"],
                bing_search_api_key="test-key",
                web_image_search_results_per_class=4,
                web_image_downloads_per_class=2,
                youtube_search_results_per_class=4,
                youtube_downloads_per_class=1,
            ),
            label=LabelConfig(provider="mock", api_key=None, gemini_model="gemini-2.0-flash"),
            training=TrainingConfig(enabled=False, model="yolov8n.pt", epochs=1, image_size=640),
            budgets=BudgetLimits(max_downloaded_sources=4, max_label_calls=10, max_accepted_samples=10),
            critic=CriticThresholds(
                min_quality_score=0.5,
                min_label_confidence=0.7,
                min_samples_to_label=1,
                min_samples_for_training=1,
            ),
            mix=SourceMix(),
        )


if __name__ == "__main__":
    unittest.main()
