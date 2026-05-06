from __future__ import annotations

import subprocess
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


def collect_web_image_sources(sources: list[SourceRecord], classes: list[str]) -> list[SourceRecord]:
    class_set = set(classes)
    return [
        source
        for source in sources
        if source.source_type == "web_image" and class_set.intersection(source.class_names)
    ]


def collect_youtube_video_sources(sources: list[SourceRecord], classes: list[str]) -> list[SourceRecord]:
    class_set = set(classes)
    return [
        source
        for source in sources
        if source.source_type == "youtube_video" and class_set.intersection(source.class_names)
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
        if not source.local_path:
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


def rebalance_samples(samples: list[SampleRecord], mix: SourceMix, max_samples: int) -> list[SampleRecord]:
    if not samples:
        return []

    ranked = sorted(samples, key=lambda item: item.quality_score or 0.0, reverse=True)
    limit = min(max_samples, len(ranked))
    target_web = round(limit * mix.web_target_ratio)
    target_video = limit - target_web

    selected: list[SampleRecord] = []
    web_count = 0
    video_count = 0

    for sample in ranked:
        if len(selected) >= limit:
            break

        if sample.source_type == "web_image":
            if web_count < target_web or video_count >= target_video:
                selected.append(sample)
                web_count += 1
        else:
            if video_count < target_video or web_count >= target_web:
                selected.append(sample)
                video_count += 1

    for sample in ranked:
        if len(selected) >= limit:
            break
        if sample not in selected:
            selected.append(sample)

    return selected
