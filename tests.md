# TESTS.md

# Autonomous Dataset Agent - Testing Guide

This guide explains how to test the project **as it exists right now**.

Current reality:

- the backend is **CLI-first**
- there is **no FastAPI server or Swagger UI yet**
- backend source ingestion supports both **manifest mode** and **live mode**
- Gemini labeling is implemented behind a provider interface
- `mock` labeling is available for offline testing
- `ffmpeg`-based video extraction is wired, but only works if `ffmpeg` is installed on your machine
- `yt-dlp` powers live YouTube discovery/download when installed

If an API server is added later, this document should be expanded with endpoint-by-endpoint Swagger instructions.

---

## 1. What You Can Test Right Now

### Backend
- unit tests
- CLI pipeline execution
- dynamic class admission
- artifact generation
- mock labeling flow
- manifest-driven web-image ingestion
- live web-image discovery/download
- live YouTube discovery/download
- optional Gemini labeling path
- optional `ffmpeg` video-frame extraction path

### Frontend
- existing Next.js UI startup
- visual shell / current pages

### Not available yet
- FastAPI endpoints
- Swagger UI
- live backend API integration with frontend

---

## 2. Folder Reference

Run commands from these folders:

- repo root: `C:\Users\nihad\Desktop\amd`
- backend package root: `C:\Users\nihad\Desktop\amd\backend`
- frontend app root: `C:\Users\nihad\Desktop\amd\frontend`

In VS Code:

1. Open the repo folder.
2. Open the integrated terminal.
3. Make sure you are in the correct folder before running each command.

---

## 3. Backend Prerequisites

### Python

Recommended backend Python:

- `3.11` or `3.12`

Current local machine note:

- this repo was tested here with Python `3.13.3`
- the backend warns if you are not on `3.11` or `3.12`

Check Python:

```powershell
python --version
```

### ffmpeg

Required only for video-frame extraction.

Check `ffmpeg`:

```powershell
ffmpeg -version
```

If this fails, video extraction will be skipped by the pipeline.

### Environment file

There is an example env file at:

- [`.env.example`](/C:/Users/nihad/Desktop/amd/.env.example)

You can copy it to `.env` and edit values if needed.

Minimum useful settings for local backend testing:

```env
SOURCE_MODE=manifest
LABEL_PROVIDER=mock
SOURCE_MANIFEST_PATH=backend/examples/source_manifest.json
ENABLE_TRAINING=false
```

Minimum useful settings for live mode:

```env
SOURCE_MODE=live
LABEL_PROVIDER=mock
ENABLE_TRAINING=false
YT_DLP_PATH=yt-dlp
FFMPEG_PATH=ffmpeg
WEB_SEARCH_PROVIDER_ORDER=duckduckgo,bing
```

If you want Gemini testing:

```env
LABEL_PROVIDER=gemini
LABEL_API_KEY=your_real_key_here
```

---

## 4. Backend Unit Tests

These tests validate the current backend scaffold without needing live APIs.

### What they cover

- class planner behavior
- class blocking when no usable samples exist
- CLI pipeline orchestration with mock labeling
- run summary artifact generation
- live query / budget / fallback helpers
- mocked live ingestion orchestration

### Command

Go to repo root:

```powershell
cd C:\Users\nihad\Desktop\amd
```

Run:

```powershell
python -m unittest discover backend/tests
```

### Expected result

You should see output similar to:

```text
...
----------------------------------------------------------------------
Ran 3 tests in ...

OK
```

### If it fails

Check:

- Python can run from the terminal
- the `backend/` folder still exists
- the repo is being run from the correct working directory

---

## 5. Backend CLI Pipeline Test

This is the main end-to-end test path right now.

It does **not** use Swagger or HTTP. You run the backend directly from the terminal.

### Step 1: go to repo root

```powershell
cd C:\Users\nihad\Desktop\amd
```

### Step 2: set safe local env values

For a dry run without real API calls, use `mock` labeling.

PowerShell:

```powershell
$env:LABEL_PROVIDER="mock"
$env:SOURCE_MODE="manifest"
$env:SOURCE_MANIFEST_PATH="backend/examples/source_manifest.json"
$env:ENABLE_TRAINING="false"
```

### Step 3: run the pipeline

```powershell
$env:PYTHONPATH="backend/src"
python -m autonomous_dataset_agent.cli run --prompt "forklift in a warehouse" --classes "forklift,pallet jack"
```

### Expected behavior

The CLI prints a JSON run summary.

It should include fields like:

- `job_id`
- `requested_classes`
- `admitted_classes`
- `deferred_classes`
- `blocked_classes`
- `artifact_paths`

### Important note

The example manifest currently contains placeholder local paths:

- [backend/examples/source_manifest.json](/C:/Users/nihad/Desktop/amd/backend/examples/source_manifest.json)

To make the pipeline produce real accepted samples, replace the placeholder image/video paths with files that exist on your machine.

---

## 6. Testing with Real Local Images

This is the best current manual backend test.

### Step 1: prepare some local images

Make a folder somewhere on your machine with a few images for classes you want to test, for example:

```text
C:\Users\nihad\Desktop\amd\test_assets\
```

Example files:

- `forklift_1.jpg`
- `forklift_2.jpg`
- `pallet_jack_1.jpg`

### Step 2: edit the source manifest

Open:

- [backend/examples/source_manifest.json](/C:/Users/nihad/Desktop/amd/backend/examples/source_manifest.json)

Replace the placeholder `local_path` values with real image paths.

Example:

```json
{
  "id": "forklift_001",
  "source_type": "web_image",
  "class_names": ["forklift"],
  "title": "Forklift test image",
  "local_path": "C:/Users/nihad/Desktop/amd/test_assets/forklift_1.jpg",
  "metadata": {
    "blur_score": 0.9,
    "visibility_score": 0.85,
    "object_size_score": 0.8
  }
}
```

### Step 3: run the CLI again

```powershell
$env:PYTHONPATH="backend/src"
$env:SOURCE_MODE="manifest"
$env:LABEL_PROVIDER="mock"
$env:SOURCE_MANIFEST_PATH="backend/examples/source_manifest.json"
python -m autonomous_dataset_agent.cli run --prompt "forklift and pallet jack in a warehouse" --classes "forklift,pallet jack"
```

### Expected result

If your file paths are correct and you have enough distinct samples:

- some classes should become `admitted`
- dataset artifacts should be generated
- JSON reports should be written under `backend/artifacts/...`

---

## 7. Testing Dynamic Class Admission

This tests the approved “accept any class input, then decide feasibility” behavior.

### Example command

```powershell
$env:PYTHONPATH="backend/src"
$env:SOURCE_MODE="manifest"
$env:LABEL_PROVIDER="mock"
$env:SOURCE_MANIFEST_PATH="backend/examples/source_manifest.json"
python -m autonomous_dataset_agent.cli run --prompt "forklift and pallet jack in a warehouse" --classes "forklift,pallet jack,ghost,unknown vehicle"
```

### What to inspect

Look at the terminal JSON output and at:

- `class_plan.json`
- `run_summary.json`

These are written under the run’s reports folder inside:

- `backend/artifacts/<job-id>/reports/`

### Expected behavior

- real classes with enough usable sources should move toward `ready`
- weak classes should become `risky`
- classes with no usable source support should become `blocked`

This is one of the most important backend behaviors to validate.

---

## 8. Testing Artifact Generation

After a CLI run, inspect the generated artifact directory.

### Where artifacts go

By default:

- `backend/artifacts/<job-id>/`

### Important files to check

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

### How to inspect quickly in PowerShell

```powershell
Get-ChildItem -Recurse backend\artifacts
```

### What to verify

- files were created
- JSON is readable
- class states match your expectations
- source breakdown exists
- notes mention warnings if `ffmpeg` or training is unavailable

---

## 9. Testing Label Providers

## A. Mock provider

Use this for safe offline testing.

```powershell
$env:LABEL_PROVIDER="mock"
```

Expected:

- no live API call
- boxes are generated for admitted classes
- labels can validate and move into dataset creation

## B. Gemini provider

Use this only if you have a real API key.

```powershell
$env:LABEL_PROVIDER="gemini"
$env:LABEL_API_KEY="your_real_key_here"
```

Then run:

```powershell
$env:PYTHONPATH="backend/src"
python -m autonomous_dataset_agent.cli run --prompt "forklift in a warehouse" --classes "forklift"
```

### Expected behavior

- the backend attempts a live Gemini labeling call for admitted samples
- if the response parses correctly, labels should be validated and exported

### What to check if it fails

- `LABEL_API_KEY` is set
- your image paths in the source manifest are real
- internet access is available
- `labels_manifest.json` contains provider error notes if parsing or network fails

---

## 10. Testing ffmpeg Video Extraction

This only works if `ffmpeg` is installed and you have a real local video file.

### Step 1: verify ffmpeg

```powershell
ffmpeg -version
```

### Step 2: add a real local video path to the source manifest

Edit:

- [backend/examples/source_manifest.json](/C:/Users/nihad/Desktop/amd/backend/examples/source_manifest.json)

Example record:

```json
{
  "id": "video_001",
  "source_type": "youtube_video",
  "class_names": ["forklift"],
  "title": "Forklift test video",
  "local_path": "C:/Users/nihad/Desktop/amd/test_assets/forklift.mp4",
  "metadata": {
    "blur_score": 0.8,
    "visibility_score": 0.8,
    "object_size_score": 0.75
  }
}
```

### Step 3: run the pipeline

```powershell
$env:PYTHONPATH="backend/src"
$env:LABEL_PROVIDER="mock"
$env:SOURCE_MODE="manifest"
python -m autonomous_dataset_agent.cli run --prompt "forklift in a warehouse" --classes "forklift"
```

### Expected result

If `ffmpeg` works and the video path is real:

- extracted frames should appear under:
  - `backend/artifacts/<job-id>/frames/`
- frame-derived samples should appear in:
  - `sample_manifest.json`
- frame scoring should appear in:
  - `frame_scores.json`

### If it fails

Check:

- the video file path exists
- `ffmpeg` is installed
- `bootstrap.json` and `run_summary.json` for warnings

---

## 11. Testing Optional Training

Training is currently optional and depends on Ultralytics being installed.

### Step 1: enable training

```powershell
$env:ENABLE_TRAINING="true"
```

### Step 2: run the pipeline

```powershell
$env:PYTHONPATH="backend/src"
$env:LABEL_PROVIDER="mock"
$env:SOURCE_MODE="manifest"
python -m autonomous_dataset_agent.cli run --prompt "forklift in a warehouse" --classes "forklift"
```

---

## 12. Testing Live Source Ingestion

Live mode is the new path that searches and downloads sources automatically before the existing pipeline runs.

### Prerequisites

Check `yt-dlp`:

```powershell
yt-dlp --version
```

Check `ffmpeg` if you want video frames:

```powershell
ffmpeg -version
```

### A. Live mode with web images only

```powershell
cd C:\Users\nihad\Desktop\amd
$env:PYTHONPATH="backend/src"
$env:SOURCE_MODE="live"
$env:LABEL_PROVIDER="mock"
$env:ENABLE_TRAINING="false"
python -m autonomous_dataset_agent.cli run --prompt "forklift in a warehouse" --classes "forklift"
```

What to verify:

- `reports/source_manifest.json` contains `provider`, `query`, `domain`, and `download_status`
- downloaded images exist under `downloads/web/`
- `sample_manifest.json` includes `web_image` samples with local paths

### B. Live mode with mixed web + YouTube

```powershell
cd C:\Users\nihad\Desktop\amd
$env:PYTHONPATH="backend/src"
$env:SOURCE_MODE="live"
$env:LABEL_PROVIDER="mock"
$env:ENABLE_TRAINING="false"
$env:YT_DLP_PATH="yt-dlp"
$env:FFMPEG_PATH="ffmpeg"
python -m autonomous_dataset_agent.cli run --prompt "forklift in a warehouse" --classes "forklift,pallet jack"
```

What to verify:

- `reports/source_manifest.json` contains `youtube_video` entries with `video_id` and `download_status`
- downloaded videos exist under `downloads/youtube/`
- extracted frames exist under `frames/` when `ffmpeg` is available
- `sample_manifest.json` includes `video_frame` samples

### C. Failure-path checks

Useful manual checks:

- remove `yt-dlp` from PATH and verify the run continues with web-only notes
- remove `ffmpeg` from PATH and verify video download may succeed while frame extraction is skipped
- set a low `MAX_DOWNLOADED_SOURCES` and verify one class does not consume the full budget

### Expected behavior

One of these will happen:

- training runs if `ultralytics` is installed and enough data exists
- training is skipped or blocked with a note in `training_results.json`

### What to inspect

- `reports/training_results.json`
- `reports/evaluation_report.json`

### Likely current outcome on this repo

If you did not install Ultralytics yet, training will report a blocked/skipped status rather than crashing.

---

## 13. Frontend Testing

The frontend is currently a separate Next.js app.

### Step 1: go to frontend folder

```powershell
cd C:\Users\nihad\Desktop\amd\frontend
```

### Step 2: start the dev server

```powershell
npm run dev
```

### Step 3: open the app

Open:

- `http://localhost:3000`

### What to test

- the app loads
- the current landing/app pages render
- no obvious layout breakage

### Important note

There is **no backend API integration yet**, so frontend testing is currently UI-shell testing only.

---

## 14. Swagger UI / Endpoint Testing

There is **no FastAPI server yet**, so there is currently:

- no `/docs`
- no Swagger UI
- no REST endpoints to hit manually

When the API layer is added later, this section should be expanded to include:

- how to start the FastAPI server
- Swagger URL
- each endpoint
- request body examples
- expected success and failure responses

---

## 15. Suggested Manual Test Sequence

If you want the cleanest current test flow, do this in order:

1. Run backend unit tests.
2. Test `manifest` mode with `LABEL_PROVIDER=mock`.
3. Replace manifest placeholder paths with real local images.
4. Run the manifest-mode CLI pipeline.
5. Inspect `run_summary.json`, `class_plan.json`, and `dataset_manifest.json`.
6. Test live web-image ingestion.
7. Test mixed live web + YouTube ingestion if `yt-dlp` and `ffmpeg` are installed.
8. If you have a Gemini key, test the Gemini provider.
9. If you install Ultralytics, test optional training.
10. Start the frontend and verify the UI shell.

---

## 16. Current Gaps to Be Aware Of

These are not test failures. They are current implementation boundaries:

- no FastAPI server yet
- no Swagger UI yet
- no full frontend-backend integration yet
- live ingestion depends on external providers and local tools like `yt-dlp` and `ffmpeg`
- API-backed web-search fallback only works if the corresponding credentials are configured

So right now the best tests are:

- unit tests
- CLI pipeline runs
- artifact inspection
- provider-path testing
- local file-based sample testing
- mocked live-ingestion testing

---

## 17. Quick Command Reference

### Run backend unit tests

```powershell
cd C:\Users\nihad\Desktop\amd
python -m unittest discover backend/tests
```

### Run backend CLI with mock labels

```powershell
cd C:\Users\nihad\Desktop\amd
$env:PYTHONPATH="backend/src"
$env:SOURCE_MODE="manifest"
$env:LABEL_PROVIDER="mock"
$env:SOURCE_MANIFEST_PATH="backend/examples/source_manifest.json"
python -m autonomous_dataset_agent.cli run --prompt "forklift in a warehouse" --classes "forklift,pallet jack"
```

### Run backend CLI in live mode

```powershell
cd C:\Users\nihad\Desktop\amd
$env:PYTHONPATH="backend/src"
$env:SOURCE_MODE="live"
$env:LABEL_PROVIDER="mock"
python -m autonomous_dataset_agent.cli run --prompt "forklift in a warehouse" --classes "forklift,pallet jack"
```

### Start frontend

```powershell
cd C:\Users\nihad\Desktop\amd\frontend
npm run dev
```

### Check artifacts

```powershell
cd C:\Users\nihad\Desktop\amd
Get-ChildItem -Recurse backend\artifacts
```

---

## 18. Future Update Rule

Whenever one of these is added, update this file immediately:

- FastAPI server
- Swagger UI
- new CLI commands
- new test files
- YouTube downloader
- frontend-backend integration

Right now this file is the authoritative testing guide for the current CLI-first MVP state.
