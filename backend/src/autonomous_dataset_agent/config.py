from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from typing import Literal
from pathlib import Path

from .contracts import (
    BudgetLimits,
    BenchmarkConfig,
    ClassQualityConfig,
    CriticThresholds,
    GovernanceConfig,
    IterationPolicyConfig,
    ObservabilityConfig,
    PromotionGateConfig,
    ResilienceConfig,
    RuntimeProfileConfig,
    SourceMix,
)
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


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_lower_list(name: str, default: list[str]) -> list[str]:
    return [item.strip().lower() for item in _env_list(name, default) if item.strip()]


def _env_json_dict(name: str) -> dict[str, dict[str, float]]:
    value = os.getenv(name)
    if value is None:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}

    normalized: dict[str, dict[str, float]] = {}
    for class_name, raw_metrics in payload.items():
        if not isinstance(raw_metrics, dict):
            continue
        metrics: dict[str, float] = {}
        for metric_name, metric_value in raw_metrics.items():
            try:
                metrics[str(metric_name)] = float(metric_value)
            except (TypeError, ValueError):
                continue
        if metrics:
            normalized[str(class_name).strip().lower()] = metrics
    return normalized


def _env_str_dict(name: str) -> dict[str, str]:
    value = os.getenv(name)
    if value is None:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(item) for key, item in payload.items()}


@dataclass
class SourceConfig:
    source_mode: Literal["manifest", "live"] = "manifest"
    manifest_path: Path | None = None
    ffmpeg_path: str = "ffmpeg"
    yt_dlp_path: str = "yt-dlp"
    frames_per_second: float = 0.5
    max_frames_per_video: int = 40
    web_search_provider_order: list[str] | None = None
    bing_search_api_key: str | None = None
    web_image_search_results_per_class: int = 10
    web_image_downloads_per_class: int = 4
    youtube_search_results_per_class: int = 6
    youtube_downloads_per_class: int = 2
    download_timeout_seconds: int = 20
    download_retry_count: int = 2
    download_user_agent: str = "AutonomousDatasetAgent/0.1"
    source_domain_allowlist: list[str] | None = None
    source_domain_denylist: list[str] | None = None


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
    class_quality: ClassQualityConfig = field(default_factory=ClassQualityConfig)
    iteration_policy: IterationPolicyConfig = field(default_factory=IterationPolicyConfig)
    governance: GovernanceConfig = field(default_factory=GovernanceConfig)
    runtime_profile: RuntimeProfileConfig = field(default_factory=RuntimeProfileConfig)
    promotion_gate: PromotionGateConfig = field(default_factory=PromotionGateConfig)
    benchmark: BenchmarkConfig = field(default_factory=BenchmarkConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    resilience: ResilienceConfig = field(default_factory=ResilienceConfig)


def build_job_config(
    prompt: str,
    classes: list[str],
    output_root: str | Path | None = None,
    env_file: str | Path | None = None,
    source_mode: str | None = None,
) -> JobConfig:
    if env_file:
        _load_env_file(Path(env_file))
    else:
        _load_env_file(Path(".env"))

    job_id = f"{slugify(prompt)}-{slugify('-'.join(classes[:3]))}"
    manifest_value = os.getenv("SOURCE_MANIFEST_PATH")
    resolved_source_mode = (source_mode or os.getenv("SOURCE_MODE", "manifest")).strip().lower()
    provider_order = _env_list("WEB_SEARCH_PROVIDER_ORDER", ["duckduckgo", "bing"])
    resolved_output_root = Path(output_root or os.getenv("OUTPUT_ROOT", "backend/artifacts"))

    budgets = BudgetLimits(
        max_runtime_seconds=_env_int("MAX_RUNTIME_SECONDS", 1800),
        max_downloaded_sources=_env_int("MAX_DOWNLOADED_SOURCES", 50),
        max_label_calls=_env_int("MAX_LABEL_CALLS", 200),
        max_accepted_samples=_env_int("MAX_ACCEPTED_SAMPLES", 150),
    )

    return JobConfig(
        job_id=job_id,
        prompt=prompt,
        classes=classes,
        output_root=resolved_output_root,
        source=SourceConfig(
            source_mode="live" if resolved_source_mode == "live" else "manifest",
            manifest_path=Path(manifest_value) if manifest_value else None,
            ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
            yt_dlp_path=os.getenv("YT_DLP_PATH", "yt-dlp"),
            frames_per_second=_env_float("FRAMES_PER_SECOND", 0.5),
            max_frames_per_video=_env_int("MAX_FRAMES_PER_VIDEO", 40),
            web_search_provider_order=provider_order,
            bing_search_api_key=os.getenv("BING_SEARCH_API_KEY"),
            web_image_search_results_per_class=_env_int("WEB_IMAGE_SEARCH_RESULTS_PER_CLASS", 10),
            web_image_downloads_per_class=_env_int("WEB_IMAGE_DOWNLOADS_PER_CLASS", 4),
            youtube_search_results_per_class=_env_int("YOUTUBE_SEARCH_RESULTS_PER_CLASS", 6),
            youtube_downloads_per_class=_env_int("YOUTUBE_DOWNLOADS_PER_CLASS", 2),
            download_timeout_seconds=_env_int("DOWNLOAD_TIMEOUT_SECONDS", 20),
            download_retry_count=_env_int("DOWNLOAD_RETRY_COUNT", 2),
            download_user_agent=os.getenv("DOWNLOAD_USER_AGENT", "AutonomousDatasetAgent/0.1"),
            source_domain_allowlist=_env_list("SOURCE_DOMAIN_ALLOWLIST", []),
            source_domain_denylist=_env_list("SOURCE_DOMAIN_DENYLIST", []),
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
        budgets=budgets,
        critic=CriticThresholds(
            min_quality_score=_env_float("MIN_QUALITY_SCORE", 0.6),
            min_label_confidence=_env_float("MIN_LABEL_CONFIDENCE", 0.7),
            min_samples_to_label=_env_int("MIN_SAMPLES_TO_LABEL", 3),
            min_samples_for_training=_env_int("MIN_SAMPLES_FOR_TRAINING", 5),
            min_image_width=_env_int("MIN_IMAGE_WIDTH", 160),
            min_image_height=_env_int("MIN_IMAGE_HEIGHT", 160),
            min_sharpness_score=_env_float("MIN_SHARPNESS_SCORE", 5.0),
            min_contrast_std=_env_float("MIN_CONTRAST_STD", 8.0),
            min_brightness_mean=_env_float("MIN_BRIGHTNESS_MEAN", 35.0),
            max_brightness_mean=_env_float("MAX_BRIGHTNESS_MEAN", 220.0),
            min_aspect_ratio=_env_float("MIN_ASPECT_RATIO", 0.2),
            max_aspect_ratio=_env_float("MAX_ASPECT_RATIO", 5.0),
        ),
        mix=SourceMix(
            web_target_ratio=_env_float("WEB_IMAGE_TARGET_RATIO", 0.7),
            video_target_ratio=_env_float("VIDEO_TARGET_RATIO", 0.3),
        ),
        class_quality=ClassQualityConfig(
            enabled=_env_bool("CLASS_QUALITY_ENABLED", True),
            min_train_samples=_env_int("CLASS_QUALITY_MIN_TRAIN_SAMPLES", 1),
            min_val_samples=_env_int("CLASS_QUALITY_MIN_VAL_SAMPLES", 1),
            review_confidence_threshold=_env_float("CLASS_QUALITY_REVIEW_CONFIDENCE_THRESHOLD", 0.75),
            conflict_iou_threshold=_env_float("CLASS_QUALITY_CONFLICT_IOU_THRESHOLD", 0.5),
            hard_negative_top_k=_env_int("CLASS_QUALITY_HARD_NEGATIVE_TOP_K", 10),
            opt_out_legacy_mode=_env_bool("CLASS_QUALITY_OPT_OUT_LEGACY_MODE", False),
        ),
        iteration_policy=IterationPolicyConfig(
            min_ap=_env_float("ITERATION_MIN_AP", 0.75),
            min_precision=_env_float("ITERATION_MIN_PRECISION", 0.7),
            min_recall=_env_float("ITERATION_MIN_RECALL", 0.7),
            max_negative_ap_delta=_env_float("ITERATION_MAX_NEGATIVE_AP_DELTA", 0.05),
            max_negative_precision_delta=_env_float("ITERATION_MAX_NEGATIVE_PRECISION_DELTA", 0.05),
            max_negative_recall_delta=_env_float("ITERATION_MAX_NEGATIVE_RECALL_DELTA", 0.05),
            min_promote_map50_gain=_env_float("ITERATION_MIN_PROMOTE_MAP50_GAIN", 0.01),
            max_iterations=_env_int("ITERATION_MAX_ITERATIONS", 3),
            max_runtime_seconds=_env_int("ITERATION_MAX_RUNTIME_SECONDS", budgets.max_runtime_seconds),
            max_label_calls=_env_int("ITERATION_MAX_LABEL_CALLS", budgets.max_label_calls),
            current_iteration=_env_int("ITERATION_CURRENT_ITERATION", 1),
            critical_classes=_env_list("ITERATION_CRITICAL_CLASSES", []),
            per_class_minimums=_env_json_dict("ITERATION_PER_CLASS_MINIMUMS"),
            per_class_delta_tolerances=_env_json_dict("ITERATION_PER_CLASS_DELTA_TOLERANCES"),
        ),
        governance=GovernanceConfig(
            enabled=_env_bool("GOVERNANCE_ENABLED", True),
            require_license_metadata=_env_bool("GOVERNANCE_REQUIRE_LICENSE_METADATA", True),
            require_provenance=_env_bool("GOVERNANCE_REQUIRE_PROVENANCE", True),
            block_ingestion_on_violation=_env_bool("GOVERNANCE_BLOCK_INGESTION_ON_VIOLATION", True),
            block_export_on_violation=_env_bool("GOVERNANCE_BLOCK_EXPORT_ON_VIOLATION", True),
            allowed_usage_rights=_env_lower_list(
                "GOVERNANCE_ALLOWED_USAGE_RIGHTS",
                ["dataset_training", "model_training", "training"],
            ),
            retention_policy=os.getenv("GOVERNANCE_RETENTION_POLICY", "retain_until_reviewed"),
            lifecycle_status=os.getenv("GOVERNANCE_LIFECYCLE_STATUS", "active"),
        ),
        runtime_profile=RuntimeProfileConfig(
            seed=_env_int("RUNTIME_SEED", 42),
            deterministic=_env_bool("RUNTIME_DETERMINISTIC", True),
            dependency_pins=_env_str_dict("RUNTIME_DEPENDENCY_PINS"),
            container_image=os.getenv("RUNTIME_CONTAINER_IMAGE", "python:3.11-slim"),
            container_digest=os.getenv("RUNTIME_CONTAINER_DIGEST"),
            execution_baseline=os.getenv("RUNTIME_EXECUTION_BASELINE", "local-container-compatible"),
        ),
        promotion_gate=PromotionGateConfig(
            enabled=_env_bool("PROMOTION_GATE_ENABLED", True),
            min_map50=_env_float("PROMOTION_GATE_MIN_MAP50", 0.75),
            min_precision=_env_float("PROMOTION_GATE_MIN_PRECISION", 0.7),
            min_recall=_env_float("PROMOTION_GATE_MIN_RECALL", 0.7),
            min_per_class_ap=_env_float("PROMOTION_GATE_MIN_PER_CLASS_AP", 0.75),
            min_per_class_precision=_env_float("PROMOTION_GATE_MIN_PER_CLASS_PRECISION", 0.7),
            min_per_class_recall=_env_float("PROMOTION_GATE_MIN_PER_CLASS_RECALL", 0.7),
            block_on_benchmark_regression=_env_bool("PROMOTION_GATE_BLOCK_ON_BENCHMARK_REGRESSION", True),
        ),
        benchmark=BenchmarkConfig(
            enabled=_env_bool("BENCHMARK_ENABLED", True),
            approved_snapshot_path=Path(os.environ["BENCHMARK_APPROVED_SNAPSHOT_PATH"])
            if os.getenv("BENCHMARK_APPROVED_SNAPSHOT_PATH")
            else None,
            max_map50_regression=_env_float("BENCHMARK_MAX_MAP50_REGRESSION", 0.02),
            max_precision_regression=_env_float("BENCHMARK_MAX_PRECISION_REGRESSION", 0.02),
            max_recall_regression=_env_float("BENCHMARK_MAX_RECALL_REGRESSION", 0.02),
            long_tail_min_recall=_env_float("BENCHMARK_LONG_TAIL_MIN_RECALL", 0.65),
            repeated_seed_runs=_env_bool("BENCHMARK_REPEATED_SEED_RUNS", False),
            repeated_seed_values=[int(item) for item in _env_list("BENCHMARK_REPEATED_SEED_VALUES", ["11", "42", "73"])],
            cross_validation=_env_bool("BENCHMARK_CROSS_VALIDATION", False),
            cross_validation_folds=_env_int("BENCHMARK_CROSS_VALIDATION_FOLDS", 3),
        ),
        observability=ObservabilityConfig(
            enabled=_env_bool("OBSERVABILITY_ENABLED", True),
            service_name=os.getenv("OBSERVABILITY_SERVICE_NAME", "autonomous-dataset-agent"),
            otel_exporter_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
            prometheus_namespace=os.getenv("PROMETHEUS_NAMESPACE", "ada"),
            log_schema_version=_env_int("LOG_SCHEMA_VERSION", 1),
            stuck_run_seconds=_env_int("ALERT_STUCK_RUN_SECONDS", 900),
            repeated_stage_failure_threshold=_env_int("ALERT_REPEATED_STAGE_FAILURE_THRESHOLD", 3),
            class_regression_ap_delta=_env_float("ALERT_CLASS_REGRESSION_AP_DELTA", 0.05),
            drift_ap_delta=_env_float("ALERT_DRIFT_AP_DELTA", 0.05),
            budget_spend_ratio=_env_float("ALERT_BUDGET_SPEND_RATIO", 0.9),
        ),
        resilience=ResilienceConfig(
            enabled=_env_bool("RESILIENCE_ENABLED", True),
            max_stage_attempts=_env_int("RESILIENCE_MAX_STAGE_ATTEMPTS", 2),
            retry_backoff_seconds=_env_float("RESILIENCE_RETRY_BACKOFF_SECONDS", 0.0),
            dead_letter_enabled=_env_bool("RESILIENCE_DEAD_LETTER_ENABLED", True),
            checkpoint_enabled=_env_bool("RESILIENCE_CHECKPOINT_ENABLED", True),
            queue_limit=_env_int("RESILIENCE_QUEUE_LIMIT", 100),
            max_concurrent_runs=_env_int("RESILIENCE_MAX_CONCURRENT_RUNS", 1),
            default_stage_sla_seconds=_env_int("RESILIENCE_DEFAULT_STAGE_SLA_SECONDS", 900),
            stage_sla_seconds={key: int(value) for key, value in _env_str_dict("RESILIENCE_STAGE_SLA_SECONDS").items() if str(value).isdigit()},
            rollback_on_promotion_block=_env_bool("RESILIENCE_ROLLBACK_ON_PROMOTION_BLOCK", True),
        ),
    )
