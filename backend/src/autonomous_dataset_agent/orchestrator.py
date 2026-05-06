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
from .contracts import JobPaths, LabelRecord, RunSummary
from .critic import score_and_filter_samples
from .dataset_builder import build_dataset
from .evaluation import evaluate_run
from .iteration import decide_next_step
from .labeling import build_label_provider, validate_label_records
from .sources import (
    collect_web_image_sources,
    collect_youtube_video_sources,
    extract_video_frames,
    load_source_manifest,
    normalize_sources_to_samples,
    rebalance_samples,
)
from .training import train_dataset
from .utils import ensure_dir, write_json


class PipelineRunner:
    def __init__(self, config: JobConfig) -> None:
        self.config = config

    def run(self) -> RunSummary:
        bootstrap = run_bootstrap_checks(self.config.source.ffmpeg_path)
        job_paths = self._build_job_paths(self.config.output_root, self.config.job_id)
        requested_classes = normalize_classes(self.config.classes)

        class_plan = build_initial_class_plan(self.config.prompt, requested_classes)
        source_manifest = load_source_manifest(self.config.source.manifest_path)
        class_plan = attach_source_counts(class_plan, source_manifest)

        candidate_classes = [
            entry.name for entry in class_plan if entry.final_state in {"ready", "risky"}
        ]
        web_sources = collect_web_image_sources(source_manifest, candidate_classes)
        video_sources = collect_youtube_video_sources(source_manifest, candidate_classes)
        total_source_budget = self.config.budgets.max_downloaded_sources
        web_sources = web_sources[:total_source_budget]
        remaining_budget = max(0, total_source_budget - len(web_sources))
        video_sources = video_sources[:remaining_budget]

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
        notes = bootstrap.warnings + extraction_notes

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
