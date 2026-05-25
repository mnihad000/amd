from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import ResilienceConfig
from .governance import stable_checksum
from .run_lifecycle import PIPELINE_STAGES, StageName
from .utils import ensure_dir, read_json, write_json


IDEMPOTENCY_CONTRACTS: dict[str, dict[str, object]] = {
    "bootstrap": {"key_fields": ["job_id", "runtime_profile"], "side_effects": ["reports/bootstrap.json"], "replay_safe": True},
    "class_planning": {"key_fields": ["job_id", "prompt", "classes"], "side_effects": ["reports/class_plan.json"], "replay_safe": True},
    "source_resolution": {"key_fields": ["job_id", "source_mode", "source_manifest"], "side_effects": ["downloads", "reports/source_manifest.json"], "replay_safe": True},
    "frame_extraction": {"key_fields": ["job_id", "source_manifest", "frames_per_second"], "side_effects": ["frames", "reports/sample_manifest.json"], "replay_safe": True},
    "critic": {"key_fields": ["job_id", "critic_config", "sample_manifest"], "side_effects": ["reports/frame_scores.json"], "replay_safe": True},
    "labeling": {"key_fields": ["job_id", "label_provider", "accepted_frames"], "side_effects": ["labels", "reports/labels_manifest.json"], "replay_safe": True},
    "dataset_build": {"key_fields": ["job_id", "labels_manifest", "split_policy"], "side_effects": ["datasets", "reports/dataset_manifest.json"], "replay_safe": True},
    "training": {"key_fields": ["job_id", "dataset_version_id", "runtime_profile"], "side_effects": ["models", "reports/training_results.json"], "replay_safe": True},
    "evaluation": {"key_fields": ["job_id", "model_version_id", "validation_set"], "side_effects": ["reports/evaluation_report.json"], "replay_safe": True},
    "iteration": {"key_fields": ["job_id", "evaluation_report", "iteration_policy"], "side_effects": ["reports/iteration_policy_report.json"], "replay_safe": True},
    "finalize": {"key_fields": ["job_id", "artifact_manifest"], "side_effects": ["reports/run_summary.json"], "replay_safe": True},
}


def build_idempotency_contracts() -> dict[str, object]:
    return {
        "schema_version": 1,
        "primary_key": "job_id",
        "stages": {stage: IDEMPOTENCY_CONTRACTS[stage] for stage in PIPELINE_STAGES},
    }


def build_retry_policy(config: ResilienceConfig) -> dict[str, object]:
    return {
        "schema_version": 1,
        "enabled": config.enabled,
        "max_stage_attempts": max(1, config.max_stage_attempts),
        "backoff_seconds": config.retry_backoff_seconds,
        "replay_sequence": list(PIPELINE_STAGES),
        "retryable_stages": [stage for stage, contract in IDEMPOTENCY_CONTRACTS.items() if contract["replay_safe"]],
        "non_retryable_errors": ["run_cancelled", "run_timed_out", "license_violation"],
    }


def write_checkpoint_state(
    *,
    reports_dir: Path,
    job_id: str,
    stage_name: StageName,
    attempt: int,
    status: str,
    artifact_refs: dict[str, str] | None = None,
) -> dict[str, object]:
    checkpoint_dir = ensure_dir(reports_dir / "checkpoints")
    payload = {
        "schema_version": 1,
        "job_id": job_id,
        "stage": stage_name,
        "attempt": attempt,
        "status": status,
        "idempotency_key": stable_checksum(
            {
                "job_id": job_id,
                "stage": stage_name,
                "attempt": attempt,
                "contract": IDEMPOTENCY_CONTRACTS[stage_name]["key_fields"],
            }
        ),
        "replay_safe": IDEMPOTENCY_CONTRACTS[stage_name]["replay_safe"],
        "resume_from": stage_name,
        "artifact_refs": artifact_refs or {},
    }
    write_json(checkpoint_dir / f"{stage_name}.json", payload)
    return payload


def build_checkpoint_manifest(reports_dir: Path, job_id: str) -> dict[str, object]:
    checkpoint_dir = reports_dir / "checkpoints"
    checkpoints: list[dict[str, object]] = []
    if checkpoint_dir.exists():
        for stage_name in PIPELINE_STAGES:
            path = checkpoint_dir / f"{stage_name}.json"
            if path.exists():
                payload = read_json(path)
                if isinstance(payload, dict):
                    checkpoints.append(payload)
    completed = [str(item.get("stage")) for item in checkpoints if item.get("status") == "completed"]
    next_stage = next((stage for stage in PIPELINE_STAGES if stage not in completed), None)
    return {
        "schema_version": 1,
        "job_id": job_id,
        "checkpoint_count": len(checkpoints),
        "completed_stages": completed,
        "next_resume_stage": next_stage,
        "resume_semantics": "resume from first incomplete deterministic stage; completed stages are replay-safe by idempotency key",
        "checkpoints": checkpoints,
    }


def capture_dead_letter(
    *,
    reports_dir: Path,
    job_id: str,
    stage_name: StageName,
    attempt: int,
    exc: Exception,
    retry_policy: dict[str, object],
) -> dict[str, object]:
    ensure_dir(reports_dir)
    payload = {
        "schema_version": 1,
        "job_id": job_id,
        "stage": stage_name,
        "attempt": attempt,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "idempotency_key": stable_checksum({"job_id": job_id, "stage": stage_name, "attempt": attempt}),
        "retry_policy": retry_policy,
        "replay": build_dead_letter_replay_plan(job_id=job_id, failed_stage=stage_name),
    }
    write_json(reports_dir / "dead_letter.json", payload)
    return payload


def build_dead_letter_replay_plan(*, job_id: str, failed_stage: StageName) -> dict[str, object]:
    start_index = PIPELINE_STAGES.index(failed_stage)
    return {
        "replay_job_id_hint": f"{job_id}-replay",
        "start_stage": failed_stage,
        "stage_sequence": list(PIPELINE_STAGES[start_index:]),
        "requires_operator_action": True,
        "notes": ["Replay uses the same prompt/classes and starts from the failed stage checkpoint when available."],
    }


def empty_dead_letter(job_id: str) -> dict[str, object]:
    return {"schema_version": 1, "job_id": job_id, "status": "empty", "replay": None}


def build_rollback_plan(
    *,
    output_root: Path,
    current_job_id: str,
    promotion_gate: dict[str, object],
    version_manifest: dict[str, object],
    config: ResilienceConfig,
) -> dict[str, object]:
    blocked = bool(promotion_gate.get("blocked")) or promotion_gate.get("status") == "blocked"
    if not config.rollback_on_promotion_block or not blocked:
        return {
            "schema_version": 1,
            "job_id": current_job_id,
            "status": "not_required",
            "reason": "promotion gate did not request rollback",
            "current_version": _version_refs(version_manifest),
            "last_stable": None,
        }

    candidates = _stable_promotion_candidates(output_root, current_job_id)
    if not candidates:
        return {
            "schema_version": 1,
            "job_id": current_job_id,
            "status": "blocked_no_stable_artifact",
            "reason": "no prior stable promoted model/artifact set found",
            "current_version": _version_refs(version_manifest),
            "last_stable": None,
        }

    last_stable = candidates[-1]
    return {
        "schema_version": 1,
        "job_id": current_job_id,
        "status": "rollback_ready",
        "reason": "promotion blocked; last stable artifact set selected",
        "current_version": _version_refs(version_manifest),
        "last_stable": last_stable,
        "actions": [
            {"action": "restore_model", "source": last_stable.get("model_artifacts", {})},
            {"action": "restore_dataset_manifest", "source": last_stable.get("dataset_version_id")},
        ],
    }


def build_concurrency_policy(
    *,
    config: ResilienceConfig,
    max_workers: int,
    active_count: int,
    queued_count: int,
) -> dict[str, object]:
    queue_limit = max(1, config.queue_limit)
    queue_ratio = round(queued_count / queue_limit, 6)
    return {
        "schema_version": 1,
        "max_concurrent_runs": max_workers,
        "configured_max_concurrent_runs": config.max_concurrent_runs,
        "queue_limit": queue_limit,
        "active_count": active_count,
        "queued_count": queued_count,
        "queue_utilization": queue_ratio,
        "backpressure_state": "rejecting" if queued_count >= queue_limit else "accepting",
        "burst_control": {
            "policy": "bounded_fifo",
            "overflow_action": "reject_new_run_with_503",
        },
    }


def build_sla_escalation_policy(config: ResilienceConfig) -> dict[str, object]:
    return {
        "schema_version": 1,
        "default_stage_sla_seconds": config.default_stage_sla_seconds,
        "stage_sla_seconds": config.stage_sla_seconds,
        "states": ["within_sla", "approaching_sla", "breached", "escalated"],
        "escalation_map": {
            "within_sla": "none",
            "approaching_sla": "operator_watch",
            "breached": "operator_page",
            "escalated": "admin_incident_review",
        },
    }


def build_sla_state(stage_telemetry: list[dict[str, object]], config: ResilienceConfig) -> dict[str, object]:
    stage_states: dict[str, dict[str, object]] = {}
    for item in stage_telemetry:
        stage_name = str(item.get("stage", "unknown"))
        duration_seconds = float(item.get("duration_ms", 0)) / 1000
        sla_seconds = config.stage_sla_seconds.get(stage_name, config.default_stage_sla_seconds)
        ratio = duration_seconds / max(1, sla_seconds)
        if ratio >= 1.5:
            state = "escalated"
        elif ratio >= 1.0:
            state = "breached"
        elif ratio >= 0.8:
            state = "approaching_sla"
        else:
            state = "within_sla"
        stage_states[stage_name] = {
            "state": state,
            "duration_seconds": round(duration_seconds, 6),
            "sla_seconds": sla_seconds,
            "escalation": build_sla_escalation_policy(config)["escalation_map"][state],
        }
    overall_order = {"within_sla": 0, "approaching_sla": 1, "breached": 2, "escalated": 3}
    overall_state = max((value["state"] for value in stage_states.values()), key=lambda item: overall_order[item], default="within_sla")
    return {
        "schema_version": 1,
        "overall_state": overall_state,
        "stage_states": stage_states,
    }


def build_resilience_artifacts(
    *,
    reports_dir: Path,
    output_root: Path,
    job_id: str,
    stage_telemetry: list[dict[str, object]],
    promotion_gate: dict[str, object],
    version_manifest: dict[str, object],
    config: ResilienceConfig,
    max_workers: int = 1,
    active_count: int = 0,
    queued_count: int = 0,
) -> dict[str, object]:
    retry_policy = build_retry_policy(config)
    checkpoint_manifest = build_checkpoint_manifest(reports_dir, job_id)
    dead_letter_path = reports_dir / "dead_letter.json"
    dead_letter = read_json(dead_letter_path) if dead_letter_path.exists() else empty_dead_letter(job_id)
    rollback_plan = build_rollback_plan(
        output_root=output_root,
        current_job_id=job_id,
        promotion_gate=promotion_gate,
        version_manifest=version_manifest,
        config=config,
    )
    concurrency_policy = build_concurrency_policy(
        config=config,
        max_workers=max_workers,
        active_count=active_count,
        queued_count=queued_count,
    )
    sla_policy = build_sla_escalation_policy(config)
    sla_state = build_sla_state(stage_telemetry, config)

    artifacts = {
        "idempotency_contracts": str(reports_dir / "idempotency_contracts.json"),
        "retry_policy": str(reports_dir / "retry_policy.json"),
        "checkpoint_manifest": str(reports_dir / "checkpoint_manifest.json"),
        "dead_letter": str(reports_dir / "dead_letter.json"),
        "rollback_plan": str(reports_dir / "rollback_plan.json"),
        "concurrency_policy": str(reports_dir / "concurrency_policy.json"),
        "sla_escalation_policy": str(reports_dir / "sla_escalation_policy.json"),
        "sla_state": str(reports_dir / "sla_state.json"),
    }
    write_json(Path(artifacts["idempotency_contracts"]), build_idempotency_contracts())
    write_json(Path(artifacts["retry_policy"]), retry_policy)
    write_json(Path(artifacts["checkpoint_manifest"]), checkpoint_manifest)
    write_json(Path(artifacts["dead_letter"]), dead_letter)
    write_json(Path(artifacts["rollback_plan"]), rollback_plan)
    write_json(Path(artifacts["concurrency_policy"]), concurrency_policy)
    write_json(Path(artifacts["sla_escalation_policy"]), sla_policy)
    write_json(Path(artifacts["sla_state"]), sla_state)

    return {
        "schema_version": 1,
        "enabled": config.enabled,
        "job_id": job_id,
        "idempotency": {"stage_count": len(IDEMPOTENCY_CONTRACTS), "all_replay_safe": all(item["replay_safe"] for item in IDEMPOTENCY_CONTRACTS.values())},
        "retry": {
            "max_stage_attempts": retry_policy["max_stage_attempts"],
            "checkpoint_count": checkpoint_manifest["checkpoint_count"],
            "next_resume_stage": checkpoint_manifest["next_resume_stage"],
        },
        "dead_letter": {
            "status": dead_letter.get("status", "captured"),
            "stage": dead_letter.get("stage"),
            "replay": dead_letter.get("replay"),
        },
        "rollback": {
            "status": rollback_plan["status"],
            "last_stable_job_id": (rollback_plan.get("last_stable") or {}).get("job_id") if isinstance(rollback_plan.get("last_stable"), dict) else None,
        },
        "concurrency": concurrency_policy,
        "sla": sla_state,
        "artifact_paths": artifacts,
    }


def _stable_promotion_candidates(output_root: Path, current_job_id: str) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    if not output_root.exists():
        return candidates
    for summary_path in sorted(output_root.glob("*/reports/run_summary.json")):
        payload = read_json(summary_path)
        if not isinstance(payload, dict) or payload.get("job_id") == current_job_id:
            continue
        promotion_gate = payload.get("promotion_gate_summary", {})
        iteration_policy = payload.get("iteration_policy", {})
        stable_gate = isinstance(promotion_gate, dict) and promotion_gate.get("status") == "passed"
        promoted = isinstance(iteration_policy, dict) and iteration_policy.get("selected_action") in {"promote", "stop"}
        if stable_gate and promoted:
            candidates.append(
                {
                    "job_id": payload.get("job_id"),
                    "dataset_version_id": payload.get("version_summary", {}).get("dataset_version_id") if isinstance(payload.get("version_summary"), dict) else None,
                    "model_version_id": payload.get("version_summary", {}).get("model_version_id") if isinstance(payload.get("version_summary"), dict) else None,
                    "artifact_paths": payload.get("artifact_paths", {}),
                    "model_artifacts": payload.get("summary", {}).get("artifact_paths", {}) if isinstance(payload.get("summary"), dict) else payload.get("artifact_paths", {}),
                }
            )
    return candidates


def _version_refs(version_manifest: dict[str, object]) -> dict[str, object]:
    return {
        "dataset_version_id": version_manifest.get("dataset_version_id"),
        "model_version_id": version_manifest.get("model_version_id"),
        "checksums": version_manifest.get("checksums", {}),
    }
