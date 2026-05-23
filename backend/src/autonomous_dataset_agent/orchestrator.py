from __future__ import annotations

import time
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
from .class_quality import (
    build_class_quota_gate,
    build_per_class_counts,
    mine_hard_negative_candidates,
    promote_hard_negative_samples,
    review_gate,
    review_queue_summary,
    select_class_aware_samples,
    update_frame_score_diagnostics,
)
from .config import JobConfig
from .contracts import BootstrapReport, JobPaths, LabelRecord, RunSummary, SourceRecord
from .critic import score_and_filter_samples
from .dataset_builder import build_dataset
from .downloaders import download_image_sources, normalize_url, round_robin_select
from .evaluation import evaluate_run
from .governance import (
    allowed_sources_for_ingestion,
    build_artifact_lifecycle,
    build_audit_log,
    build_lineage_manifest,
    build_version_manifest,
    governance_summary,
    validate_source_licenses,
)
from .iteration import decide_next_step
from .iteration_policy import BudgetState, load_last_promoted_baseline
from .labeling import build_label_provider, validate_label_records, validate_label_records_with_review
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
from .run_lifecycle import PipelineRunContext, StageName
from .utils import ensure_dir, write_json
from .web_search import search_web_image_candidates
from .youtube_search import download_youtube_sources, search_youtube_candidates


class PipelineRunner:
    def __init__(self, config: JobConfig, run_context: PipelineRunContext | None = None) -> None:
        self.config = config
        self._run_context = run_context or PipelineRunContext()

    def set_run_context(self, run_context: PipelineRunContext) -> None:
        self._run_context = run_context

    def run(self) -> RunSummary:
        started_at_monotonic = time.monotonic()
        bootstrap, job_paths = self._run_stage(
            "bootstrap",
            lambda: (
                run_bootstrap_checks(
                    self.config.source.ffmpeg_path,
                    self.config.source.yt_dlp_path,
                ),
                self._build_job_paths(self.config.output_root, self.config.job_id),
            ),
        )
        requested_classes, class_plan = self._run_stage(
            "class_planning",
            lambda: self._plan_classes(),
        )
        source_manifest, source_notes, web_sources, video_sources, class_plan, license_report = self._run_stage(
            "source_resolution",
            lambda: self._resolve_sources(job_paths, bootstrap, requested_classes, class_plan),
        )
        _extracted_frames, extraction_notes, all_samples = self._run_stage(
            "frame_extraction",
            lambda: self._extract_samples(video_sources, web_sources, job_paths, bootstrap),
        )
        balanced_samples, frame_scores, class_plan, admitted_for_labeling, class_quality_report, hard_negative_report = self._run_stage(
            "critic",
            lambda: self._critic_stage(all_samples, class_plan, job_paths),
        )
        label_records, validation_errors, review_queue, class_plan, extraction_notes, label_calls_used = self._label_stage(
            class_plan,
            balanced_samples,
            admitted_for_labeling,
            extraction_notes,
        )
        admitted_for_training = [entry.name for entry in class_plan if entry.final_state == "ready"]

        filtered_labels = self._filter_labels_for_training(label_records, admitted_for_training)
        filtered_samples = [
            sample
            for sample in balanced_samples
            if sample.id in {record.sample_id for record in filtered_labels}
        ]
        dataset_result = self._run_stage(
            "dataset_build",
            lambda: build_dataset(
                job_paths,
                filtered_samples,
                filtered_labels,
                admitted_for_training,
            ),
        )
        review_gate_result = review_gate(review_queue) if self._class_quality_enabled() else {"status": "passed", "pending_count": 0, "reasons": []}
        quota_gate = (
            build_class_quota_gate(dataset_result, admitted_for_training, self.config.class_quality)
            if self._class_quality_enabled()
            else {"status": "passed", "per_class": {}, "reasons": []}
        )
        if self.config.training.enabled and quota_gate.get("status") == "blocked":
            blocked_by_quota = set(quota_gate.get("per_class", {}))
            for entry in class_plan:
                if entry.name in blocked_by_quota and quota_gate["per_class"][entry.name]["status"] == "blocked":
                    entry.final_state = "blocked"
                    entry.reasons.extend(quota_gate["per_class"][entry.name]["reasons"])

        training_result = self._run_stage(
            "training",
            lambda: train_dataset(
                dataset_result,
                job_paths,
                self.config.training,
                review_gate=review_gate_result,
                quota_gate=quota_gate,
                compliance_gate=license_report,
            ),
        )
        evaluation_report = self._run_stage(
            "evaluation",
            lambda: evaluate_run(training_result, class_plan),
        )
        policy_target_classes = admitted_for_training or requested_classes
        promoted_baseline = load_last_promoted_baseline(
            self.config.output_root,
            current_job_id=self.config.job_id,
            target_classes=policy_target_classes,
        )
        iteration_decision = self._run_stage(
            "iteration",
            lambda: decide_next_step(
                evaluation_report,
                class_plan,
                self.config.iteration_policy,
                budget_state=BudgetState(
                    current_iteration=self.config.iteration_policy.current_iteration,
                    elapsed_runtime_seconds=time.monotonic() - started_at_monotonic,
                    label_calls_used=label_calls_used,
                    max_iterations=self.config.iteration_policy.max_iterations,
                    max_runtime_seconds=self.config.iteration_policy.max_runtime_seconds,
                    max_label_calls=self.config.iteration_policy.max_label_calls,
                ),
                target_classes=policy_target_classes,
                baseline=promoted_baseline,
            ),
        )

        source_breakdown = Counter(sample.source_type for sample in balanced_samples)
        notes = bootstrap.warnings + source_notes + extraction_notes

        return self._run_stage(
            "finalize",
            lambda: self._finalize_run(
                bootstrap=bootstrap,
                job_paths=job_paths,
                requested_classes=requested_classes,
                class_plan=class_plan,
                source_manifest=source_manifest,
                all_samples=all_samples,
                frame_scores=frame_scores,
                balanced_samples=balanced_samples,
                label_records=label_records,
                validation_errors=validation_errors,
                review_queue=review_queue,
                class_quality_report=class_quality_report,
                hard_negative_report=hard_negative_report,
                license_report=license_report,
                review_gate_result=review_gate_result,
                quota_gate=quota_gate,
                dataset_result=dataset_result,
                training_result=training_result,
                evaluation_report=evaluation_report,
                iteration_decision=iteration_decision,
                source_breakdown=dict(source_breakdown),
                notes=notes,
                admitted_for_training=admitted_for_training,
            ),
        )

    def _run_stage(self, stage_name: StageName, func):
        self._run_context.start_stage(stage_name)
        try:
            result = func()
        except Exception:
            self._run_context.fail_stage(stage_name)
            raise
        self._run_context.complete_stage(stage_name)
        return result

    def _resolve_sources(
        self,
        job_paths: JobPaths,
        bootstrap: BootstrapReport,
        requested_classes: list[str],
        class_plan,
    ):
        source_manifest, source_notes = self._resolve_source_manifest(
            requested_classes,
            job_paths,
            bootstrap,
        )
        license_report = validate_source_licenses(source_manifest, self.config.governance)
        allowed_source_manifest = allowed_sources_for_ingestion(
            source_manifest,
            license_report,
            self.config.governance,
        )
        blocked_count = license_report.get("summary", {}).get("blocked", 0)
        if blocked_count:
            source_notes.append(f"Governance blocked {blocked_count} source(s) from ingestion.")

        class_plan = attach_source_counts(class_plan, usable_sources(allowed_source_manifest))
        candidate_classes = [
            entry.name for entry in class_plan if entry.final_state in {"ready", "risky"}
        ]
        web_sources = collect_web_image_sources(allowed_source_manifest, candidate_classes)
        video_sources = collect_youtube_video_sources(allowed_source_manifest, candidate_classes)
        return source_manifest, source_notes, web_sources, video_sources, class_plan, license_report

    def _plan_classes(self) -> tuple[list[str], list]:
        requested_classes = normalize_classes(self.config.classes)
        class_plan = build_initial_class_plan(self.config.prompt, requested_classes)
        return requested_classes, class_plan

    def _extract_samples(
        self,
        video_sources,
        web_sources,
        job_paths: JobPaths,
        bootstrap: BootstrapReport,
    ):
        extracted_frames, extraction_notes = extract_video_frames(
            video_sources,
            job_paths,
            self.config,
            bootstrap.ffmpeg_available,
        )
        all_samples = normalize_sources_to_samples(web_sources, extracted_frames)
        return extracted_frames, extraction_notes, all_samples

    def _critic_stage(self, all_samples, class_plan, job_paths: JobPaths):
        accepted_samples, rejected_samples, frame_scores = score_and_filter_samples(
            all_samples,
            self.config.critic,
        )
        requested_classes = [entry.name for entry in class_plan if entry.final_state != "blocked"]
        hard_negative_report = (
            mine_hard_negative_candidates(
                self.config.output_root,
                self.config.job_id,
                requested_classes,
                self.config.class_quality.hard_negative_top_k,
            )
            if self._class_quality_enabled()
            else {"status": "disabled", "candidates": [], "summary": {"count": 0}}
        )
        promoted_samples = promote_hard_negative_samples(accepted_samples, hard_negative_report)
        if self._class_quality_enabled():
            balanced_samples, class_quality_report = select_class_aware_samples(
                promoted_samples,
                classes=requested_classes,
                mix=self.config.mix,
                max_samples=self.config.budgets.max_accepted_samples,
                min_candidate_pool=self.config.critic.min_samples_to_label,
            )
            frame_scores = update_frame_score_diagnostics(frame_scores, accepted_samples + rejected_samples)
        else:
            balanced_samples = rebalance_samples(
                accepted_samples,
                self.config.mix,
                self.config.budgets.max_accepted_samples,
                self.config.critic.min_samples_to_label,
            )
            class_quality_report = {
                "enabled": False,
                "legacy_mode": True,
                "before_distribution": {},
                "after_distribution": {},
            }
        admitted_for_labeling = determine_label_admission(
            class_plan,
            balanced_samples,
            self.config.critic,
        )
        del rejected_samples
        return balanced_samples, frame_scores, class_plan, admitted_for_labeling, class_quality_report, hard_negative_report

    def _label_stage(
        self,
        class_plan,
        balanced_samples,
        admitted_for_labeling,
        extraction_notes: list[str],
    ):
        label_records: list[LabelRecord] = []
        validation_errors: list[LabelRecord] = []
        label_calls_used = 0
        review_queue: dict[str, object] = {
            "schema_version": 1,
            "states": ["pending", "approved", "relabel_requested", "rejected"],
            "items": [],
        }
        label_inputs = [
            sample
            for sample in balanced_samples
            if set(sample.class_names).intersection(admitted_for_labeling)
        ]

        if admitted_for_labeling and label_inputs:
            def perform_labeling():
                class_map = {class_name: index for index, class_name in enumerate(admitted_for_labeling)}
                provider = build_label_provider(self.config.label)
                limited_inputs = label_inputs[: self.config.budgets.max_label_calls]
                raw_labels = provider.label_samples(limited_inputs, admitted_for_labeling, class_map)
                if self._class_quality_enabled():
                    valid, invalid, queue = validate_label_records_with_review(
                        raw_labels,
                        admitted_for_labeling,
                        self.config.critic.min_label_confidence,
                        self.config.class_quality,
                    )
                    return valid, invalid, queue, len(limited_inputs)
                valid, invalid = validate_label_records(
                    raw_labels,
                    admitted_for_labeling,
                    self.config.critic.min_label_confidence,
                )
                return valid, invalid, review_queue, len(limited_inputs)

            label_records, validation_errors, review_queue, label_calls_used = self._run_stage("labeling", perform_labeling)
        else:
            self._run_context.checkpoint()
            self._run_context.skip_stage("labeling")
            extraction_notes.append("No classes met the pre-labeling admission threshold.")

        class_plan = finalize_class_plan(
            class_plan,
            balanced_samples,
            label_records,
            self.config.critic,
        )
        return label_records, validation_errors, review_queue, class_plan, extraction_notes, label_calls_used

    def _finalize_run(
        self,
        *,
        bootstrap: BootstrapReport,
        job_paths: JobPaths,
        requested_classes: list[str],
        class_plan,
        source_manifest,
        all_samples,
        frame_scores,
        balanced_samples,
        label_records: list[LabelRecord],
        validation_errors: list[LabelRecord],
        review_queue: dict[str, object],
        class_quality_report: dict[str, object],
        hard_negative_report: dict[str, object],
        license_report: dict[str, object],
        review_gate_result: dict[str, object],
        quota_gate: dict[str, object],
        dataset_result,
        training_result,
        evaluation_report,
        iteration_decision,
        source_breakdown: dict[str, int],
        notes: list[str],
        admitted_for_training: list[str],
    ) -> RunSummary:
        artifacts = {
            "bootstrap": str(job_paths.reports / "bootstrap.json"),
            "class_plan": str(job_paths.reports / "class_plan.json"),
            "source_manifest": str(job_paths.reports / "source_manifest.json"),
            "sample_manifest": str(job_paths.reports / "sample_manifest.json"),
            "frame_scores": str(job_paths.reports / "frame_scores.json"),
            "accepted_frames": str(job_paths.reports / "accepted_frames.json"),
            "labels_manifest": str(job_paths.reports / "labels_manifest.json"),
            "class_quality_report": str(job_paths.reports / "class_quality_report.json"),
            "review_queue": str(job_paths.reports / "review_queue.json"),
            "hard_negative_candidates": str(job_paths.reports / "hard_negative_candidates.json"),
            "class_quota_gate": str(job_paths.reports / "class_quota_gate.json"),
            "dataset_manifest": str(job_paths.reports / "dataset_manifest.json"),
            "training_results": str(job_paths.reports / "training_results.json"),
            "evaluation_report": str(job_paths.reports / "evaluation_report.json"),
            "iteration_policy_report": str(job_paths.reports / "iteration_policy_report.json"),
            "baseline_comparison": str(job_paths.reports / "baseline_comparison.json"),
            "promotion_guard": str(job_paths.reports / "promotion_guard.json"),
            "lineage_manifest": str(job_paths.reports / "lineage_manifest.json"),
            "version_manifest": str(job_paths.reports / "version_manifest.json"),
            "license_compliance_report": str(job_paths.reports / "license_compliance_report.json"),
            "audit_log": str(job_paths.reports / "audit_log.json"),
            "artifact_lifecycle": str(job_paths.reports / "artifact_lifecycle.json"),
            "run_summary": str(job_paths.reports / "run_summary.json"),
        }

        version_manifest = build_version_manifest(
            job_id=self.config.job_id,
            source_manifest=source_manifest,
            all_samples=all_samples,
            accepted_samples=balanced_samples,
            label_records=label_records,
            dataset_result=dataset_result,
            training_result=training_result,
            iteration_decision=iteration_decision,
        )
        lineage_manifest = build_lineage_manifest(
            job_id=self.config.job_id,
            source_manifest=source_manifest,
            all_samples=all_samples,
            accepted_samples=balanced_samples,
            label_records=label_records,
            dataset_result=dataset_result,
            version_manifest=version_manifest,
            iteration_decision=iteration_decision,
        )
        audit_log = build_audit_log(
            job_id=self.config.job_id,
            license_report=license_report,
            review_queue=review_queue,
            iteration_decision=iteration_decision,
        )
        artifact_lifecycle = build_artifact_lifecycle(
            artifacts,
            self.config.governance,
            export_status=str(license_report.get("export_status", "unknown")),
        )
        governance_report_summary = governance_summary(
            license_report,
            lineage_manifest,
            version_manifest,
            audit_log,
            artifact_lifecycle,
        )

        write_json(Path(artifacts["bootstrap"]), bootstrap)
        write_json(Path(artifacts["class_plan"]), class_plan)
        write_json(Path(artifacts["source_manifest"]), source_manifest)
        write_json(Path(artifacts["sample_manifest"]), all_samples)
        write_json(Path(artifacts["frame_scores"]), frame_scores)
        write_json(Path(artifacts["accepted_frames"]), balanced_samples)
        write_json(Path(artifacts["labels_manifest"]), {"valid": label_records, "invalid": validation_errors})
        write_json(Path(artifacts["class_quality_report"]), class_quality_report)
        write_json(Path(artifacts["review_queue"]), review_queue)
        write_json(Path(artifacts["hard_negative_candidates"]), hard_negative_report)
        write_json(Path(artifacts["class_quota_gate"]), quota_gate)
        write_json(Path(artifacts["dataset_manifest"]), dataset_result)
        write_json(Path(artifacts["training_results"]), training_result)
        write_json(Path(artifacts["evaluation_report"]), evaluation_report)
        write_json(Path(artifacts["iteration_policy_report"]), iteration_decision.policy_report)
        write_json(Path(artifacts["baseline_comparison"]), iteration_decision.baseline_comparison)
        write_json(Path(artifacts["promotion_guard"]), iteration_decision.promotion_guard)
        write_json(Path(artifacts["lineage_manifest"]), lineage_manifest)
        write_json(Path(artifacts["version_manifest"]), version_manifest)
        write_json(Path(artifacts["license_compliance_report"]), license_report)
        write_json(Path(artifacts["audit_log"]), audit_log)
        write_json(Path(artifacts["artifact_lifecycle"]), artifact_lifecycle)

        per_class_counts = build_per_class_counts(
            requested_classes,
            balanced_samples,
            label_records,
            dataset_result,
        )
        review_summary = review_queue_summary(review_queue)
        gate_notes = []
        if review_gate_result.get("status") == "blocked":
            gate_notes.extend(str(reason) for reason in review_gate_result.get("reasons", []))
        if quota_gate.get("status") == "blocked":
            gate_notes.extend(str(reason) for reason in quota_gate.get("reasons", []))
        if license_report.get("export_status") == "blocked":
            gate_notes.append("License compliance gate blocked export/training.")

        summary = RunSummary(
            job_id=self.config.job_id,
            prompt=self.config.prompt,
            requested_classes=requested_classes,
            admitted_classes=admitted_for_training,
            deferred_classes=[entry.name for entry in class_plan if entry.final_state == "risky"],
            blocked_classes=[entry.name for entry in class_plan if entry.final_state == "blocked"],
            source_breakdown=source_breakdown,
            budgets={
                "max_runtime_seconds": self.config.budgets.max_runtime_seconds,
                "max_downloaded_sources": self.config.budgets.max_downloaded_sources,
                "max_label_calls": self.config.budgets.max_label_calls,
                "max_accepted_samples": self.config.budgets.max_accepted_samples,
            },
            notes=notes + gate_notes + iteration_decision.reasons + iteration_decision.warnings,
            artifact_paths=artifacts,
            per_class_counts=per_class_counts,
            quota_status=quota_gate,
            review_queue_summary=review_summary,
            hard_negative_summary=hard_negative_report.get("summary", {}),
            iteration_policy=iteration_decision.policy_report,
            baseline_comparison_summary=iteration_decision.baseline_comparison,
            promotion_guard_summary=iteration_decision.promotion_guard,
            governance_summary=governance_report_summary,
            lineage_summary=lineage_manifest.get("summary", {}),
            license_compliance=license_report,
            version_summary={
                "dataset_version_id": version_manifest.get("dataset_version_id"),
                "model_version_id": version_manifest.get("model_version_id"),
                "checksums": version_manifest.get("checksums", {}),
            },
            artifact_lifecycle=artifact_lifecycle.get("summary", {}),
        )
        write_json(Path(artifacts["run_summary"]), summary)
        return summary

    def _class_quality_enabled(self) -> bool:
        return self.config.class_quality.enabled and not self.config.class_quality.opt_out_legacy_mode

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
        selected_source_ids = {source.id for source in selected_sources}
        canonical_selected_sources = self._canonicalize_selected_sources(selected_sources)

        for source in manifest_sources:
            if source.id not in selected_source_ids and "download_status" not in source.metadata:
                source.metadata["download_status"] = "skipped_budget"
                source.metadata["download_error"] = None

        selected_web_sources = [
            source for source in canonical_selected_sources if source.source_type == "web_image"
        ]
        selected_video_sources = [
            source for source in canonical_selected_sources if source.source_type == "youtube_video"
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
    def _canonicalize_selected_sources(selected_sources: list[SourceRecord]) -> list[SourceRecord]:
        canonical_by_key: dict[tuple[str, str], SourceRecord] = {}
        canonical_order: list[SourceRecord] = []

        for source in selected_sources:
            raw_key = source.url or source.id
            normalized_key = normalize_url(raw_key) if source.url else raw_key
            key = (source.source_type, normalized_key)
            existing = canonical_by_key.get(key)
            if existing is None:
                source.class_names = list(dict.fromkeys(value.lower() for value in source.class_names))
                canonical_by_key[key] = source
                canonical_order.append(source)
                continue

            existing.class_names = list(
                dict.fromkeys(
                    [
                        *(value.lower() for value in existing.class_names),
                        *(value.lower() for value in source.class_names),
                    ]
                )
            )
            merged_ids = set(existing.metadata.get("merged_source_ids", []))
            merged_ids.add(source.id)
            existing.metadata["merged_source_ids"] = sorted(merged_ids)
            source.metadata["download_status"] = "skipped_shared_source"
            source.metadata["download_error"] = None
            source.metadata["canonical_source_id"] = existing.id

        return canonical_order

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
