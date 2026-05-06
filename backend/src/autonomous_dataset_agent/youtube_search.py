from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path

from .config import SourceConfig
from .contracts import JobPaths, SourceRecord
from .downloaders import build_source_id, normalize_url
from .utils import ensure_dir, slugify


def search_youtube_candidates(
    classes: list[str],
    queries_by_class: dict[str, list[str]],
    config: SourceConfig,
    yt_dlp_available: bool,
) -> tuple[dict[str, list[SourceRecord]], list[str]]:
    notes: list[str] = []
    grouped: dict[str, list[SourceRecord]] = {}

    if not yt_dlp_available:
        notes.append("yt-dlp is unavailable; skipping YouTube discovery.")
        return grouped, notes

    for class_name in classes:
        candidates: list[SourceRecord] = []
        seen_ids: set[str] = set()

        for query_index, query in enumerate(queries_by_class.get(class_name, [])):
            command = [
                config.yt_dlp_path,
                "--dump-single-json",
                "--skip-download",
                "--flat-playlist",
                "--no-warnings",
                "--quiet",
                f"ytsearch{config.youtube_search_results_per_class}:{query}",
            ]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                notes.append(
                    f"yt-dlp search failed for '{query}': {completed.stderr.strip() or 'unknown error'}"
                )
                continue

            try:
                payload = json.loads(completed.stdout or "{}")
            except json.JSONDecodeError as exc:
                notes.append(f"yt-dlp search returned invalid JSON for '{query}': {exc}")
                continue

            entries = payload.get("entries", [])
            for result_index, entry in enumerate(entries):
                video_id = str(entry.get("id") or "").strip()
                if not video_id or video_id in seen_ids:
                    continue

                watch_url = str(entry.get("url") or f"https://www.youtube.com/watch?v={video_id}")
                if not watch_url.startswith("http"):
                    watch_url = f"https://www.youtube.com/watch?v={video_id}"
                candidates.append(
                    SourceRecord(
                        id=build_source_id("youtube", class_name, normalize_url(watch_url)),
                        source_type="youtube_video",
                        class_names=[class_name],
                        title=str(entry.get("title") or class_name),
                        url=watch_url,
                        local_path=None,
                        metadata={
                            "provider": "yt-dlp",
                            "query": query,
                            "rank": result_index,
                            "query_index": query_index,
                            "video_id": video_id,
                            "uploader": entry.get("uploader") or entry.get("channel"),
                            "duration_sec": entry.get("duration"),
                            "format_id": entry.get("format_id"),
                        },
                    )
                )
                seen_ids.add(video_id)

        uploader_counts = Counter(str(item.metadata.get("uploader") or "") for item in candidates)
        candidates.sort(
            key=lambda candidate: (
                int(candidate.metadata.get("query_index", 999)),
                int(candidate.metadata.get("rank", 999)),
                max(0, uploader_counts.get(str(candidate.metadata.get("uploader") or ""), 0) - 1),
                candidate.id,
            )
        )
        for rank, candidate in enumerate(candidates, start=1):
            candidate.metadata["rank"] = rank

        grouped[class_name] = candidates[: config.youtube_search_results_per_class]

    return grouped, notes


def download_youtube_sources(
    sources: list[SourceRecord],
    job_paths: JobPaths,
    config: SourceConfig,
    yt_dlp_available: bool,
) -> tuple[list[SourceRecord], list[str]]:
    notes: list[str] = []
    if not sources:
        return sources, notes
    if not yt_dlp_available:
        notes.append("yt-dlp is unavailable; skipping YouTube downloads.")
        return sources, notes

    youtube_root = ensure_dir(job_paths.downloads / "youtube")
    for source in sources:
        class_name = source.class_names[0] if source.class_names else "unknown"
        target_dir = ensure_dir(youtube_root / slugify(class_name))
        template = str(target_dir / "%(id)s-%(title).120B.%(ext)s")
        command = [
            config.yt_dlp_path,
            "--no-playlist",
            "--no-progress",
            "--quiet",
            "--print",
            "after_move:filepath",
            "-o",
            template,
            source.url or "",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        metadata = dict(source.metadata)
        if completed.returncode != 0:
            metadata["download_status"] = "failed"
            metadata["download_error"] = completed.stderr.strip() or "unknown error"
            notes.append(f"YouTube download failed for {source.id}: {metadata['download_error']}")
            source.metadata = metadata
            continue

        output_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        downloaded_path = Path(output_lines[-1]) if output_lines else None
        if not downloaded_path or not downloaded_path.exists():
            metadata["download_status"] = "failed"
            metadata["download_error"] = "yt-dlp did not report a downloaded file path"
            notes.append(f"YouTube download failed for {source.id}: {metadata['download_error']}")
            source.metadata = metadata
            continue

        source.local_path = str(downloaded_path)
        metadata["download_status"] = "downloaded"
        metadata["download_error"] = None
        source.metadata = metadata

    return sources, notes
