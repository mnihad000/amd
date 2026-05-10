from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

from .config import JobConfig
from .contracts import JobPaths, SampleRecord, SourceMix, SourceRecord
from .utils import ensure_dir, read_json, slugify


def load_source_manifest(path: Path | None) -> list[SourceRecord]:
    if path is None or not path.exists():
        return []

    payload = read_json(path)
    raw_sources = payload.get("sources", payload) if isinstance(payload, dict) else payload
    sources: list[SourceRecord] = []
    for item in raw_sources:
        sources.append(
            SourceRecord(
                id=item["id"],
                source_type=item["source_type"],
                class_names=[value.lower() for value in item.get("class_names", [])],
                title=item.get("title", item["id"]),
                url=item.get("url"),
                local_path=item.get("local_path"),
                metadata=item.get("metadata", {}),
            )
        )
    return sources


def has_local_asset(source: SourceRecord) -> bool:
    return bool(source.local_path and Path(source.local_path).exists())


def usable_sources(sources: list[SourceRecord]) -> list[SourceRecord]:
    return [source for source in sources if has_local_asset(source)]


def collect_web_image_sources(sources: list[SourceRecord], classes: list[str]) -> list[SourceRecord]:
    class_set = set(classes)
    return [
        source
        for source in sources
        if source.source_type == "web_image"
        and class_set.intersection(source.class_names)
        and has_local_asset(source)
    ]


def collect_youtube_video_sources(sources: list[SourceRecord], classes: list[str]) -> list[SourceRecord]:
    class_set = set(classes)
    return [
        source
        for source in sources
        if source.source_type == "youtube_video"
        and class_set.intersection(source.class_names)
        and has_local_asset(source)
    ]


def extract_video_frames(
    sources: list[SourceRecord],
    job_paths: JobPaths,
    config: JobConfig,
    ffmpeg_available: bool,
) -> tuple[list[SampleRecord], list[str]]:
    samples: list[SampleRecord] = []
    notes: list[str] = []

    if not sources:
        return samples, notes
    if not ffmpeg_available:
        notes.append("Skipped video frame extraction because ffmpeg is unavailable.")
        return samples, notes

    for source in sources:
        if not source.local_path:
            notes.append(f"Skipped source {source.id}: missing local_path for video input.")
            continue

        video_path = Path(source.local_path)
        if not video_path.exists():
            notes.append(f"Skipped source {source.id}: local video path does not exist.")
            continue

        frame_dir = ensure_dir(job_paths.frames / slugify(source.id))
        output_pattern = str(frame_dir / "frame_%04d.jpg")
        command = [
            config.source.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            f"fps={config.source.frames_per_second}",
            "-frames:v",
            str(config.source.max_frames_per_video),
            output_pattern,
        ]

        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            notes.append(
                f"ffmpeg failed for {source.id}: {completed.stderr.strip() or 'unknown error'}"
            )
            continue

        frame_files = sorted(frame_dir.glob("frame_*.jpg"))
        for index, frame_file in enumerate(frame_files, start=1):
            timestamp = round(index / max(config.source.frames_per_second, 0.001), 3)
            samples.append(
                SampleRecord(
                    id=f"{source.id}_f_{index:04d}",
                    source_id=source.id,
                    source_type="video_frame",
                    class_names=source.class_names,
                    path=str(frame_file),
                    metadata={"title": source.title, **source.metadata},
                    derived_from=source.id,
                    timestamp_sec=timestamp,
                )
            )

    return samples, notes


def normalize_sources_to_samples(web_sources: list[SourceRecord], frame_samples: list[SampleRecord]) -> list[SampleRecord]:
    samples: list[SampleRecord] = list(frame_samples)

    for source in web_sources:
        if not has_local_asset(source):
            continue
        samples.append(
            SampleRecord(
                id=source.id,
                source_id=source.id,
                source_type="web_image",
                class_names=source.class_names,
                path=source.local_path,
                metadata={"title": source.title, **source.metadata},
            )
        )

    return samples


def rebalance_samples(
    samples: list[SampleRecord],
    mix: SourceMix,
    max_samples: int,
    min_per_class: int = 0,
) -> list[SampleRecord]:
    if not samples:
        return []

    ranked = sorted(samples, key=lambda item: item.quality_score or 0.0, reverse=True)
    limit = min(max_samples, len(ranked))
    if limit <= 0:
        return []

    target_web = round(limit * mix.web_target_ratio)
    target_video = limit - target_web

    selected: list[SampleRecord] = []
    selected_ids: set[str] = set()
    class_counts: Counter[str] = Counter()
    sample_classes: dict[str, set[str]] = {
        sample.id: {class_name.lower() for class_name in sample.class_names if class_name}
        for sample in ranked
    }

    def _add_sample(sample: SampleRecord) -> None:
        selected.append(sample)
        selected_ids.add(sample.id)
        for class_name in sample.class_names:
            class_counts[class_name.lower()] += 1

    if min_per_class > 0:
        all_classes = sorted(
            {
                class_name.lower()
                for sample in ranked
                for class_name in sample.class_names
                if class_name
            }
        )
        for class_name in all_classes:
            while class_counts[class_name] < min_per_class and len(selected) < limit:
                candidate = next(
                    (
                        sample
                        for sample in ranked
                        if sample.id not in selected_ids
                        and class_name in sample_classes.get(sample.id, set())
                    ),
                    None,
                )
                if candidate is None:
                    break
                _add_sample(candidate)

    web_count = sum(1 for sample in selected if sample.source_type == "web_image")
    video_count = len(selected) - web_count

    for sample in ranked:
        if len(selected) >= limit:
            break
        if sample.id in selected_ids:
            continue

        if sample.source_type == "web_image":
            if web_count < target_web or video_count >= target_video:
                _add_sample(sample)
                web_count += 1
        else:
            if video_count < target_video or web_count >= target_web:
                _add_sample(sample)
                video_count += 1

    for sample in ranked:
        if len(selected) >= limit:
            break
        if sample.id not in selected_ids:
            _add_sample(sample)

    return selected
