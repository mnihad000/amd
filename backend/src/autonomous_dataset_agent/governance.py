from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from .contracts import (
    DatasetBuildResult,
    GovernanceConfig,
    IterationDecision,
    LabelRecord,
    SampleRecord,
    SourceRecord,
    TrainingResult,
)
from .utils import dataclass_to_dict


def stable_checksum(payload: Any) -> str:
    normalized = dataclass_to_dict(payload)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_source_licenses(
    sources: list[SourceRecord],
    config: GovernanceConfig,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    if not config.enabled:
        return {
            "schema_version": 1,
            "status": "disabled",
            "ingestion_status": "passed",
            "export_status": "passed",
            "summary": {"total_sources": len(sources), "allowed": len(sources), "blocked": 0},
            "sources": [],
            "violations": [],
        }

    effective_today = today or date.today()
    rows: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for source in sorted(sources, key=lambda item: item.id):
        license_metadata = source_license_metadata(source)
        reasons = _license_violation_reasons(source, license_metadata, config, effective_today)
        status = "blocked" if reasons else "allowed"
        source.metadata["license_compliance_status"] = status
        source.metadata["license_compliance_reasons"] = reasons
        if license_metadata:
            source.metadata.setdefault("license", license_metadata)

        row = {
            "source_id": source.id,
            "source_type": source.source_type,
            "class_names": sorted(source.class_names),
            "status": status,
            "origin": license_metadata.get("origin"),
            "license_type": license_metadata.get("license_type"),
            "usage_rights": _normalized_rights(license_metadata.get("usage_rights")),
            "expiration": license_metadata.get("expiration"),
            "restrictions": _normalized_restrictions(license_metadata.get("restrictions")),
            "reasons": reasons,
        }
        rows.append(row)
        if reasons:
            violations.append(
                {
                    "source_id": source.id,
                    "reasons": reasons,
                    "phase": "ingestion",
                    "blocking": config.block_ingestion_on_violation,
                }
            )

    blocked_count = len(violations)
    ingestion_status = "blocked" if blocked_count and config.block_ingestion_on_violation else "passed"
    export_status = "blocked" if blocked_count and config.block_export_on_violation else "passed"
    return {
        "schema_version": 1,
        "status": "blocked" if ingestion_status == "blocked" or export_status == "blocked" else "passed",
        "ingestion_status": ingestion_status,
        "export_status": export_status,
        "policy": {
            "require_license_metadata": config.require_license_metadata,
            "require_provenance": config.require_provenance,
            "block_ingestion_on_violation": config.block_ingestion_on_violation,
            "block_export_on_violation": config.block_export_on_violation,
            "allowed_usage_rights": sorted(config.allowed_usage_rights),
        },
        "summary": {
            "total_sources": len(sources),
            "allowed": len(rows) - blocked_count,
            "blocked": blocked_count,
        },
        "sources": rows,
        "violations": violations,
    }


def allowed_sources_for_ingestion(
    sources: list[SourceRecord],
    license_report: dict[str, Any],
    config: GovernanceConfig,
) -> list[SourceRecord]:
    if not config.enabled or not config.block_ingestion_on_violation:
        return list(sources)
    blocked_ids = {
        str(item.get("source_id"))
        for item in license_report.get("sources", [])
        if isinstance(item, dict) and item.get("status") == "blocked"
    }
    return [source for source in sources if source.id not in blocked_ids]


def source_license_metadata(source: SourceRecord) -> dict[str, Any]:
    if isinstance(source.license, dict) and source.license:
        return dict(source.license)
    metadata_license = source.metadata.get("license")
    if isinstance(metadata_license, dict):
        return dict(metadata_license)
    return {}


def build_version_manifest(
    *,
    job_id: str,
    source_manifest: list[SourceRecord],
    all_samples: list[SampleRecord],
    accepted_samples: list[SampleRecord],
    label_records: list[LabelRecord],
    dataset_result: DatasetBuildResult,
    training_result: TrainingResult,
    iteration_decision: IterationDecision,
) -> dict[str, Any]:
    dataset_payload = {
        "sources": _source_fingerprint_rows(source_manifest),
        "samples": _sample_fingerprint_rows(accepted_samples),
        "labels": _label_fingerprint_rows(label_records),
        "dataset": dataset_result,
    }
    model_payload = {
        "dataset": dataset_payload,
        "training": training_result,
        "iteration_action": iteration_decision.action,
    }
    source_manifest_checksum = stable_checksum(_source_fingerprint_rows(source_manifest))
    sample_manifest_checksum = stable_checksum(_sample_fingerprint_rows(all_samples))
    accepted_manifest_checksum = stable_checksum(_sample_fingerprint_rows(accepted_samples))
    labels_manifest_checksum = stable_checksum(_label_fingerprint_rows(label_records))
    dataset_manifest_checksum = stable_checksum(dataset_payload)
    model_manifest_checksum = stable_checksum(model_payload)

    return {
        "schema_version": 1,
        "job_id": job_id,
        "immutable": True,
        "checksums": {
            "source_manifest": source_manifest_checksum,
            "sample_manifest": sample_manifest_checksum,
            "accepted_frames": accepted_manifest_checksum,
            "labels_manifest": labels_manifest_checksum,
            "dataset_manifest": dataset_manifest_checksum,
            "model_manifest": model_manifest_checksum,
        },
        "dataset_version_id": f"dataset_{dataset_manifest_checksum[:16]}",
        "model_version_id": f"model_{model_manifest_checksum[:16]}",
        "promotion_decision": iteration_decision.action,
    }


def build_lineage_manifest(
    *,
    job_id: str,
    source_manifest: list[SourceRecord],
    all_samples: list[SampleRecord],
    accepted_samples: list[SampleRecord],
    label_records: list[LabelRecord],
    dataset_result: DatasetBuildResult,
    version_manifest: dict[str, Any],
    iteration_decision: IterationDecision,
) -> dict[str, Any]:
    del all_samples
    sources_by_id = {source.id: source for source in source_manifest}
    labels_by_sample = {record.sample_id: record for record in label_records}
    accepted_ids = {sample.id for sample in accepted_samples}
    sample_rows: list[dict[str, Any]] = []

    for sample in sorted(accepted_samples, key=lambda item: item.id):
        source = sources_by_id.get(sample.source_id) or sources_by_id.get(sample.derived_from or "")
        label = labels_by_sample.get(sample.id)
        sample_rows.append(
            {
                "source_id": sample.source_id,
                "source_type": source.source_type if source else sample.source_type,
                "frame_or_sample_id": sample.id,
                "accepted_sample_id": sample.id if sample.id in accepted_ids else None,
                "derived_from": sample.derived_from,
                "label_sample_id": label.sample_id if label else None,
                "label_status": label.status if label else "missing",
                "split": _split_from_label_path(label.label_path if label else None),
                "dataset_version_id": version_manifest["dataset_version_id"],
                "model_version_id": version_manifest["model_version_id"],
                "promotion_decision": iteration_decision.action,
            }
        )

    manifest = {
        "schema_version": 1,
        "job_id": job_id,
        "dataset_status": dataset_result.status,
        "dataset_version_id": version_manifest["dataset_version_id"],
        "model_version_id": version_manifest["model_version_id"],
        "lineage": sample_rows,
        "summary": {
            "sources": len(source_manifest),
            "accepted_samples": len(accepted_samples),
            "labeled_samples": len(label_records),
            "lineage_records": len(sample_rows),
        },
    }
    manifest["checksum"] = stable_checksum({key: value for key, value in manifest.items() if key != "checksum"})
    return manifest


def build_audit_log(
    *,
    job_id: str,
    license_report: dict[str, Any],
    review_queue: dict[str, Any],
    iteration_decision: IterationDecision,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    sequence = 1

    def add_event(stage: str, event_type: str, action: str, context: dict[str, Any], actor: str = "system") -> None:
        nonlocal sequence
        base = {
            "sequence": sequence,
            "job_id": job_id,
            "actor": actor or "unknown",
            "stage": stage,
            "event_type": event_type,
            "action": action,
            "context": context,
        }
        base["event_id"] = f"audit_{stable_checksum(base)[:16]}"
        events.append(base)
        sequence += 1

    add_event("source_resolution", "automated_decision", "license_validation", license_report.get("summary", {}))
    for item in sorted(review_queue.get("items", []), key=lambda value: str(value.get("id", ""))):
        if not isinstance(item, dict):
            continue
        state = str(item.get("state", "pending"))
        if state == "pending":
            continue
        add_event(
            "review",
            "human_action",
            state,
            {
                "item_id": item.get("id"),
                "sample_id": item.get("sample_id"),
                "decision_notes": item.get("decision_notes", item.get("notes", [])),
            },
            actor=str(item.get("reviewer") or "unknown"),
        )
    add_event(
        "iteration",
        "automated_decision",
        str(iteration_decision.action),
        {
            "target_classes": iteration_decision.target_classes,
            "reasons": iteration_decision.reasons,
            "warnings": iteration_decision.warnings,
        },
    )

    return {
        "schema_version": 1,
        "job_id": job_id,
        "events": events,
        "summary": {
            "total_events": len(events),
            "automated_events": sum(1 for event in events if event["event_type"] == "automated_decision"),
            "human_events": sum(1 for event in events if event["event_type"] == "human_action"),
        },
    }


def build_artifact_lifecycle(
    artifacts: dict[str, str],
    config: GovernanceConfig,
    *,
    export_status: str,
) -> dict[str, Any]:
    rows = [
        {
            "artifact_name": name,
            "path": path,
            "lifecycle_status": config.lifecycle_status,
            "retention_policy": config.retention_policy,
            "delete_eligible": False,
            "export_status": export_status,
        }
        for name, path in sorted(artifacts.items())
    ]
    return {
        "schema_version": 1,
        "status": config.lifecycle_status,
        "retention_policy": config.retention_policy,
        "physical_deletion_enabled": False,
        "artifacts": rows,
        "summary": {"tracked_artifacts": len(rows), "export_status": export_status},
    }


def governance_summary(
    license_report: dict[str, Any],
    lineage_manifest: dict[str, Any],
    version_manifest: dict[str, Any],
    audit_log: dict[str, Any],
    lifecycle: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "blocked" if license_report.get("export_status") == "blocked" else "passed",
        "license_status": license_report.get("status", "unknown"),
        "ingestion_status": license_report.get("ingestion_status", "unknown"),
        "export_status": license_report.get("export_status", "unknown"),
        "blocked_source_count": license_report.get("summary", {}).get("blocked", 0),
        "lineage_records": lineage_manifest.get("summary", {}).get("lineage_records", 0),
        "dataset_version_id": version_manifest.get("dataset_version_id"),
        "model_version_id": version_manifest.get("model_version_id"),
        "audit_events": audit_log.get("summary", {}).get("total_events", 0),
        "lifecycle_status": lifecycle.get("status", "unknown"),
    }


def _license_violation_reasons(
    source: SourceRecord,
    license_metadata: dict[str, Any],
    config: GovernanceConfig,
    today: date,
) -> list[str]:
    reasons: list[str] = []
    if config.require_license_metadata and not license_metadata:
        return ["missing license metadata"]

    origin = str(license_metadata.get("origin", "")).strip()
    license_type = str(license_metadata.get("license_type", "")).strip()
    usage_rights = _normalized_rights(license_metadata.get("usage_rights"))
    restrictions = _normalized_restrictions(license_metadata.get("restrictions"))
    expiration = str(license_metadata.get("expiration", "")).strip()

    if config.require_provenance and not origin:
        reasons.append("missing origin")
    if not license_type:
        reasons.append("missing license type")
    if not usage_rights:
        reasons.append("missing usage rights")
    elif not set(usage_rights).intersection({right.lower() for right in config.allowed_usage_rights}):
        reasons.append("usage rights do not allow dataset/model training")
    if expiration and expiration < today.isoformat():
        reasons.append("license expired")
    if restrictions:
        reasons.append("license restrictions present")
    if not (source.url or source.local_path):
        reasons.append("missing source provenance path")
    return reasons


def _normalized_rights(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip().lower()] if value.strip() else []
    if isinstance(value, list):
        return sorted({str(item).strip().lower() for item in value if str(item).strip()})
    return []


def _normalized_restrictions(value: Any) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return sorted({str(item).strip() for item in value if str(item).strip()})
    return [str(value).strip()]


def _source_fingerprint_rows(sources: list[SourceRecord]) -> list[dict[str, Any]]:
    return [
        {
            "id": source.id,
            "source_type": source.source_type,
            "class_names": sorted(source.class_names),
            "url": source.url,
            "local_path": source.local_path,
            "license": source_license_metadata(source),
            "content_hash": source.metadata.get("content_hash"),
            "download_status": source.metadata.get("download_status"),
            "license_compliance_status": source.metadata.get("license_compliance_status"),
        }
        for source in sorted(sources, key=lambda item: item.id)
    ]


def _sample_fingerprint_rows(samples: list[SampleRecord]) -> list[dict[str, Any]]:
    return [
        {
            "id": sample.id,
            "source_id": sample.source_id,
            "source_type": sample.source_type,
            "class_names": sorted(sample.class_names),
            "derived_from": sample.derived_from,
            "timestamp_sec": sample.timestamp_sec,
            "quality_score": sample.quality_score,
            "decision": sample.decision,
            "content_hash": sample.content_hash,
        }
        for sample in sorted(samples, key=lambda item: item.id)
    ]


def _label_fingerprint_rows(labels: list[LabelRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in sorted(labels, key=lambda item: item.sample_id):
        rows.append(
            {
                "sample_id": record.sample_id,
                "provider": record.provider,
                "status": record.status,
                "label_path": _path_suffix(record.label_path),
                "boxes": [
                    {
                        "class_name": box.class_name,
                        "class_id": box.class_id,
                        "x_center": box.x_center,
                        "y_center": box.y_center,
                        "width": box.width,
                        "height": box.height,
                        "confidence": box.confidence,
                    }
                    for box in sorted(record.boxes, key=lambda value: (value.class_name, value.class_id))
                ],
            }
        )
    return rows


def _split_from_label_path(label_path: str | None) -> str | None:
    if not label_path:
        return None
    parts = Path(label_path).parts
    for index, part in enumerate(parts):
        if part == "labels" and index + 1 < len(parts):
            return parts[index + 1]
    return None


def _path_suffix(path: str | None) -> str | None:
    if not path:
        return None
    parts = Path(path).parts
    if len(parts) >= 3:
        return "/".join(parts[-3:])
    return Path(path).name
