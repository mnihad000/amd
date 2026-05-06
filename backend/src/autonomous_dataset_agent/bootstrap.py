from __future__ import annotations

import platform
import shutil
import sys

from .contracts import BootstrapReport


def run_bootstrap_checks(ffmpeg_path: str, yt_dlp_path: str) -> BootstrapReport:
    version = platform.python_version()
    supported_python = sys.version_info[:2] in {(3, 11), (3, 12)}
    resolved_ffmpeg = shutil.which(ffmpeg_path) if ffmpeg_path else None
    resolved_yt_dlp = shutil.which(yt_dlp_path) if yt_dlp_path else None

    warnings: list[str] = []
    if not supported_python:
        warnings.append(
            f"Backend is validated for Python 3.11/3.12, current interpreter is {version}."
        )
    if not resolved_ffmpeg:
        warnings.append("ffmpeg is not available on PATH; YouTube video frame extraction will be skipped.")
    if not resolved_yt_dlp:
        warnings.append("yt-dlp is not available on PATH; live YouTube discovery/download will be skipped.")

    return BootstrapReport(
        supported_python=supported_python,
        python_version=version,
        ffmpeg_available=resolved_ffmpeg is not None,
        ffmpeg_path=resolved_ffmpeg,
        yt_dlp_available=resolved_yt_dlp is not None,
        yt_dlp_path=resolved_yt_dlp,
        warnings=warnings,
    )
