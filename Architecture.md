# ARCHITECTURE.md

# Autonomous Dataset Agent — System Architecture

## Overview

Autonomous Dataset Agent is an end-to-end agentic pipeline that turns a text prompt into two outputs:

1. a trained YOLO object detection model  
2. a reusable labeled dataset used to train that model

The system automates the full computer vision workflow: source discovery, frame extraction, quality filtering, auto-labeling, dataset construction, training, evaluation, and iteration.

Instead of relying on a user to manually collect and label data, the system coordinates specialized agents that continuously improve the dataset until model performance reaches a target threshold or the run budget is exhausted.

---

## High-Level Architecture

```text
                        ┌──────────────────────┐
                        │   User / Frontend    │
                        │ prompt: "forklift"   │
                        └──────────┬───────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │   API / Orchestrator │
                        │ FastAPI job manager  │
                        └──────────┬───────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
         ▼                         ▼                         ▼
┌─────────────────┐     ┌──────────────────┐      ┌──────────────────┐
│ Source Search   │     │ Job / Metadata   │      │ Artifact Store   │
│ Agent           │     │ Store            │      │ datasets/models  │
└────────┬────────┘     └──────────────────┘      └──────────────────┘
         │
         ▼
┌─────────────────┐
│ Video / Media   │
│ Collection      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Frame Extraction│
│ ffmpeg          │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Critic Agent    │
│ quality scoring │
└────────┬────────┘
         │ accepted frames
         ▼
┌─────────────────┐
│ Label Agent     │
│ bbox generation │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Dataset Builder │
│ split/augment   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Train Agent     │
│ YOLO training   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Eval Agent      │
│ metrics/review  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Iteration Agent │
│ retry / stop    │
└─────────────────┘
Core System Components
1. User Interface Layer

The user interacts with the system through a lightweight frontend or API request.

Input
object or scenario prompt
optional source constraints
optional target classes
optional training budget
optional quality threshold
optional output format preferences
Example
{
  "prompt": "forklift in a warehouse",
  "classes": ["forklift"],
  "target_map50": 0.75
}
Responsibilities
collect job input
submit run request
display progress
preview accepted/rejected frames
show final metrics
expose model and dataset artifacts for download
2. API / Orchestration Layer

The orchestration layer coordinates every stage of the pipeline.

Suggested stack
FastAPI
background workers
task queue or async jobs
persistent metadata store
Responsibilities
create and track jobs
invoke agents in sequence
manage retries and failure states
persist run metadata
store artifact paths
expose job status and logs
Example endpoints
POST /jobs
GET /jobs/{job_id}
GET /jobs/{job_id}/artifacts
POST /jobs/{job_id}/train
POST /jobs/{job_id}/iterate
3. Source Search Agent

The Source Search Agent gathers candidate visual sources relevant to the prompt.

Responsibilities
translate prompt into searchable visual queries
gather videos or image-rich sources
maximize diversity across angle, lighting, context, and background
score sources for usefulness before downloading
Inputs
prompt
class list
optional domain hints
Outputs
ranked source list
source metadata
candidate download URLs or references
Goals
source diversity
source relevance
source quality
low duplication
4. Media Collection Layer

This layer downloads or ingests the selected source material.

Responsibilities
download video files
normalize formats
maintain source metadata
store raw media for reproducibility
Outputs
local or cloud-stored media files
source manifest
checksum / provenance metadata
5. Frame Extraction Layer

This layer converts videos into candidate frames for downstream processing.

Suggested tool
ffmpeg
Responsibilities
sample frames at configurable FPS
support scene-based extraction or interval-based extraction
preserve source-to-frame mapping
emit frame metadata
Example metadata
{
  "frame_id": "src12_t0842",
  "source_id": "src12",
  "timestamp_sec": 84.2,
  "path": "frames/src12/frame_0842.jpg"
}
Why this layer matters

This is the bridge between raw media and dataset construction. It generates the candidate pool the system will curate.

6. Critic Agent

The Critic Agent filters and ranks frames before labeling.

Responsibilities
reject blurry frames
reject heavily occluded frames
reject near-duplicates
reject frames with low object visibility
prioritize diverse, labelable examples
Example quality criteria
blur score
occlusion score
duplicate similarity score
label confidence estimate
composition usefulness
class visibility
viewpoint diversity
Outputs
accepted frames
rejected frames
rejection reasons
quality scores per frame
Why it matters

This is one of the main differentiators of the project. The system is not blindly labeling every extracted frame; it is curating a better dataset first.

7. Label Agent

The Label Agent produces object annotations for accepted frames.

Responsibilities
detect target objects in frame
generate structured bounding boxes
normalize coordinates for YOLO format
optionally estimate label confidence
Output format

YOLO label files:

<class_id> <x_center> <y_center> <width> <height>
Example
0 0.523 0.481 0.211 0.327
Additional metadata
label confidence
source frame reference
prompt used for labeling
version of labeling model used
8. Dataset Builder

The Dataset Builder transforms accepted images and labels into a trainable dataset.

Responsibilities
organize dataset into YOLO-compatible structure
generate class index mappings
split train / validation / test
apply augmentations
track label transformations
export dataset manifest
Example output structure
dataset/
├── images/
│   ├── train/
│   ├── val/
│   └── test/
├── labels/
│   ├── train/
│   ├── val/
│   └── test/
└── data.yaml
Augmentations
horizontal flip
brightness shift
contrast adjustment
noise injection
optional crop / scale transforms
Key requirement

Augmentations must preserve label correctness.

9. Train Agent

The Train Agent runs YOLO training on the generated dataset.

Suggested stack
Ultralytics YOLO
Responsibilities
load dataset config
configure training parameters
train model
save weights and logs
track best checkpoint
Outputs
trained weights
training logs
loss curves
checkpoint metadata
Example artifacts
best.pt
last.pt
results.csv
confusion_matrix.png
10. Evaluation Agent

The Evaluation Agent determines how well the trained model performs and whether iteration is required.

Responsibilities
compute model quality metrics
identify weak classes
identify hard frames
compare results against target threshold
Example metrics
mAP@50
mAP@50-95
precision
recall
per-class AP
false positive rate
false negative rate
Outputs
evaluation report
failure analysis
weak-class summary
recommendation for next step
Example recommendation logic
if mAP is below target, recollect more data
if label confidence is weak, relabel accepted frames
if one class underperforms, prioritize source search for that class
11. Iteration Agent

The Iteration Agent controls the feedback loop.

Responsibilities
decide whether to stop or retry
choose next improvement action
send pipeline back to the correct stage
Possible actions
recollect more sources
extract more frames from strong sources
relabel low-confidence samples
rebalance dataset
retrain with revised data
Stop conditions
target performance reached
max iterations reached
time budget reached
data budget reached
12. Artifact Storage Layer

This layer stores all reusable outputs from the run.

Stores
raw media
extracted frames
accepted/rejected frame logs
labels
dataset manifests
trained weights
evaluation reports
Final artifacts returned
labeled dataset
YOLO config
model weights
evaluation report
run metadata

This is important because the system returns both the model and the dataset, not just a black-box result.

13. Metadata / Experiment Tracking

A lightweight metadata layer helps make the system reproducible.

Tracks
job ID
prompt
sources used
frames accepted/rejected
label version
augmentation config
training hyperparameters
metrics by iteration
final artifacts
Why it matters

Without this layer, the system becomes hard to debug and hard to explain during demos.

Agent Design

The system is organized around specialized agents rather than a single monolithic controller.

Agent list
Source Search Agent

Finds candidate media sources for the target object.

Critic Agent

Filters frames and improves dataset quality.

Label Agent

Generates annotations for accepted frames.

Train Agent

Runs model training.

Eval Agent

Measures performance and identifies failures.

Iteration Agent

Controls the improvement loop and decides next actions.

Data Flow
Prompt
  -> source search
  -> media download
  -> frame extraction
  -> frame critique
  -> auto-labeling
  -> dataset build
  -> model training
  -> evaluation
  -> iteration decision
  -> final model + dataset export
Example Run
User prompt

"forklift in a warehouse"

Step-by-step flow
User submits prompt
Orchestrator creates job
Source Search Agent finds relevant visual sources
Media is downloaded
Frames are extracted with ffmpeg
Critic Agent scores and filters frames
Label Agent creates bounding boxes
Dataset Builder creates YOLO dataset and augmentations
Train Agent trains detector
Evaluation Agent computes metrics
Iteration Agent either retries or stops
Final dataset and model are exported
Failure Handling

The system should fail gracefully at every stage.

Common failures
no good source material found
extracted frames are too low quality
label generation is inconsistent
dataset too small for reliable training
training fails or underperforms
Handling strategy
keep detailed stage-level logs
store partial artifacts
support restart from intermediate checkpoints
surface failure reason in job status
Scalability Considerations

Although the hackathon version can be run on a single machine, the design can scale.

Natural scale points
parallel source ingestion
parallel frame critique
parallel labeling
distributed training jobs
batched evaluation
Good future architecture upgrades
queue-based workers
cloud object storage
GPU worker pool
experiment tracking dashboard
multi-user job isolation
Security and Trust

Even in a hackathon version, the system should aim for basic trustworthiness.

Recommendations
preserve source provenance
log rejection reasons
keep label confidence metadata
make dataset export auditable
expose evaluation metrics clearly

This helps position the project as a dataset engine rather than a black-box model trainer.

Design Principles

The architecture follows a few core principles:

1. Dataset quality is more important than raw volume

More frames do not always mean a better detector.

2. Every stage should produce inspectable artifacts

The system should be debuggable and demo-friendly.

3. Iteration should be metric-driven

The system should only retry when measurable weaknesses exist.

4. The output should be reusable

The user should receive the dataset as well as the model.

5. Agents should be modular

Each stage should be independently testable and replaceable.

Summary

Autonomous Dataset Agent is designed as a modular, agent-driven system for creating custom object detection datasets and YOLO models from minimal user input. Its core architectural advantage is not just automation, but autonomous dataset curation: the system actively gathers, filters, labels, trains, evaluates, and iterates until it produces a better detector and a reusable dataset.

The most important distinction is that the architecture treats dataset generation as the primary problem, with model training serving as one stage inside a broader self-improving pipeline.