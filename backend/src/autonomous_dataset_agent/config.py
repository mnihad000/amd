from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .contracts import BudgetLimits, CriticThresholds, SourceMix
from .utils import slugify


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


@dataclass
class SourceConfig:
    manifest_path: Path | None
    ffmpeg_path: str
    frames_per_second: float
    max_frames_per_video: int


@dataclass
class LabelConfig:
    provider: str
    api_key: str | None
    gemini_model: str


@dataclass
class TrainingConfig:
    enabled: bool
    model: str
    epochs: int
    image_size: int


@dataclass
class JobConfig:
    job_id: str
    prompt: str
    classes: list[str]
    output_root: Path
    source: SourceConfig
    label: LabelConfig
    training: TrainingConfig
    budgets: BudgetLimits
    critic: CriticThresholds
    mix: SourceMix


def build_job_config(
    prompt: str,
    classes: list[str],
    output_root: str | Path | None = None,
    env_file: str | Path | None = None,
) -> JobConfig:
    if env_file:
        _load_env_file(Path(env_file))
    else:
        _load_env_file(Path(".env"))

    job_id = f"{slugify(prompt)}-{slugify('-'.join(classes[:3]))}"
    manifest_value = os.getenv("SOURCE_MANIFEST_PATH")
    resolved_output_root = Path(output_root or os.getenv("OUTPUT_ROOT", "backend/artifacts"))

    return JobConfig(
        job_id=job_id,
        prompt=prompt,
        classes=classes,
        output_root=resolved_output_root,
        source=SourceConfig(
            manifest_path=Path(manifest_value) if manifest_value else None,
            ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
            frames_per_second=_env_float("FRAMES_PER_SECOND", 0.5),
            max_frames_per_video=_env_int("MAX_FRAMES_PER_VIDEO", 40),
        ),
        label=LabelConfig(
            provider=os.getenv("LABEL_PROVIDER", "gemini"),
            api_key=os.getenv("LABEL_API_KEY"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        ),
        training=TrainingConfig(
            enabled=_env_bool("ENABLE_TRAINING", False),
            model=os.getenv("YOLO_MODEL", "yolov8n.pt"),
            epochs=_env_int("YOLO_EPOCHS", 25),
            image_size=_env_int("YOLO_IMAGE_SIZE", 640),
        ),
        budgets=BudgetLimits(
            max_runtime_seconds=_env_int("MAX_RUNTIME_SECONDS", 1800),
            max_downloaded_sources=_env_int("MAX_DOWNLOADED_SOURCES", 50),
            max_label_calls=_env_int("MAX_LABEL_CALLS", 200),
            max_accepted_samples=_env_int("MAX_ACCEPTED_SAMPLES", 150),
        ),
        critic=CriticThresholds(
            min_quality_score=_env_float("MIN_QUALITY_SCORE", 0.6),
            min_label_confidence=_env_float("MIN_LABEL_CONFIDENCE", 0.7),
            min_samples_to_label=_env_int("MIN_SAMPLES_TO_LABEL", 3),
            min_samples_for_training=_env_int("MIN_SAMPLES_FOR_TRAINING", 5),
        ),
        mix=SourceMix(
            web_target_ratio=_env_float("WEB_IMAGE_TARGET_RATIO", 0.7),
            video_target_ratio=_env_float("VIDEO_TARGET_RATIO", 0.3),
        ),
    )
