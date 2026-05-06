# TASKS.md

# Autonomous Dataset Agent - Team Tasks (2-Person Build)

## Overview

This document tracks the current MVP build for a **2-person team**. It separates:

- decisions that are already locked
- implementation tasks that are still open
- explicit v1 simplifications and later improvements

The backend MVP is now based on:

- CLI-first orchestration
- prompt-driven class input
- **dynamic class admission** instead of hard class caps
- **structured web-image ingestion + YouTube ingestion**
- a **70/30 accepted-set target mix** between web images and video-derived frames
- a **generic label-provider interface** with **Gemini first**

---

## Team Roles

## Person A - ML / Backend / Pipeline
Owns the core dataset and model pipeline.

### Main responsibilities
- source ingestion
- frame extraction
- frame scoring / filtering
- class planning and admission
- auto-labeling pipeline
- YOLO dataset creation
- training + evaluation
- backend orchestration

---

## Person B - Frontend / Demo / Integration
Owns the presentation layer and demo flow.

### Main responsibilities
- frontend or lightweight UI
- job submission flow
- progress display
- artifact preview
- result visualization
- demo polish
- integration testing
- backup demo flow

---

# 1. MVP Definition

The MVP is complete when the system can:

- accept a text prompt and class list
- attempt any number of requested classes without rejecting input up front
- decide which classes are feasible for the current run
- ingest both structured web images and YouTube video sources
- extract video frames with `ffmpeg`
- filter bad or duplicate samples
- generate bounding boxes automatically
- package a YOLO-format dataset for the feasible subset
- optionally train one YOLO model
- show evaluation and class-level outcome summaries
- expose final dataset + weights + manifests in a simple demo flow

---

# 2. Priority Labels

## P0 - Must have
Required for the demo to work at all.

## P1 - Should have
Important for a strong demo, but not absolutely required.

## P2 - Nice to have
Good polish or stretch goals.

---

# 3. Task Breakdown

## A. Core Pipeline Tasks

### A0. Backend environment bootstrap
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- Python runtime pinned to `3.11` or `3.12`
- dependency management for backend packages
- `ffmpeg` installation / path validation
- `.env.example`

#### Notes
This makes the backend reproducible before agent logic starts.

---

### A1. Define folder structure and project skeleton
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- clean repo structure
- folders for jobs, raw sources, downloads, frames, labels, datasets, models, outputs, reports
- shared config and data contracts

#### Notes
This should happen first so the rest of the system has a clean place to write artifacts.

---

### A2. Source ingestion pipeline
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- structured web-image source adapter
- YouTube source discovery / download path
- source provenance metadata
- source-type tagging
- saved raw source records and manifests

#### Notes
V1 should support the two-source ingestion path cleanly rather than many unreliable adapters.

#### V1 now, improve later
- broader source adapters
- licensing filters
- public dataset adapters

---

### A2b. Class Planner / dynamic class admission
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- per-class feasibility scoring
- `ready` / `risky` / `blocked` states
- admitted-class plan artifact
- partial-success handling for feasible subsets

#### Notes
This replaces hard class caps as the main safety mechanism.

---

### A3. Frame extraction with ffmpeg
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- extract frames from input videos
- configurable FPS or interval
- frame metadata log
- timestamp-to-source mapping
- output directory per source

#### Notes
Requires local `ffmpeg` bootstrap/setup to be validated first.

#### V1 now, improve later
- scene-change extraction
- adaptive FPS
- source-specific extraction policies

---

### A4. Frame critic / quality filtering
**Owner:** Person A  
**Priority:** P0  
**Status:** Done (v1 lightweight hardening complete)

#### Deliverables
- blur filtering
- cross-source deduplication
- source-aware quality scoring
- object visibility / size heuristics
- accept/reject logic
- JSON log with rejection reasons

#### Notes
This is part of the core novelty of the project, so it needs to be visible in the demo.

#### V1 now, improve later
- embedding-based diversity scoring
- stronger occlusion estimation
- learned critic model
- API-time stage metrics / critic telemetry export

---

### A4b. Cross-source sample normalization
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- unify web images and video frames into one sample contract
- preserve provenance and source type
- preserve class hints and extraction metadata

#### Notes
This keeps downstream labeling and dataset build logic source-agnostic.

---

### A5. Auto-labeling pipeline
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- accepted sample input
- generic label-provider interface
- Gemini-first implementation
- bounding box output in YOLO format
- label confidence metadata
- per-class labeling for admitted classes only

#### Notes
V1 should optimize for one provider abstraction done cleanly, not many half-integrated providers.

#### V1 now, improve later
- multi-provider backends
- second-pass relabeling
- human-review queue

---

### A5b. Label validation and confidence gating
**Owner:** Person A  
**Priority:** P1  
**Status:** Not started

#### Deliverables
- check label format validity
- check coordinate ranges
- check image-label pairing
- reject broken labels before training
- exclude low-confidence labels when needed

#### Notes
This extends the old label-validation task into a stronger gate before training.

---

### A6. Label validation
**Owner:** Person A  
**Priority:** P1  
**Status:** Superseded by A5b

#### Notes
Folded into `A5b. Label validation and confidence gating`.

---

### A7. Dataset builder
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- YOLO folder structure
- train / val / test split
- `data.yaml` generation
- dataset manifest
- partial-success dataset creation
- admitted / deferred class handling
- source-mix reporting in manifests

#### Notes
This is the artifact that proves the system returns a reusable dataset, not just a model.

#### V1 now, improve later
- smarter class balancing
- curriculum datasets
- augmentation presets by domain

---

### A7b. Run-budget and resource guardrails
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- max runtime per run
- max downloads
- max labeling calls
- max accepted samples
- graceful stop behavior

#### Notes
The user input can stay unbounded even though execution stays resource-aware.

---

### A8. Basic data augmentation
**Owner:** Person A  
**Priority:** P1  
**Status:** Not started

#### Deliverables
- horizontal flip
- brightness / contrast adjustments
- synced label transforms
- augmentation log

#### Notes
Only add this after the base dataset path is working.

---

### A9. YOLO training integration
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- train YOLO on generated dataset
- save best weights
- save results/logs
- basic configurable hyperparameters

#### Notes
Training is part of the story, but dataset quality still comes first.

---

### A10. Evaluation pipeline
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- mAP@50
- precision
- recall
- feasible-subset evaluation
- class-level weakness reporting
- class-level include / defer feedback
- evaluation report JSON

#### Notes
Even simple metrics are enough for MVP as long as they are real and visible.

#### V1 now, improve later
- confusion analysis
- object-size breakdowns
- source-performance attribution

---

### A11. Iteration logic
**Owner:** Person A  
**Priority:** P1  
**Status:** Not started

#### Deliverables
- threshold-based stop / retry logic
- per-class recollect / relabel decisions
- no full rerun when only one class is weak
- simple retry flow

#### Notes
For MVP, this can still be lightweight, but it must be class-aware.

#### V1 now, improve later
- targeted recollection strategies
- automatic class re-weighting
- label repair loops

---

### A12. Backend job orchestration
**Owner:** Person A  
**Priority:** P0  
**Status:** In progress

#### Deliverables
- CLI-first pipeline runner
- stage-by-stage execution
- Class Planner stage
- run budgets
- job status tracking
- graceful partial completion
- final artifact bundle

#### Notes
Build the core runner once, then wrap it in an API later if needed.

#### V1 now, improve later
- FastAPI wrapper (thin synchronous phase completed)
- async jobs
- resumable checkpoints
- multi-run comparison UI

---

### A12b. Post-v1 Phase 1 - Thin API layer checklist
**Owner:** Person A  
**Priority:** P1  
**Status:** In progress

#### Completed
- `POST /runs` endpoint implemented
- `GET /runs/{job_id}` endpoint implemented
- `GET /runs/{job_id}/artifacts` endpoint implemented
- synchronous execution path wired to existing `PipelineRunner`
- artifact contracts reused from existing run summary
- API dependencies and server entrypoint added (`fastapi`, `uvicorn`, `ada-api`)

#### Next checklist items
- add API integration test coverage for run success/failure and artifact fetch
- add explicit request timeout behavior and error mapping docs
- add lightweight run-status persistence policy for restarts
- decide async execution handoff boundary for next iteration

---

## B. Frontend / Demo Tasks

### B1. Simple UI or demo control panel
**Owner:** Person B  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- text input for prompt/class list
- submit button
- run status view
- final results page

#### Notes
The UI can be very lightweight. Clean and understandable is more important than fancy.

---

### B2. Progress / stage tracker
**Owner:** Person B  
**Priority:** P1  
**Status:** Not started

#### Deliverables
- visible pipeline steps
- current stage indicator
- completed stage list
- simple loading states

#### Example stages
- class planning
- source collection
- frame extraction
- filtering
- labeling
- training
- evaluation
- export

---

### B3. Accepted vs rejected frame viewer
**Owner:** Person B  
**Priority:** P1  
**Status:** Not started

#### Deliverables
- sample accepted frames
- sample rejected frames
- rejection reasons shown

#### Notes
This is one of the strongest features for judges because it shows the curation loop visually.

---

### B4. Dataset artifact preview
**Owner:** Person B  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- show example images
- show example bounding boxes
- show dataset stats
- show class counts or frame counts

#### Notes
This reinforces that the dataset is a real output of the system.

---

### B5. Metrics dashboard
**Owner:** Person B  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- display mAP@50
- precision
- recall
- weak-class notes
- admitted / deferred class outcomes

#### Notes
Keep this clean and legible.

---

### B6. Final artifact section
**Owner:** Person B  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- show path or link to dataset
- show path or link to model weights
- show run summary
- show proof of completed output bundle

---

### B7. Demo mode / canned example support
**Owner:** Person B  
**Priority:** P1  
**Status:** Not started

#### Deliverables
- one-click sample prompt
- fallback precomputed example
- stable presentation flow

#### Notes
This is critical for hackathon reliability.

---

### B8. Landing page / project explanation
**Owner:** Person B  
**Priority:** P2  
**Status:** Not started

#### Deliverables
- short explanation of what the project does
- key pipeline steps
- why it is different

#### Notes
Nice for polish, not core.

---

## C. Shared / Integration Tasks

### C1. Decide exact MVP scope
**Owner:** Both  
**Priority:** P0  
**Status:** Done

#### Locked decisions
- CLI-first backend
- prompt-driven class input
- dynamic class admission
- structured web-image ingestion + YouTube ingestion
- accepted-set 70/30 source-mix target
- Gemini-first label provider behind a generic interface

#### Notes
This scope is locked unless the team explicitly reopens it.

---

### C2. Define prompt-to-output demo path
**Owner:** Both  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- exact demo input
- exact expected outputs
- timing expectations
- backup plan if live run is slow

---

### C3. Agree on artifact contracts
**Owner:** Both  
**Priority:** P0  
**Status:** Done

#### Deliverables
- `class_plan.json`
- `source_manifest.json`
- `sample_manifest.json`
- `frame_scores.json`
- `accepted_frames.json`
- `labels_manifest.json`
- `dataset_manifest.json`
- `training_results.json`
- `evaluation_report.json`
- `run_summary.json`

#### Notes
The frontend and backend should integrate against these artifacts.

---

### C4. Integration testing
**Owner:** Both  
**Priority:** P0  
**Status:** In progress

#### Deliverables
- full pipeline test
- broken-stage handling
- UI + backend end-to-end validation
- proof that final artifacts render correctly
- API endpoint smoke coverage (`POST /runs`, `GET /runs/{job_id}`, `GET /runs/{job_id}/artifacts`)

---

### C5. Demo script
**Owner:** Both  
**Priority:** P1  
**Status:** Not started

#### Deliverables
- 30-second version
- 1-minute version
- 2-minute walkthrough
- clear explanation of novelty

---

### C6. Backup demo package
**Owner:** Both  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- precomputed successful run
- saved example dataset
- saved model weights
- screenshots / clips if needed

#### Notes
This is non-negotiable for a hackathon.

---

# 4. Recommended Ownership Summary

## Person A primary
- A0 backend bootstrap
- A1 repo skeleton
- A2 source ingestion
- A2b class planning
- A3 frame extraction
- A4 frame critic
- A4b sample normalization
- A5 auto-labeling
- A5b label validation
- A7 dataset builder
- A7b budget guardrails
- A9 YOLO training
- A10 evaluation
- A11 iteration logic
- A12 orchestration

## Person B primary
- B1 UI
- B2 progress tracker
- B3 accepted/rejected viewer
- B4 dataset preview
- B5 metrics dashboard
- B6 final artifacts section
- B7 demo mode
- B8 landing page

## Shared
- C1 scope decisions
- C2 demo path
- C3 artifact contracts
- C4 integration testing
- C5 demo script
- C6 backup demo

---

# 5. Build Order

## Phase 1 - Critical foundation
**Goal:** make the backend real before demo polish

### Person A
- A0 backend bootstrap
- A1 repo skeleton
- A2b class planner
- A3 frame extraction
- A5 auto-labeling
- A7 dataset builder

### Person B
- C3 artifact contracts with Person A
- B1 simple UI shell
- B2 progress tracker shell
- B4 dataset preview shell

---

## Phase 2 - Core novelty
**Goal:** implement what makes the project stand out

### Person A
- A2 source ingestion
- A4 frame critic
- A4b sample normalization
- A10 evaluation

### Person B
- B3 accepted/rejected frame viewer
- B5 metrics dashboard
- B6 final artifact section

---

## Phase 3 - Reliability and demo
**Goal:** make the project presentable and safe to show

### Person A
- A5b label validation
- A7b budget guardrails
- A9 training integration
- A11 iteration logic
- A12 better orchestration

### Person B
- B7 demo mode
- B8 landing page or project summary polish

### Both
- C4 integration testing
- C5 demo script
- C6 backup demo package

---

# 6. Critical Path

These tasks must work for the project to be demoable:

1. class planning  
2. source/media input  
3. frame extraction  
4. frame filtering  
5. auto-labeling  
6. dataset build  
7. evaluation output  
8. basic UI or display layer

If any of these fail, the demo weakens significantly.

---

# 7. Stretch Goals

Only do these if the MVP is already stable.

## Stretch Goal 1
Live multi-provider label backends

## Stretch Goal 2
Smarter diversity scoring and learned critic logic

## Stretch Goal 3
Automatic recollection loops with source-aware planning

## Stretch Goal 4
Live webcam inference on final trained model

## Stretch Goal 5
Downloadable artifact bundle from UI

---

# 8. Demo Checklist

Before submission, verify:

- prompt input works
- class planning is visible
- frame extraction works
- accepted/rejected filtering is visible
- labels are being generated correctly
- dataset folder is valid
- evaluation outputs render correctly
- final manifests are saved
- dataset is shown as an output
- backup demo exists

---

# 9. Risk Management

## Risk: full live training is too slow
**Mitigation:** use smaller datasets, optional training, or a precomputed fallback run

## Risk: auto-labeling is noisy
**Mitigation:** use confidence gating, better filtering, and partial-success class admission

## Risk: frontend and backend mismatch
**Mitigation:** define artifact contracts early and keep them stable

## Risk: source collection becomes messy
**Mitigation:** support the approved two-source path well before adding more adapters

## Risk: iteration loop becomes too ambitious
**Mitigation:** keep first version threshold-based and class-aware

---

# 10. Suggested Daily Focus

## Day 1
- lock MVP
- define contracts
- make class planning + frame extraction + labeling + dataset structure real

## Day 2
- get ingestion, critic, and evaluation working
- build UI around actual outputs

## Day 3
- integrate everything
- polish demo
- record backup run
- practice pitch

---

# 11. Definition of Done

The project is done when:

- a user enters a target prompt and class list
- the system evaluates class feasibility
- the system produces filtered frames/samples
- labels are generated
- a YOLO dataset is built for the feasible subset
- evaluation metrics or evaluation status are shown
- both dataset and model artifacts are returned when available
- the team can demo the workflow clearly and reliably

---

# 12. Summary

For a 2-person team, the right strategy is still:
- **Person A:** make the pipeline real
- **Person B:** make the pipeline visible, understandable, and demoable

The difference is that the backend scope is now clearer:
- do not hard-cap classes
- do not pretend every class is equally feasible
- admit what is trainable
- preserve provenance
- return transparent artifacts and run decisions

The win condition is one clear end-to-end story: the system accepts an open-ended detection request, plans which classes are feasible, builds a better dataset, and returns both the dataset and the model artifacts it can support.
