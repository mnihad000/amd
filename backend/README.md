# Backend MVP

This backend is a CLI-first scaffold for the Autonomous Dataset Agent project.

Current goals:

- accept a prompt and class list
- plan class feasibility dynamically
- ingest structured web-image and YouTube source manifests
- extract frames from local videos with `ffmpeg`
- normalize and filter samples
- label accepted samples through a provider interface
- export YOLO dataset artifacts and run manifests

The current scaffold is designed to be testable offline:

- source ingestion can run from a local JSON manifest
- the `mock` label provider supports dry runs and tests
- Gemini is wired as the first real provider path through `LABEL_PROVIDER=gemini`

## Quick start

```bash
cd backend
pip install -r requirements.txt
python -m autonomous_dataset_agent.cli run ^
  --prompt "forklift in a warehouse" ^
  --classes "forklift,pallet jack"
```

If you want YOLO training enabled, install:

```bash
pip install -r requirements-train.txt
```

## Source manifest shape

The manifest referenced by `SOURCE_MANIFEST_PATH` should be JSON with either a top-level `sources` array or a raw array:

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

Supported `source_type` values in v1:

- `web_image`
- `youtube_video`

`youtube_video` entries should point to a local downloaded video file in `local_path`. The scaffold keeps discovery/download separate from frame extraction so it can be tested without network access.
