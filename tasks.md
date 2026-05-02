# TASKS.md

# Autonomous Dataset Agent — Team Tasks (2-Person Build)

## Overview

This document breaks the project into clear tasks for a **2-person team** building the hackathon MVP.

The goal is to ship an end-to-end demo where a user can enter a target like:

> `"forklift in a warehouse"`

and the system will:
- gather source material
- extract and filter frames
- auto-label accepted images
- build a YOLO dataset
- train a detector
- evaluate results
- return both the model and the dataset

Because the team is small, tasks are split by **ownership**, **priority**, and **dependency**.

---

## Team Roles

## Person A — ML / Backend / Pipeline
Owns the core dataset and model pipeline.

### Main responsibilities
- source ingestion
- frame extraction
- frame scoring / filtering
- auto-labeling pipeline
- YOLO dataset creation
- training + evaluation
- backend orchestration

---

## Person B — Frontend / Demo / Integration
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

- accept a text prompt
- process at least one real example class
- extract frames from source media
- filter bad frames
- generate bounding boxes automatically
- package a YOLO-format dataset
- train one YOLO model
- show evaluation metrics
- expose final dataset + weights in a simple demo flow

---

# 2. Priority Labels

## P0 — Must have
Required for the demo to work at all.

## P1 — Should have
Important for a strong demo, but not absolutely required.

## P2 — Nice to have
Good polish or stretch goals.

---

# 3. Task Breakdown

## A. Core Pipeline Tasks

### A1. Define folder structure and project skeleton
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- clean repo structure
- folders for raw media, frames, labels, datasets, models, outputs
- config file or constants file

#### Notes
This should happen first so the rest of the system has a clean place to write artifacts.

---

### A2. Source ingestion pipeline
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- input source handling
- support for at least one reliable source path
- saved raw media files with source metadata

#### Notes
For MVP, this can be simpler than the big vision. It does not need fully autonomous multi-source search on day one if that becomes risky.

---

### A3. Frame extraction with ffmpeg
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- extract frames from input videos
- configurable FPS or interval
- frame metadata log
- output directory per source

#### Notes
This is one of the most important early tasks because many later stages depend on it.

---

### A4. Frame critic / quality filtering
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- blur filtering
- duplicate filtering or approximate deduplication
- accept/reject logic
- JSON log with rejection reasons

#### Notes
This is part of the core novelty of the project, so it needs to be visible in the demo.

---

### A5. Auto-labeling pipeline
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- accepted frame input
- bounding box output in YOLO format
- label file generation
- label confidence metadata if possible

#### Notes
Keep the first version simple and reliable. It is better to support one class well than many classes badly.

---

### A6. Label validation
**Owner:** Person A  
**Priority:** P1  
**Status:** Not started

#### Deliverables
- check label format validity
- check coordinate ranges
- check image-label pairing
- reject broken labels before training

#### Notes
This can save a lot of debugging time later.

---

### A7. Dataset builder
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- YOLO folder structure
- train / val split
- data.yaml generation
- dataset manifest

#### Notes
This is the artifact that proves the system returns a reusable dataset, not just a model.

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
This is essential for the end-to-end story.

---

### A10. Evaluation pipeline
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- mAP@50
- precision
- recall
- basic results summary
- evaluation report JSON

#### Notes
Even simple metrics are enough for MVP as long as they are real and visible.

---

### A11. Iteration logic
**Owner:** Person A  
**Priority:** P1  
**Status:** Not started

#### Deliverables
- threshold-based stop / retry logic
- decision based on mAP or weak quality signals
- simple retry flow

#### Notes
For MVP, this can be one clean second-pass retry rather than a very advanced loop.

---

### A12. Backend job orchestration
**Owner:** Person A  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- pipeline runner
- stage-by-stage execution
- job status tracking
- final artifact bundle

#### Notes
Can be CLI-first and later wrapped in an API.

---

## B. Frontend / Demo Tasks

### B1. Simple UI or demo control panel
**Owner:** Person B  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- text input for prompt/class
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
- optional weak-class notes

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
**Status:** Not started

#### Decision points
- one class or multiple?
- one source type or many?
- full live training or partial precomputation?
- UI-first or CLI-first?

#### Notes
This must be locked early to avoid scope creep.

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
**Status:** Not started

#### Deliverables
- file names
- folder paths
- JSON schema for shared outputs
- run status schema

#### Notes
This avoids integration pain between backend and frontend.

---

### C4. Integration testing
**Owner:** Both  
**Priority:** P0  
**Status:** Not started

#### Deliverables
- full pipeline test
- broken-stage handling
- UI + backend end-to-end validation
- proof that final artifacts render correctly

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
- A1 repo skeleton
- A2 source ingestion
- A3 frame extraction
- A4 frame critic
- A5 auto-labeling
- A7 dataset builder
- A9 YOLO training
- A10 evaluation
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

## Phase 1 — Critical foundation
**Goal:** make the pipeline real before making it pretty

### Person A
- A1 repo skeleton
- A3 frame extraction
- A5 auto-labeling
- A7 dataset builder
- A9 YOLO training

### Person B
- C3 artifact contracts with Person A
- B1 simple UI shell
- B2 progress tracker shell
- B4 dataset preview shell

---

## Phase 2 — Core novelty
**Goal:** implement what makes the project stand out

### Person A
- A2 source ingestion
- A4 frame critic
- A10 evaluation

### Person B
- B3 accepted/rejected frame viewer
- B5 metrics dashboard
- B6 final artifact section

---

## Phase 3 — Reliability and demo
**Goal:** make the project presentable and safe to show

### Person A
- A6 label validation
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

1. source/media input  
2. frame extraction  
3. frame filtering  
4. auto-labeling  
5. dataset build  
6. YOLO training  
7. evaluation output  
8. basic UI or display layer

If any of these fail, the demo weakens significantly.

---

# 7. Stretch Goals

Only do these if the MVP is already stable.

## Stretch Goal 1
Multi-source search instead of one source path

## Stretch Goal 2
Smarter diversity scoring

## Stretch Goal 3
Iteration loop with automatic recollection

## Stretch Goal 4
Live webcam inference on final trained model

## Stretch Goal 5
Downloadable artifact bundle from UI

---

# 8. Demo Checklist

Before submission, verify:

- prompt input works
- frame extraction works
- accepted/rejected filtering is visible
- labels are being generated correctly
- dataset folder is valid
- YOLO training completes
- metrics display correctly
- final weights are saved
- dataset is shown as an output
- backup demo exists

---

# 9. Risk Management

## Risk: full live training is too slow
**Mitigation:** use smaller dataset or precomputed fallback run

## Risk: auto-labeling is noisy
**Mitigation:** restrict to one object class and filter more aggressively

## Risk: frontend and backend mismatch
**Mitigation:** define artifact contracts early

## Risk: source collection becomes messy
**Mitigation:** support one reliable source path first

## Risk: iteration loop becomes too ambitious
**Mitigation:** keep first version threshold-based and simple

---

# 10. Suggested Daily Focus

## Day 1
- lock MVP
- define contracts
- make frame extraction + labeling + dataset structure real

## Day 2
- get YOLO training and metrics working
- build UI around actual outputs
- implement frame critic

## Day 3
- integrate everything
- polish demo
- record backup run
- practice pitch

---

# 11. Definition of Done

The project is done when:

- a user enters a target prompt
- the system produces filtered frames
- labels are generated
- a YOLO dataset is built
- a model is trained
- evaluation metrics are shown
- both dataset and model are returned
- the team can demo the workflow clearly and reliably

---

# 12. Summary

For a 2-person team, the right strategy is to split the project into:
- **Person A:** make the pipeline real
- **Person B:** make the pipeline visible, understandable, and demoable

The win condition is not building every advanced feature. It is delivering one clear end-to-end story: the system autonomously creates a dataset, trains a detector, evaluates it, and returns both the model and the dataset.