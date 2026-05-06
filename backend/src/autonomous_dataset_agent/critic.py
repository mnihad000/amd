from __future__ import annotations

from pathlib import Path

from .contracts import CriticThresholds, SampleRecord
from .utils import sha256_file


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

        if not path.exists():
            rejection_reasons.append("sample file missing")
        elif path.stat().st_size < 64:
            rejection_reasons.append("sample file too small")

        content_hash = None
        if not rejection_reasons:
            content_hash = sha256_file(path)
            sample.content_hash = content_hash
            if content_hash in seen_hashes:
                rejection_reasons.append("exact duplicate of earlier sample")

        blur_score = float(sample.metadata.get("blur_score", 0.75))
        visibility_score = float(sample.metadata.get("visibility_score", 0.75))
        object_size_score = float(sample.metadata.get("object_size_score", 0.75))
        duplicate_score = 1.0 if rejection_reasons and "duplicate" in " ".join(rejection_reasons) else 0.0

        quality_score = round(
            0.3 * blur_score
            + 0.3 * visibility_score
            + 0.2 * object_size_score
            + 0.2 * (1.0 - duplicate_score),
            3,
        )
        sample.quality_score = quality_score

        if quality_score < thresholds.min_quality_score:
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
                "decision": sample.decision,
                "rejection_reasons": sample.rejection_reasons,
            }
        )

    return accepted, rejected, scores
