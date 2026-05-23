from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .contracts import ClassQualityConfig, DatasetBuildResult, LabelRecord, SampleRecord, SourceMix
from .utils import read_json

REVIEW_STATES = {"pending", "approved", "relabel_requested", "rejected"}


def class_distribution(samples: list[SampleRecord], classes: list[str] | None = None) -> dict[str, int]:
    allowed = set(classes or [])
    counts: Counter[str] = Counter()
    for sample in samples:
        for class_name in sample.class_names:
            normalized = class_name.lower()
            if not allowed or normalized in allowed:
                counts[normalized] += 1
    if classes is None:
        return dict(sorted(counts.items()))
    return {class_name: counts.get(class_name, 0) for class_name in classes}


def select_class_aware_samples(
    samples: list[SampleRecord],
    *,
    classes: list[str],
    mix: SourceMix,
    max_samples: int,
    min_candidate_pool: int,
) -> tuple[list[SampleRecord], dict[str, Any]]:
    if not samples:
        return [], _empty_quality_report(classes)

    ranked = sorted(
        samples,
        key=lambda item: (
            0 if item.metadata.get("hard_negative_promoted") else 1,
            -(item.quality_score or 0.0),
            item.id,
        ),
    )
    limit = min(max_samples, len(ranked))
    if limit <= 0:
        return [], _empty_quality_report(classes)

    sample_classes = {
        sample.id: {class_name.lower() for class_name in sample.class_names if class_name}
        for sample in ranked
    }
    selected: list[SampleRecord] = []
    selected_ids: set[str] = set()
    class_counts: Counter[str] = Counter()

    def add_sample(sample: SampleRecord, pass_name: str) -> None:
        if sample.id in selected_ids or len(selected) >= limit:
            return
        before = {class_name: class_counts.get(class_name, 0) for class_name in classes}
        selected.append(sample)
        selected_ids.add(sample.id)
        for class_name in sample_classes.get(sample.id, set()):
            if class_name in classes:
                class_counts[class_name] += 1
        after = {class_name: class_counts.get(class_name, 0) for class_name in classes}
        delta = {class_name: after[class_name] - before[class_name] for class_name in classes}
        sample.metadata["class_coverage_delta"] = delta
        sample.metadata["minority_boost_applied"] = pass_name == "minority_protection"
        sample.metadata["selection_pass"] = pass_name

    # Pass 1: satisfy a per-class candidate pool before pure quality ranking.
    for class_name in classes:
        while class_counts[class_name] < min_candidate_pool and len(selected) < limit:
            candidate = next(
                (
                    sample
                    for sample in ranked
                    if sample.id not in selected_ids
                    and class_name in sample_classes.get(sample.id, set())
                ),
                None,
            )
            if candidate is None:
                break
            add_sample(candidate, "class_minimum_pool")

    # Pass 2: maximize quality while preserving minority-class coverage.
    for sample in ranked:
        if len(selected) >= limit:
            break
        if sample.id in selected_ids:
            continue
        classes_for_sample = sample_classes.get(sample.id, set()).intersection(classes)
        minority_boost = any(class_counts[class_name] < min_candidate_pool for class_name in classes_for_sample)
        add_sample(sample, "minority_protection" if minority_boost else "quality_rank")

    # Pass 3: enforce the configured source mix by replacing lowest-value overrepresented samples.
    selected = _apply_source_mix(selected, ranked, selected_ids, mix, limit, classes)

    selected_distribution = class_distribution(selected, classes)
    rejected_by_context = []
    selected_id_set = {sample.id for sample in selected}
    selected_class_counts = Counter()
    for sample in selected:
        for class_name in sample_classes.get(sample.id, set()).intersection(classes):
            selected_class_counts[class_name] += 1

    for sample in ranked:
        if sample.id in selected_id_set:
            continue
        sample_reason = "class-aware selection limit reached"
        sample_class_set = sample_classes.get(sample.id, set()).intersection(classes)
        if any(selected_class_counts[class_name] < min_candidate_pool for class_name in sample_class_set):
            sample_reason = "class-context rejected: insufficient quota capacity"
        sample.metadata["class_context_rejection_reason"] = sample_reason
        rejected_by_context.append({"sample_id": sample.id, "reason": sample_reason})

    report = {
        "enabled": True,
        "selection_passes": [
            "class_minimum_pool",
            "minority_protection",
            "source_mix",
        ],
        "before_distribution": class_distribution(samples, classes),
        "after_distribution": selected_distribution,
        "source_mix": dict(sorted(Counter(sample.source_type for sample in selected).items())),
        "rejected_by_class_context": rejected_by_context,
    }
    return selected, report


def update_frame_score_diagnostics(
    frame_scores: list[dict[str, object]],
    samples: list[SampleRecord],
) -> list[dict[str, object]]:
    samples_by_id = {sample.id: sample for sample in samples}
    for score in frame_scores:
        sample_id = str(score.get("sample_id", ""))
        sample = samples_by_id.get(sample_id)
        if sample is None:
            score.setdefault("class_coverage_delta", {})
            score.setdefault("minority_boost_applied", False)
            score.setdefault("class_context_rejection_reason", None)
            continue
        score["class_coverage_delta"] = sample.metadata.get("class_coverage_delta", {})
        score["minority_boost_applied"] = bool(sample.metadata.get("minority_boost_applied", False))
        score["class_context_rejection_reason"] = sample.metadata.get("class_context_rejection_reason")
    return frame_scores


def review_queue_summary(review_queue: dict[str, Any]) -> dict[str, int]:
    counts = {"pending": 0, "approved": 0, "relabel_requested": 0, "rejected": 0, "total": 0}
    for item in review_queue.get("items", []):
        state = str(item.get("state", "pending"))
        if state in counts:
            counts[state] += 1
        counts["total"] += 1
    return counts


def review_gate(review_queue: dict[str, Any]) -> dict[str, Any]:
    summary = review_queue_summary(review_queue)
    pending_count = summary.get("pending", 0)
    status = "passed" if pending_count == 0 else "blocked"
    reasons = [] if status == "passed" else [f"{pending_count} review item(s) are still pending."]
    return {"status": status, "pending_count": pending_count, "reasons": reasons}


def build_class_quota_gate(
    dataset_result: DatasetBuildResult,
    admitted_classes: list[str],
    config: ClassQualityConfig,
) -> dict[str, Any]:
    per_class: dict[str, dict[str, Any]] = {}
    blocked = False

    for class_name in admitted_classes:
        split_counts = dataset_result.class_split_counts.get(class_name, {})
        train_count = int(split_counts.get("train", 0))
        val_count = int(split_counts.get("val", 0))
        reasons: list[str] = []
        if train_count < config.min_train_samples:
            reasons.append(
                f"train count {train_count} is below minimum {config.min_train_samples}"
            )
        if val_count < config.min_val_samples:
            reasons.append(f"val count {val_count} is below minimum {config.min_val_samples}")
        status = "passed" if not reasons else "blocked"
        blocked = blocked or bool(reasons)
        per_class[class_name] = {
            "status": status,
            "train": train_count,
            "val": val_count,
            "min_train_samples": config.min_train_samples,
            "min_val_samples": config.min_val_samples,
            "reasons": reasons,
        }

    return {
        "status": "blocked" if blocked else "passed",
        "per_class": per_class,
        "reasons": [
            f"{class_name}: {reason}"
            for class_name, payload in per_class.items()
            for reason in payload["reasons"]
        ],
    }


def build_per_class_counts(
    classes: list[str],
    accepted_samples: list[SampleRecord],
    label_records: list[LabelRecord],
    dataset_result: DatasetBuildResult,
) -> dict[str, dict[str, int]]:
    accepted_counts = class_distribution(accepted_samples, classes)
    labeled_counts: Counter[str] = Counter()
    for record in label_records:
        seen_in_sample = {box.class_name for box in record.boxes if box.class_name in classes}
        for class_name in seen_in_sample:
            labeled_counts[class_name] += 1

    counts: dict[str, dict[str, int]] = {}
    for class_name in classes:
        split_counts = dataset_result.class_split_counts.get(class_name, {})
        counts[class_name] = {
            "accepted": accepted_counts.get(class_name, 0),
            "labeled": labeled_counts.get(class_name, 0),
            "train": int(split_counts.get("train", 0)),
            "val": int(split_counts.get("val", 0)),
        }
    return counts


def mine_hard_negative_candidates(
    output_root: Path,
    current_job_id: str,
    classes: list[str],
    top_k: int,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    if top_k <= 0 or not output_root.exists():
        return {"status": "skipped", "candidates": [], "summary": {"top_k": top_k, "count": 0}}

    for reports_dir in sorted(output_root.glob("*/reports")):
        run_id = reports_dir.parent.name
        if run_id == current_job_id:
            continue
        labels_path = reports_dir / "labels_manifest.json"
        evaluation_path = reports_dir / "evaluation_report.json"
        predictions_path = reports_dir / "predictions.json"

        labels_payload = _safe_read_json(labels_path)
        evaluation_payload = _safe_read_json(evaluation_path)
        predictions_payload = _safe_read_json(predictions_path)
        weak_classes = {
            str(item)
            for item in (evaluation_payload.get("weak_classes", []) if isinstance(evaluation_payload, dict) else [])
        }

        for record in _label_records_from_payload(labels_payload):
            sample_id = str(record.get("sample_id", ""))
            for box in record.get("boxes", []):
                class_name = str(box.get("class_name", "")).lower()
                if class_name not in classes:
                    continue
                for confused_with in sorted(set(classes) - {class_name}):
                    weak_boost = 0.2 if class_name in weak_classes or confused_with in weak_classes else 0.0
                    confidence = float(box.get("confidence", 0.0))
                    score = round((1.0 - min(max(confidence, 0.0), 1.0)) + weak_boost, 6)
                    candidates.append(
                        {
                            "sample_id": sample_id,
                            "source_run_id": run_id,
                            "target_class": class_name,
                            "confused_with": confused_with,
                            "score": score,
                            "reason": "prior label near similar requested class pair",
                        }
                    )

        for item in _prediction_items(predictions_payload):
            true_class = str(item.get("true_class", "")).lower()
            predicted_class = str(item.get("predicted_class", "")).lower()
            if true_class in classes and predicted_class in classes and true_class != predicted_class:
                candidates.append(
                    {
                        "sample_id": str(item.get("sample_id", "")),
                        "source_run_id": run_id,
                        "target_class": true_class,
                        "confused_with": predicted_class,
                        "score": round(float(item.get("confidence", 0.5)) + 0.5, 6),
                        "reason": "prior prediction confused requested classes",
                    }
                )

    ranked = sorted(
        candidates,
        key=lambda item: (
            -float(item["score"]),
            str(item["source_run_id"]),
            str(item["sample_id"]),
            str(item["target_class"]),
            str(item["confused_with"]),
        ),
    )
    selected = ranked[:top_k]
    return {
        "status": "completed",
        "candidates": selected,
        "summary": {
            "top_k": top_k,
            "count": len(selected),
            "scanned_run_count": len({item["source_run_id"] for item in ranked}),
        },
    }


def promote_hard_negative_samples(
    samples: list[SampleRecord],
    hard_negative_report: dict[str, Any],
) -> list[SampleRecord]:
    candidate_ids = [
        str(item.get("sample_id"))
        for item in hard_negative_report.get("candidates", [])
        if item.get("sample_id")
    ]
    if not candidate_ids:
        return samples
    priority = {sample_id: index for index, sample_id in enumerate(candidate_ids)}
    for sample in samples:
        if sample.id in priority:
            sample.metadata["hard_negative_promoted"] = True
    return sorted(samples, key=lambda sample: (priority.get(sample.id, len(priority)), sample.id))


def _empty_quality_report(classes: list[str]) -> dict[str, Any]:
    return {
        "enabled": True,
        "selection_passes": [],
        "before_distribution": {class_name: 0 for class_name in classes},
        "after_distribution": {class_name: 0 for class_name in classes},
        "source_mix": {},
        "rejected_by_class_context": [],
    }


def _apply_source_mix(
    selected: list[SampleRecord],
    ranked: list[SampleRecord],
    selected_ids: set[str],
    mix: SourceMix,
    limit: int,
    classes: list[str],
) -> list[SampleRecord]:
    if len(selected) >= limit:
        return selected

    target_web = round(limit * mix.web_target_ratio)
    target_video = limit - target_web
    selected_list = list(selected)
    web_count = sum(1 for sample in selected_list if sample.source_type == "web_image")
    video_count = len(selected_list) - web_count

    for sample in ranked:
        if len(selected_list) >= limit:
            break
        if sample.id in selected_ids:
            continue
        if sample.source_type == "web_image" and web_count >= target_web and video_count < target_video:
            continue
        if sample.source_type != "web_image" and video_count >= target_video and web_count < target_web:
            continue
        sample.metadata["selection_pass"] = "source_mix"
        sample.metadata.setdefault("minority_boost_applied", False)
        sample.metadata.setdefault("class_coverage_delta", {class_name: 0 for class_name in classes})
        selected_list.append(sample)
        selected_ids.add(sample.id)
        if sample.source_type == "web_image":
            web_count += 1
        else:
            video_count += 1

    return selected_list


def _safe_read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def _label_records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        records = payload.get("valid", [])
    elif isinstance(payload, list):
        records = payload
    else:
        records = []
    return [record for record in records if isinstance(record, dict)]


def _prediction_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("predictions", [])
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]
