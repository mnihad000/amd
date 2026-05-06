from __future__ import annotations

from .config import TrainingConfig
from .contracts import DatasetBuildResult, JobPaths, TrainingResult


def train_dataset(
    dataset_result: DatasetBuildResult,
    job_paths: JobPaths,
    training: TrainingConfig,
) -> TrainingResult:
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
