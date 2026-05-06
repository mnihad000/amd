from __future__ import annotations

from collections import Counter

from .contracts import ClassPlanEntry, CriticThresholds, LabelRecord, SampleRecord, SourceRecord

GENERIC_CLASS_WORDS = {"object", "item", "thing", "stuff", "vehicle", "machine"}


def normalize_classes(classes: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_class in classes:
        candidate = raw_class.strip().lower()
        if not candidate or candidate in seen:
            continue
        normalized.append(candidate)
        seen.add(candidate)
    return normalized


def build_initial_class_plan(prompt: str, classes: list[str]) -> list[ClassPlanEntry]:
    prompt_lower = prompt.lower()
    plan: list[ClassPlanEntry] = []

    for class_name in normalize_classes(classes):
        score = 0.6
        reasons: list[str] = []

        if class_name in prompt_lower:
            score += 0.15
            reasons.append("Prompt explicitly references the class.")
        else:
            reasons.append("Prompt does not mention the class verbatim, but the class remains eligible.")

        tokens = class_name.split()
        if any(token in GENERIC_CLASS_WORDS for token in tokens):
            score -= 0.25
            reasons.append("Class name is visually generic and may need stronger evidence.")

        if len(tokens) > 4:
            score -= 0.1
            reasons.append("Class phrase is long and may be harder to source consistently.")

        score = max(0.0, min(1.0, score))
        initial_state = "ready" if score >= 0.7 else "risky"

        plan.append(
            ClassPlanEntry(
                name=class_name,
                initial_state=initial_state,
                final_state=initial_state,
                feasibility_score=round(score, 3),
                reasons=reasons,
            )
        )

    return plan


def attach_source_counts(plan: list[ClassPlanEntry], sources: list[SourceRecord]) -> list[ClassPlanEntry]:
    counts = Counter()
    for source in sources:
        for class_name in source.class_names:
            counts[class_name.lower()] += 1

    for entry in plan:
        entry.discovered_sources = counts.get(entry.name, 0)
        if entry.discovered_sources == 0:
            entry.reasons.append("No matching usable sources were discovered for this run.")
            if entry.final_state == "ready":
                entry.final_state = "risky"
    return plan


def determine_label_admission(
    plan: list[ClassPlanEntry],
    accepted_samples: list[SampleRecord],
    thresholds: CriticThresholds,
) -> list[str]:
    counts = Counter()
    for sample in accepted_samples:
        for class_name in sample.class_names:
            counts[class_name.lower()] += 1

    admitted: list[str] = []
    for entry in plan:
        sample_count = counts.get(entry.name, 0)
        if entry.final_state == "blocked":
            continue
        if sample_count >= thresholds.min_samples_to_label:
            admitted.append(entry.name)
        else:
            entry.final_state = "risky"
            entry.accepted_samples = sample_count
            entry.reasons.append(
                f"Only {sample_count} accepted samples before labeling; below labeling threshold."
            )
    return admitted


def finalize_class_plan(
    plan: list[ClassPlanEntry],
    accepted_samples: list[SampleRecord],
    label_records: list[LabelRecord],
    thresholds: CriticThresholds,
) -> list[ClassPlanEntry]:
    sample_counts = Counter()
    confidence_totals = Counter()
    confidence_counts = Counter()

    for sample in accepted_samples:
        for class_name in sample.class_names:
            sample_counts[class_name.lower()] += 1

    for record in label_records:
        for box in record.boxes:
            confidence_totals[box.class_name.lower()] += box.confidence
            confidence_counts[box.class_name.lower()] += 1

    for entry in plan:
        entry.accepted_samples = sample_counts.get(entry.name, 0)
        if confidence_counts.get(entry.name):
            entry.avg_label_confidence = round(
                confidence_totals[entry.name] / confidence_counts[entry.name],
                3,
            )

        if entry.accepted_samples == 0:
            entry.final_state = "blocked"
            entry.reasons.append("No accepted samples survived filtering for this class.")
            continue

        if entry.accepted_samples < thresholds.min_samples_for_training:
            entry.final_state = "risky"
            entry.reasons.append(
                "Accepted sample count is below the training threshold for this class."
            )
            continue

        if entry.avg_label_confidence is not None and entry.avg_label_confidence < thresholds.min_label_confidence:
            entry.final_state = "risky"
            entry.reasons.append("Average label confidence is below the minimum training threshold.")
            continue

        entry.final_state = "ready"

    return plan
