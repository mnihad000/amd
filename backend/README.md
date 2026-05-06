# Backend MVP

This backend is a CLI-first dataset pipeline for the Autonomous Dataset Agent project.

Current capabilities:

- accept a prompt and class list
- plan class feasibility dynamically
- ingest sources in either `manifest` or `live` mode
- discover web images and YouTube videos automatically in `live` mode
- extract frames from local or downloaded videos with `ffmpeg`
- normalize and filter samples
- label accepted samples through a provider interface
- export YOLO dataset artifacts and run manifests

The backend still preserves an offline-first path:

- `manifest` mode works from a local JSON manifest
- the `mock` label provider supports dry runs and tests
- `live` mode writes the same `source_manifest.json` artifact used by downstream stages

## Dependencies

Python package dependencies:

```bash
cd backend
pip install -r requirements.txt
```

Optional training dependencies:

```bash
pip install -r requirements-train.txt
```

External CLI/runtime dependencies:

- `ffmpeg` for video frame extraction
- `yt-dlp` for live YouTube discovery and download

Optional provider credential:

- `BING_SEARCH_API_KEY` if you want API-backed image-search fallback after DuckDuckGo

## Quick start

PowerShell examples from repo root:

```powershell
$env:PYTHONPATH="backend/src"
python -m autonomous_dataset_agent.cli run --prompt "forklift in a warehouse" --classes "forklift,pallet jack"
```

You can override the source mode per run:

```powershell
python -m autonomous_dataset_agent.cli run --prompt "forklift in a warehouse" --classes "forklift" --source-mode live
```

## API quick start

The FastAPI service now exposes an async run lifecycle intended for browser polling and the `frontend/app` dashboard:

```powershell
cd backend
ada-api --host 127.0.0.1 --port 8000
```

Endpoints:

- `POST /runs`
  Returns `202 Accepted` with an initial `queued` run resource.
- `GET /runs`
  Returns recent runs ordered by `updated_at` descending.
- `GET /runs/{job_id}`
  Returns lifecycle status, stage history, timestamps, cancellation flag, summary, and error details.
- `POST /runs/{job_id}/cancel`
  Requests cooperative cancellation for `queued` or `running` jobs.
- `GET /health`
  Returns queue depth, active worker count, and configured artifact/index paths.
- `GET /runs/{job_id}/artifacts`
  Returns the artifact index with API URLs and safe file URLs.
- `GET /runs/{job_id}/artifacts/{artifact_name}`
  Returns parsed JSON content for known report artifacts.
- `GET /runs/{job_id}/files/{relative_path}`
  Serves preview-safe files rooted to the run directory.

Lifecycle statuses:

- `queued`
- `running`
- `completed`
- `failed`

Stage timeline:

- `bootstrap`
- `class_planning`
- `source_resolution`
- `frame_extraction`
- `critic`
- `labeling`
- `dataset_build`
- `training`
- `evaluation`
- `iteration`
- `finalize`

## Source modes

### Manifest mode

Default mode:

- reads `SOURCE_MANIFEST_PATH`
- expects local files for `web_image` and `youtube_video`
- best for offline tests, deterministic runs, and canned demos

Manifest shape:

```json
{
  "sources": [
    {
      "id": "web_001",
      "source_type": "web_image",
      "class_names": ["forklift"],
      "title": "Forklift warehouse photo",
      "local_path": "C:/data/forklift_1.png",
      "url": "https://example.com/forklift_1.png",
      "metadata": {
        "blur_score": 0.9,
        "visibility_score": 0.8,
        "object_size_score": 0.85
      }
    }
  ]
}
```

Supported `source_type` values:

- `web_image`
- `youtube_video`

### Live mode

Live mode discovers and downloads sources before the existing pipeline runs:

- generates deterministic search queries from `prompt + classes`
- searches web images per class using configured provider order
- searches YouTube per class with `yt-dlp`
- downloads selected assets under the run `downloads/` tree
- writes discovered and attempted sources to `reports/source_manifest.json`
- continues with the existing critic, labeling, dataset, training, and evaluation flow

Useful env vars:

- `SOURCE_MODE=manifest|live`
- `WEB_SEARCH_PROVIDER_ORDER=duckduckgo,bing`
- `BING_SEARCH_API_KEY=...`
- `YT_DLP_PATH=yt-dlp`
- `WEB_IMAGE_SEARCH_RESULTS_PER_CLASS=10`
- `WEB_IMAGE_DOWNLOADS_PER_CLASS=4`
- `YOUTUBE_SEARCH_RESULTS_PER_CLASS=6`
- `YOUTUBE_DOWNLOADS_PER_CLASS=2`
- `MAX_DOWNLOADED_SOURCES=50`
- `MIN_IMAGE_WIDTH=160`
- `MIN_IMAGE_HEIGHT=160`
- `MIN_SHARPNESS_SCORE=5.0`
- `MIN_CONTRAST_STD=8.0`
- `MIN_BRIGHTNESS_MEAN=35.0`
- `MAX_BRIGHTNESS_MEAN=220.0`
- `MIN_ASPECT_RATIO=0.2`
- `MAX_ASPECT_RATIO=5.0`

## Artifacts

Each run writes artifacts under `backend/artifacts/<job-id>/` by default:

- `reports/bootstrap.json`
- `reports/class_plan.json`
- `reports/source_manifest.json`
- `reports/sample_manifest.json`
- `reports/frame_scores.json`
- `reports/accepted_frames.json`
- `reports/labels_manifest.json`
- `reports/dataset_manifest.json`
- `reports/training_results.json`
- `reports/evaluation_report.json`
- `reports/run_summary.json`

In live mode, `source_manifest.json` includes provenance metadata such as:

- `provider`
- `query`
- `domain`
- `rank`
- `download_status`
- `download_error`
- `video_id`, `uploader`, `duration_sec`, `format_id` for YouTube when available

## Failure handling

Expected non-fatal cases:

- if DuckDuckGo search fails or returns nothing, the backend tries the next configured provider
- if all web providers fail for a class, the run continues
- if `yt-dlp` is unavailable or a YouTube search/download fails, the run continues with web-only sources
- if `ffmpeg` is unavailable, video frame extraction is skipped and web-image sources still run
- if zero usable sources survive discovery, the run completes with blocked/risky classes instead of crashing

## Debugging

If a live run underperforms, inspect these first:

- `reports/bootstrap.json` for missing `ffmpeg` or `yt-dlp`
- `reports/source_manifest.json` for provider/query provenance and `download_status`
- `reports/sample_manifest.json` for normalized image/frame inputs
- `reports/frame_scores.json` and `reports/accepted_frames.json` for critic outcomes
- `reports/run_summary.json` for the final admitted/deferred/blocked classes
