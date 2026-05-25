from __future__ import annotations

from .config import TrainingConfig
from .contracts import DatasetBuildResult, JobPaths, TrainingResult
from .contracts import RuntimeProfileConfig
from .training_hardening import apply_runtime_profile


def train_dataset(
    dataset_result: DatasetBuildResult,
    job_paths: JobPaths,
    training: TrainingConfig,
    *,
    review_gate: dict[str, object] | None = None,
    quota_gate: dict[str, object] | None = None,
    compliance_gate: dict[str, object] | None = None,
    runtime_profile: RuntimeProfileConfig | None = None,
) -> TrainingResult:
    if runtime_profile is not None:
        apply_runtime_profile(runtime_profile)

    if compliance_gate and compliance_gate.get("export_status") == "blocked":
        reasons = compliance_gate.get("violations", ["License compliance gate blocked export/training."])
        notes = []
        for reason in reasons:
            if isinstance(reason, dict):
                notes.extend(str(item) for item in reason.get("reasons", []))
            else:
                notes.append(str(reason))
        return TrainingResult(status="blocked", notes=notes or ["License compliance gate blocked export/training."])
    if review_gate and review_gate.get("status") == "blocked":
        reasons = review_gate.get("reasons", ["Pending review items block training."])
        return TrainingResult(status="blocked", notes=[str(reason) for reason in reasons])
    if quota_gate and quota_gate.get("status") == "blocked":
        reasons = quota_gate.get("reasons", ["Class quota gate blocked training."])
        return TrainingResult(status="blocked", notes=[str(reason) for reason in reasons])
    if not training.enabled:
        return TrainingResult(status="skipped", notes=["Training disabled by configuration."])
    if dataset_result.status != "completed" or not dataset_result.data_yaml_path:
        return TrainingResult(status="skipped", notes=["Dataset build did not complete successfully."])

    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError:
        return TrainingResult(
            status="blocked",
            notes=["Ultralytics is not installed. Install backend with the 'train' extra to enable training."],
        )

    model = YOLO(training.model)
    output_dir = job_paths.models / "yolo"
    results = model.train(
        data=dataset_result.data_yaml_path,
        epochs=training.epochs,
        imgsz=training.image_size,
        seed=runtime_profile.seed if runtime_profile is not None else 42,
        deterministic=runtime_profile.deterministic if runtime_profile is not None else True,
        project=str(output_dir.parent),
        name=output_dir.name,
        exist_ok=True,
    )

    metrics = {}
    for key in ("metrics/mAP50(B)", "metrics/precision(B)", "metrics/recall(B)"):
        if hasattr(results, "results_dict") and key in results.results_dict:
            metrics[key] = float(results.results_dict[key])

    artifact_paths = {
        "model_dir": str(output_dir),
    }
    return TrainingResult(status="completed", metrics=metrics, artifact_paths=artifact_paths)
