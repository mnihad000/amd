from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .contracts import CriticThresholds, SampleRecord
from .utils import sha256_file


@dataclass
class ImageSignals:
    width: int | None
    height: int | None
    aspect_ratio: float | None
    brightness_mean: float | None
    contrast_std: float | None
    sharpness_raw: float | None
    analysis_mode: str


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _extract_image_signals(path: Path) -> ImageSignals:
    try:
        from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError
    except ImportError:
        return ImageSignals(
            width=None,
            height=None,
            aspect_ratio=None,
            brightness_mean=None,
            contrast_std=None,
            sharpness_raw=None,
            analysis_mode="fallback_no_pillow",
        )

    try:
        with Image.open(path) as source_image:
            grayscale = source_image.convert("L")
            width, height = grayscale.size
            aspect_ratio = round(width / max(height, 1), 3)
            luminance_stats = ImageStat.Stat(grayscale)
            brightness_mean = float(luminance_stats.mean[0])
            contrast_std = float(luminance_stats.stddev[0])
            edge_image = grayscale.filter(ImageFilter.FIND_EDGES)
            edge_stats = ImageStat.Stat(edge_image)
            sharpness_raw = float(edge_stats.mean[0])
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"sample image unreadable: {exc}") from exc

    return ImageSignals(
        width=width,
        height=height,
        aspect_ratio=aspect_ratio,
        brightness_mean=brightness_mean,
        contrast_std=contrast_std,
        sharpness_raw=sharpness_raw,
        analysis_mode="pillow",
    )


def _brightness_range_score(brightness_mean: float, thresholds: CriticThresholds) -> float:
    lower = thresholds.min_brightness_mean
    upper = thresholds.max_brightness_mean
    if lower <= brightness_mean <= upper:
        return 1.0

    if brightness_mean < lower:
        return _clamp(1.0 - ((lower - brightness_mean) / max(lower, 1.0)))
    return _clamp(1.0 - ((brightness_mean - upper) / max(255.0 - upper, 1.0)))


def _normalized_signal_scores(
    sample: SampleRecord,
    signals: ImageSignals,
    thresholds: CriticThresholds,
) -> dict[str, float]:
    visibility_score = float(sample.metadata.get("visibility_score", 0.5))
    object_size_score = float(sample.metadata.get("object_size_score", 0.5))

    if signals.width is not None and signals.height is not None:
        width_ratio = _clamp(signals.width / max(float(thresholds.min_image_width), 1.0))
        height_ratio = _clamp(signals.height / max(float(thresholds.min_image_height), 1.0))
        size_score = round(width_ratio * height_ratio, 3)
    else:
        size_score = 1.0

    metadata_sharpness_score = _clamp(float(sample.metadata.get("blur_score", 0.5)))
    if signals.sharpness_raw is not None:
        sharpness_score = max(
            _clamp(signals.sharpness_raw / max(thresholds.min_sharpness_score * 2.0, 1.0)),
            metadata_sharpness_score,
        )
    else:
        sharpness_score = metadata_sharpness_score

    contrast_raw = signals.contrast_std if signals.contrast_std is not None else float(
        sample.metadata.get("contrast_std", thresholds.min_contrast_std)
    )
    metadata_contrast_score = _clamp(
        float(sample.metadata.get("contrast_std", thresholds.min_contrast_std))
        / max(thresholds.min_contrast_std * 2.0, 1.0)
    )
    contrast_score = max(
        _clamp(contrast_raw / max(thresholds.min_contrast_std * 2.0, 1.0)),
        metadata_contrast_score,
    )

    brightness_raw = signals.brightness_mean if signals.brightness_mean is not None else 128.0
    brightness_score = _brightness_range_score(brightness_raw, thresholds)

    metadata_bonus = _clamp((visibility_score + object_size_score) / 2.0)

    return {
        "sharpness_score": round(sharpness_score, 3),
        "contrast_score": round(contrast_score, 3),
        "brightness_score": round(brightness_score, 3),
        "size_score": round(size_score, 3),
        "metadata_bonus": round(metadata_bonus, 3),
        "visibility_score": round(visibility_score, 3),
        "object_size_score": round(object_size_score, 3),
    }


def score_and_filter_samples(
    samples: list[SampleRecord],
    thresholds: CriticThresholds,
) -> tuple[list[SampleRecord], list[SampleRecord], list[dict[str, object]]]:
    accepted: list[SampleRecord] = []
    rejected: list[SampleRecord] = []
    scores: list[dict[str, object]] = []
    seen_hashes: set[str] = set()

    for sample in samples:
        path = Path(sample.path)
        rejection_reasons: list[str] = []
        signals = ImageSignals(None, None, None, None, None, None, "uninitialized")

        if not path.exists():
            rejection_reasons.append("sample file missing")
        elif path.stat().st_size < 64:
            rejection_reasons.append("sample file too small")
        else:
            try:
                signals = _extract_image_signals(path)
            except ValueError as exc:
                has_metadata_fallback = any(
                    key in sample.metadata for key in ("blur_score", "visibility_score", "object_size_score")
                )
                is_partial_image = "broken data stream" in str(exc).lower()
                if has_metadata_fallback or is_partial_image:
                    signals = ImageSignals(None, None, None, None, None, None, "metadata_fallback_unreadable")
                    sample.metadata["critic_warning"] = str(exc)
                else:
                    rejection_reasons.append(str(exc))

        if not rejection_reasons and signals.width is not None and signals.width < thresholds.min_image_width:
            rejection_reasons.append("sample width below minimum threshold")
        if not rejection_reasons and signals.height is not None and signals.height < thresholds.min_image_height:
            rejection_reasons.append("sample height below minimum threshold")
        if (
            not rejection_reasons
            and signals.aspect_ratio is not None
            and (
                signals.aspect_ratio < thresholds.min_aspect_ratio
                or signals.aspect_ratio > thresholds.max_aspect_ratio
            )
        ):
            rejection_reasons.append("sample aspect ratio outside allowed range")

        content_hash = None
        if not rejection_reasons:
            content_hash = sha256_file(path)
            sample.content_hash = content_hash
            if content_hash in seen_hashes:
                rejection_reasons.append("exact duplicate of earlier sample")

        score_parts = _normalized_signal_scores(sample, signals, thresholds)
        sharpness_score = score_parts["sharpness_score"]
        contrast_score = score_parts["contrast_score"]
        brightness_score = score_parts["brightness_score"]
        size_score = score_parts["size_score"]
        metadata_bonus = score_parts["metadata_bonus"]
        visibility_score = score_parts["visibility_score"]
        object_size_score = score_parts["object_size_score"]
        blur_score = float(sample.metadata.get("blur_score", sharpness_score))

        quality_score = round(
            0.35 * sharpness_score
            + 0.20 * contrast_score
            + 0.15 * brightness_score
            + 0.20 * size_score
            + 0.10 * metadata_bonus,
            3,
        )
        sample.quality_score = quality_score

        if quality_score < thresholds.min_quality_score and "exact duplicate of earlier sample" not in rejection_reasons:
            rejection_reasons.append("quality score below threshold")

        if rejection_reasons:
            sample.decision = "reject"
            sample.rejection_reasons = rejection_reasons
            rejected.append(sample)
        else:
            sample.decision = "accept"
            accepted.append(sample)
            if content_hash:
                seen_hashes.add(content_hash)

        scores.append(
            {
                "sample_id": sample.id,
                "source_type": sample.source_type,
                "quality_score": quality_score,
                "blur_score": blur_score,
                "visibility_score": visibility_score,
                "object_size_score": object_size_score,
                "width": signals.width,
                "height": signals.height,
                "aspect_ratio": signals.aspect_ratio,
                "brightness_mean": signals.brightness_mean,
                "contrast_std": signals.contrast_std,
                "sharpness_score": sharpness_score,
                "size_score": size_score,
                "analysis_mode": signals.analysis_mode,
                "decision": sample.decision,
                "rejection_reasons": sample.rejection_reasons,
            }
        )

    return accepted, rejected, scores
