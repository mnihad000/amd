from __future__ import annotations

from collections import Counter
from pathlib import Path

from .bootstrap import run_bootstrap_checks
from .class_planner import (
    attach_source_counts,
    build_initial_class_plan,
    determine_label_admission,
    finalize_class_plan,
    normalize_classes,
)
from .config import JobConfig
from .contracts import BootstrapReport, JobPaths, LabelRecord, RunSummary, SourceRecord
from .critic import score_and_filter_samples
from .dataset_builder import build_dataset
from .downloaders import download_image_sources, round_robin_select
from .evaluation import evaluate_run
from .iteration import decide_next_step
from .labeling import build_label_provider, validate_label_records
from .query_generation import generate_class_queries
from .sources import (
    collect_web_image_sources,
    collect_youtube_video_sources,
    extract_video_frames,
    has_local_asset,
    load_source_manifest,
    normalize_sources_to_samples,
    rebalance_samples,
    usable_sources,
)
from .training import train_dataset
from .utils import ensure_dir, write_json
from .web_search import search_web_image_candidates
from .youtube_search import download_youtube_sources, search_youtube_candidates


class PipelineRunner:
    def __init__(self, config: JobConfig) -> None:
        self.config = config

    def run(self) -> RunSummary:
        bootstrap = run_bootstrap_checks(
            self.config.source.ffmpeg_path,
            self.config.source.yt_dlp_path,
        )
        job_paths = self._build_job_paths(self.config.output_root, self.config.job_id)
        requested_classes = normalize_classes(self.config.classes)

        class_plan = build_initial_class_plan(self.config.prompt, requested_classes)
        source_manifest, source_notes = self._resolve_source_manifest(
            requested_classes,
            job_paths,
            bootstrap,
        )
        class_plan = attach_source_counts(class_plan, usable_sources(source_manifest))

        candidate_classes = [
            entry.name for entry in class_plan if entry.final_state in {"ready", "risky"}
        ]
        web_sources = collect_web_image_sources(source_manifest, candidate_classes)
        video_sources = collect_youtube_video_sources(source_manifest, candidate_classes)

        extracted_frames, extraction_notes = extract_video_frames(
            video_sources,
            job_paths,
            self.config,
            bootstrap.ffmpeg_available,
        )
        all_samples = normalize_sources_to_samples(web_sources, extracted_frames)
        accepted_samples, rejected_samples, frame_scores = score_and_filter_samples(
            all_samples,
            self.config.critic,
        )
        balanced_samples = rebalance_samples(
            accepted_samples,
            self.config.mix,
            self.config.budgets.max_accepted_samples,
        )

        admitted_for_labeling = determine_label_admission(
            class_plan,
            balanced_samples,
            self.config.critic,
        )
        class_map = {class_name: index for index, class_name in enumerate(admitted_for_labeling)}
        label_inputs = [
            sample
            for sample in balanced_samples
            if set(sample.class_names).intersection(admitted_for_labeling)
        ]
        label_records: list[LabelRecord] = []
        validation_errors: list[LabelRecord] = []

        if admitted_for_labeling and label_inputs:
            provider = build_label_provider(self.config.label)
            limited_inputs = label_inputs[: self.config.budgets.max_label_calls]
            raw_labels = provider.label_samples(limited_inputs, admitted_for_labeling, class_map)
            label_records, validation_errors = validate_label_records(
                raw_labels,
                admitted_for_labeling,
                self.config.critic.min_label_confidence,
            )
        else:
            extraction_notes.append("No classes met the pre-labeling admission threshold.")

        class_plan = finalize_class_plan(
            class_plan,
            balanced_samples,
            label_records,
            self.config.critic,
        )
        admitted_for_training = [entry.name for entry in class_plan if entry.final_state == "ready"]

        filtered_labels = self._filter_labels_for_training(label_records, admitted_for_training)
        filtered_samples = [
            sample
            for sample in balanced_samples
            if sample.id in {record.sample_id for record in filtered_labels}
        ]
        dataset_result = build_dataset(
            job_paths,
            filtered_samples,
            filtered_labels,
            admitted_for_training,
        )
        training_result = train_dataset(dataset_result, job_paths, self.config.training)
        evaluation_report = evaluate_run(training_result, class_plan)
        iteration_decision = decide_next_step(evaluation_report, class_plan)

        source_breakdown = Counter(sample.source_type for sample in balanced_samples)
        notes = bootstrap.warnings + source_notes + extraction_notes

        artifacts = {
            "bootstrap": str(job_paths.reports / "bootstrap.json"),
            "class_plan": str(job_paths.reports / "class_plan.json"),
            "source_manifest": str(job_paths.reports / "source_manifest.json"),
            "sample_manifest": str(job_paths.reports / "sample_manifest.json"),
            "frame_scores": str(job_paths.reports / "frame_scores.json"),
            "accepted_frames": str(job_paths.reports / "accepted_frames.json"),
            "labels_manifest": str(job_paths.reports / "labels_manifest.json"),
            "dataset_manifest": str(job_paths.reports / "dataset_manifest.json"),
            "training_results": str(job_paths.reports / "training_results.json"),
            "evaluation_report": str(job_paths.reports / "evaluation_report.json"),
            "run_summary": str(job_paths.reports / "run_summary.json"),
        }

        write_json(Path(artifacts["bootstrap"]), bootstrap)
        write_json(Path(artifacts["class_plan"]), class_plan)
        write_json(Path(artifacts["source_manifest"]), source_manifest)
        write_json(Path(artifacts["sample_manifest"]), all_samples)
        write_json(Path(artifacts["frame_scores"]), frame_scores)
        write_json(Path(artifacts["accepted_frames"]), balanced_samples)
        write_json(Path(artifacts["labels_manifest"]), {"valid": label_records, "invalid": validation_errors})
        write_json(Path(artifacts["dataset_manifest"]), dataset_result)
        write_json(Path(artifacts["training_results"]), training_result)
        write_json(Path(artifacts["evaluation_report"]), evaluation_report)

        summary = RunSummary(
            job_id=self.config.job_id,
            prompt=self.config.prompt,
            requested_classes=requested_classes,
            admitted_classes=admitted_for_training,
            deferred_classes=[entry.name for entry in class_plan if entry.final_state == "risky"],
            blocked_classes=[entry.name for entry in class_plan if entry.final_state == "blocked"],
            source_breakdown=dict(source_breakdown),
            budgets={
                "max_runtime_seconds": self.config.budgets.max_runtime_seconds,
                "max_downloaded_sources": self.config.budgets.max_downloaded_sources,
                "max_label_calls": self.config.budgets.max_label_calls,
                "max_accepted_samples": self.config.budgets.max_accepted_samples,
            },
            notes=notes + iteration_decision.reasons,
            artifact_paths=artifacts,
        )
        write_json(Path(artifacts["run_summary"]), summary)
        return summary

    def _resolve_source_manifest(
        self,
        requested_classes: list[str],
        job_paths: JobPaths,
        bootstrap: BootstrapReport,
    ) -> tuple[list[SourceRecord], list[str]]:
        if self.config.source.source_mode == "manifest":
            return load_source_manifest(self.config.source.manifest_path), []

        notes: list[str] = []
        queries_by_class = generate_class_queries(self.config.prompt, requested_classes)
        web_candidates_by_class, web_notes = search_web_image_candidates(
            requested_classes,
            queries_by_class,
            self.config.source,
        )
        youtube_candidates_by_class, youtube_notes = search_youtube_candidates(
            requested_classes,
            queries_by_class,
            self.config.source,
            bootstrap.yt_dlp_available,
        )
        notes.extend(web_notes)
        notes.extend(youtube_notes)

        manifest_sources: list[SourceRecord] = []
        selected_by_id: dict[str, SourceRecord] = {}
        grouped_for_budget: dict[str, list[SourceRecord]] = {}

        for class_name in requested_classes:
            web_candidates = list(web_candidates_by_class.get(class_name, []))
            youtube_candidates = list(youtube_candidates_by_class.get(class_name, []))

            selected_web = web_candidates[: self.config.source.web_image_downloads_per_class]
            selected_youtube = youtube_candidates[: self.config.source.youtube_downloads_per_class]
            grouped_for_budget[class_name] = selected_web + selected_youtube

            for source in web_candidates[self.config.source.web_image_downloads_per_class :]:
                source.metadata["download_status"] = "skipped_candidate_limit"
                source.metadata["download_error"] = None
            for source in youtube_candidates[self.config.source.youtube_downloads_per_class :]:
                source.metadata["download_status"] = "skipped_candidate_limit"
                source.metadata["download_error"] = None

            manifest_sources.extend(web_candidates)
            manifest_sources.extend(youtube_candidates)

        selected_sources = round_robin_select(
            grouped_for_budget,
            self.config.budgets.max_downloaded_sources,
        )
        for source in selected_sources:
            selected_by_id[source.id] = source

        for source in manifest_sources:
            if source.id not in selected_by_id and "download_status" not in source.metadata:
                source.metadata["download_status"] = "skipped_budget"
                source.metadata["download_error"] = None

        selected_web_sources = [source for source in selected_sources if source.source_type == "web_image"]
        selected_video_sources = [
            source for source in selected_sources if source.source_type == "youtube_video"
        ]

        _, download_notes = download_image_sources(selected_web_sources, job_paths, self.config.source)
        notes.extend(download_notes)
        _, youtube_download_notes = download_youtube_sources(
            selected_video_sources,
            job_paths,
            self.config.source,
            bootstrap.yt_dlp_available,
        )
        notes.extend(youtube_download_notes)

        if not any(has_local_asset(source) for source in manifest_sources):
            notes.append("Live discovery produced no usable local sources.")

        return manifest_sources, notes

    @staticmethod
    def _build_job_paths(output_root: Path, job_id: str) -> JobPaths:
        root = ensure_dir(output_root / job_id)
        return JobPaths(
            root=root,
            downloads=ensure_dir(root / "downloads"),
            frames=ensure_dir(root / "frames"),
            labels=ensure_dir(root / "labels"),
            datasets=ensure_dir(root / "datasets"),
            models=ensure_dir(root / "models"),
            reports=ensure_dir(root / "reports"),
        )

    @staticmethod
    def _filter_labels_for_training(
        label_records: list[LabelRecord],
        admitted_classes: list[str],
    ) -> list[LabelRecord]:
        admitted_set = set(admitted_classes)
        filtered: list[LabelRecord] = []
        for record in label_records:
            boxes = [box for box in record.boxes if box.class_name in admitted_set]
            if not boxes:
                continue
            filtered.append(
                LabelRecord(
                    sample_id=record.sample_id,
                    provider=record.provider,
                    status=record.status,
                    boxes=boxes,
                    notes=record.notes,
                    label_path=record.label_path,
                )
            )
        return filtered
