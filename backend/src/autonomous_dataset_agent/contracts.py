from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BudgetLimits:
    max_runtime_seconds: int = 1800
    max_downloaded_sources: int = 50
    max_label_calls: int = 200
    max_accepted_samples: int = 150


@dataclass
class SourceMix:
    web_target_ratio: float = 0.7
    video_target_ratio: float = 0.3


@dataclass
class CriticThresholds:
    min_quality_score: float = 0.6
    min_label_confidence: float = 0.7
    min_samples_to_label: int = 3
    min_samples_for_training: int = 5
    min_image_width: int = 1
    min_image_height: int = 1
    min_sharpness_score: float = 5.0
    min_contrast_std: float = 8.0
    min_brightness_mean: float = 35.0
    max_brightness_mean: float = 220.0
    min_aspect_ratio: float = 0.2
    max_aspect_ratio: float = 5.0


@dataclass
class SourceRecord:
    id: str
    source_type: str
    class_names: list[str]
    title: str
    url: str | None = None
    local_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SampleRecord:
    id: str
    source_id: str
    source_type: str
    class_names: list[str]
    path: str
    metadata: dict[str, Any] = field(default_factory=dict)
    derived_from: str | None = None
    timestamp_sec: float | None = None
    quality_score: float | None = None
    decision: str = "pending"
    rejection_reasons: list[str] = field(default_factory=list)
    content_hash: str | None = None


@dataclass
class ClassPlanEntry:
    name: str
    initial_state: str
    final_state: str
    feasibility_score: float
    reasons: list[str] = field(default_factory=list)
    discovered_sources: int = 0
    accepted_samples: int = 0
    avg_label_confidence: float | None = None


@dataclass
class LabelBox:
    class_name: str
    class_id: int
    x_center: float
    y_center: float
    width: float
    height: float
    confidence: float


@dataclass
class LabelRecord:
    sample_id: str
    provider: str
    status: str
    boxes: list[LabelBox] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    label_path: str | None = None


@dataclass
class DatasetBuildResult:
    status: str
    dataset_dir: str | None = None
    data_yaml_path: str | None = None
    class_map: dict[int, str] = field(default_factory=dict)
    split_counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class TrainingResult:
    status: str
    metrics: dict[str, float] = field(default_factory=dict)
    artifact_paths: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class EvaluationReport:
    status: str
    map50: float | None = None
    precision: float | None = None
    recall: float | None = None
    weak_classes: list[str] = field(default_factory=list)
    class_outcomes: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class IterationDecision:
    action: str
    target_classes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class BootstrapReport:
    supported_python: bool
    python_version: str
    ffmpeg_available: bool
    ffmpeg_path: str | None
    yt_dlp_available: bool = False
    yt_dlp_path: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class JobPaths:
    root: Path
    downloads: Path
    frames: Path
    labels: Path
    datasets: Path
    models: Path
    reports: Path


@dataclass
class RunSummary:
    job_id: str
    prompt: str
    requested_classes: list[str]
    admitted_classes: list[str]
    deferred_classes: list[str]
    blocked_classes: list[str]
    source_breakdown: dict[str, int]
    budgets: dict[str, int]
    notes: list[str] = field(default_factory=list)
    artifact_paths: dict[str, str] = field(default_factory=dict)
