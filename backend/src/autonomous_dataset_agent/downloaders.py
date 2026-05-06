from __future__ import annotations

import hashlib
import mimetypes
from collections import deque
from pathlib import Path
from urllib import error, parse, request

from .config import SourceConfig
from .contracts import JobPaths, SourceRecord
from .utils import ensure_dir, sha256_file, slugify

_IMAGE_FORMAT_EXTENSIONS = {
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "png": ".png",
    "webp": ".webp",
    "gif": ".gif",
    "bmp": ".bmp",
}


def normalize_url(url: str) -> str:
    parsed = parse.urlsplit(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = parse.urlencode(sorted(parse.parse_qsl(parsed.query, keep_blank_values=True)))
    return parse.urlunsplit((scheme, netloc, path, query, ""))


def extract_domain(url: str | None) -> str:
    if not url:
        return ""
    return parse.urlsplit(url).netloc.lower()


def build_source_id(prefix: str, class_name: str, url: str) -> str:
    digest = hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{slugify(class_name)}_{digest}"


def round_robin_select(grouped_sources: dict[str, list[SourceRecord]], global_limit: int) -> list[SourceRecord]:
    if global_limit <= 0:
        return []

    queues = {key: deque(value) for key, value in grouped_sources.items() if value}
    ordered_keys = [key for key, value in grouped_sources.items() if value]
    selected: list[SourceRecord] = []

    while ordered_keys and len(selected) < global_limit:
        next_round: list[str] = []
        for key in ordered_keys:
            queue = queues[key]
            if queue and len(selected) < global_limit:
                selected.append(queue.popleft())
            if queue:
                next_round.append(key)
        ordered_keys = next_round

    return selected


def _guess_extension(url: str, content_type: str | None, image_format: str | None) -> str:
    if image_format:
        normalized_format = image_format.lower()
        if normalized_format in _IMAGE_FORMAT_EXTENSIONS:
            return _IMAGE_FORMAT_EXTENSIONS[normalized_format]
    if content_type:
        extension = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
        if extension:
            return extension
    suffix = Path(parse.urlsplit(url).path).suffix.lower()
    return suffix if suffix else ".img"


def _build_opener(user_agent: str) -> request.OpenerDirector:
    opener = request.build_opener()
    opener.addheaders = [("User-Agent", user_agent)]
    return opener


def download_image_sources(
    sources: list[SourceRecord],
    job_paths: JobPaths,
    config: SourceConfig,
) -> tuple[list[SourceRecord], list[str]]:
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        for source in sources:
            source.metadata["download_status"] = "failed"
            source.metadata["download_error"] = "Pillow is required for image validation but is not installed."
        return sources, ["Pillow is not installed; skipping web image downloads."]

    notes: list[str] = []
    if not sources:
        return sources, notes

    web_root = ensure_dir(job_paths.downloads / "web")
    opener = _build_opener(config.download_user_agent)
    seen_hashes: dict[str, str] = {}

    for source in sources:
        class_name = source.class_names[0] if source.class_names else "unknown"
        target_dir = ensure_dir(web_root / slugify(class_name))
        metadata = dict(source.metadata)
        download_error = ""

        for attempt in range(max(1, config.download_retry_count + 1)):
            try:
                response = opener.open(source.url or "", timeout=config.download_timeout_seconds)
                payload = response.read()
                content_type = response.headers.get("Content-Type", "")
                if not content_type.lower().startswith("image/"):
                    raise ValueError(f"non-image response content type: {content_type or 'unknown'}")

                temp_path = target_dir / f"{source.id}.download"
                temp_path.write_bytes(payload)
                with Image.open(temp_path) as image:
                    image.verify()
                with Image.open(temp_path) as image:
                    image_format = image.format

                content_hash = sha256_file(temp_path)
                if content_hash in seen_hashes:
                    temp_path.unlink(missing_ok=True)
                    metadata["download_status"] = "duplicate"
                    metadata["download_error"] = "duplicate content"
                    download_error = "duplicate content"
                    break

                extension = _guess_extension(source.url or source.id, content_type, image_format)
                final_path = target_dir / f"{slugify(class_name)}-{metadata.get('provider', 'web')}-{source.id}{extension}"
                temp_path.replace(final_path)
                source.local_path = str(final_path)
                metadata["download_status"] = "downloaded"
                metadata["download_error"] = None
                seen_hashes[content_hash] = str(final_path)
                download_error = ""
                break
            except (error.URLError, TimeoutError, ValueError, OSError, UnidentifiedImageError) as exc:
                download_error = str(exc)
                if attempt + 1 >= max(1, config.download_retry_count + 1):
                    metadata["download_status"] = "failed"
                    metadata["download_error"] = download_error
                continue

        if download_error:
            notes.append(f"Image download failed for {source.id}: {download_error}")
        source.metadata = metadata

    return sources, notes
