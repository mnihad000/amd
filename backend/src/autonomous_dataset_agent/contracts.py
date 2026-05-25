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
class ClassQualityConfig:
    enabled: bool = True
    min_train_samples: int = 1
    min_val_samples: int = 1
    review_confidence_threshold: float = 0.75
    conflict_iou_threshold: float = 0.5
    hard_negative_top_k: int = 10
    opt_out_legacy_mode: bool = False


@dataclass
class IterationPolicyConfig:
    min_ap: float = 0.75
    min_precision: float = 0.7
    min_recall: float = 0.7
    max_negative_ap_delta: float = 0.05
    max_negative_precision_delta: float = 0.05
    max_negative_recall_delta: float = 0.05
    min_promote_map50_gain: float = 0.01
    max_iterations: int = 3
    max_runtime_seconds: int = 1800
    max_label_calls: int = 200
    current_iteration: int = 1
    critical_classes: list[str] = field(default_factory=list)
    per_class_minimums: dict[str, dict[str, float]] = field(default_factory=dict)
    per_class_delta_tolerances: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class GovernanceConfig:
    enabled: bool = True
    require_license_metadata: bool = True
    require_provenance: bool = True
    block_ingestion_on_violation: bool = True
    block_export_on_violation: bool = True
    allowed_usage_rights: list[str] = field(
        default_factory=lambda: ["dataset_training", "model_training", "training"]
    )
    retention_policy: str = "retain_until_reviewed"
    lifecycle_status: str = "active"


@dataclass
class RuntimeProfileConfig:
    seed: int = 42
    deterministic: bool = True
    dependency_pins: dict[str, str] = field(default_factory=dict)
    container_image: str = "python:3.11-slim"
    container_digest: str | None = None
    execution_baseline: str = "local-container-compatible"


@dataclass
class PromotionGateConfig:
    enabled: bool = True
    min_map50: float = 0.75
    min_precision: float = 0.7
    min_recall: float = 0.7
    min_per_class_ap: float = 0.75
    min_per_class_precision: float = 0.7
    min_per_class_recall: float = 0.7
    block_on_benchmark_regression: bool = True


@dataclass
class BenchmarkConfig:
    enabled: bool = True
    approved_snapshot_path: Path | None = None
    max_map50_regression: float = 0.02
    max_precision_regression: float = 0.02
    max_recall_regression: float = 0.02
    long_tail_min_recall: float = 0.65
    repeated_seed_runs: bool = False
    repeated_seed_values: list[int] = field(default_factory=lambda: [11, 42, 73])
    cross_validation: bool = False
    cross_validation_folds: int = 3


@dataclass
class ObservabilityConfig:
    enabled: bool = True
    service_name: str = "autonomous-dataset-agent"
    otel_exporter_endpoint: str | None = None
    prometheus_namespace: str = "ada"
    log_schema_version: int = 1
    stuck_run_seconds: int = 900
    repeated_stage_failure_threshold: int = 3
    class_regression_ap_delta: float = 0.05
    drift_ap_delta: float = 0.05
    budget_spend_ratio: float = 0.9


@dataclass
class ResilienceConfig:
    enabled: bool = True
    max_stage_attempts: int = 2
    retry_backoff_seconds: float = 0.0
    dead_letter_enabled: bool = True
    checkpoint_enabled: bool = True
    queue_limit: int = 100
    max_concurrent_runs: int = 1
    default_stage_sla_seconds: int = 900
    stage_sla_seconds: dict[str, int] = field(default_factory=dict)
    rollback_on_promotion_block: bool = True


@dataclass
class SourceRecord:
    id: str
    source_type: str
    class_names: list[str]
    title: str
    url: str | None = None
    local_path: str | None = None
    license: dict[str, Any] = field(default_factory=dict)
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
    class_split_counts: dict[str, dict[str, int]] = field(default_factory=dict)
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
    per_class_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    class_failure_diagnostics: dict[str, dict[str, object]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class IterationDecision:
    action: str
    target_classes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    budget_snapshot: dict[str, object] = field(default_factory=dict)
    regression_gate_status: str = "not_evaluated"
    policy_report: dict[str, object] = field(default_factory=dict)
    baseline_comparison: dict[str, object] = field(default_factory=dict)
    promotion_guard: dict[str, object] = field(default_factory=dict)


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
    per_class_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    quota_status: dict[str, object] = field(default_factory=dict)
    review_queue_summary: dict[str, int] = field(default_factory=dict)
    hard_negative_summary: dict[str, object] = field(default_factory=dict)
    iteration_policy: dict[str, object] = field(default_factory=dict)
    baseline_comparison_summary: dict[str, object] = field(default_factory=dict)
    promotion_guard_summary: dict[str, object] = field(default_factory=dict)
    runtime_profile: dict[str, object] = field(default_factory=dict)
    promotion_gate_summary: dict[str, object] = field(default_factory=dict)
    benchmark_summary: dict[str, object] = field(default_factory=dict)
    benchmark_regression_summary: dict[str, object] = field(default_factory=dict)
    advanced_validation_summary: dict[str, object] = field(default_factory=dict)
    governance_summary: dict[str, object] = field(default_factory=dict)
    lineage_summary: dict[str, object] = field(default_factory=dict)
    license_compliance: dict[str, object] = field(default_factory=dict)
    version_summary: dict[str, object] = field(default_factory=dict)
    artifact_lifecycle: dict[str, object] = field(default_factory=dict)
    monitoring_summary: dict[str, object] = field(default_factory=dict)
    orchestration_resilience: dict[str, object] = field(default_factory=dict)
