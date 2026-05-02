# DATASET_PIPELINE_AND_EVALUATION.md

# Autonomous Dataset Agent — Dataset Pipeline & Evaluation

## Overview

This document defines how Autonomous Dataset Agent turns a text prompt into a trainable YOLO dataset, how it judges data quality, and how it evaluates whether the final detector is good enough or needs another iteration.

The system does not treat dataset generation as a one-time preprocessing step. Instead, it treats it as an iterative loop:

1. collect candidate source material  
2. extract frames  
3. score frame quality  
4. reject poor examples  
5. auto-label accepted frames  
6. build and augment dataset  
7. train YOLO  
8. evaluate model quality  
9. improve weak spots if needed

The goal is to return both:
- a reusable labeled dataset
- a trained YOLO detector

---

# Part 1 — Dataset Pipeline

## 1. Pipeline Goal

The dataset pipeline is responsible for producing a clean, diverse, trainable object detection dataset from raw visual sources.

### Input
- text prompt
- target classes
- optional quality thresholds
- optional iteration budget

### Example input
```json
{
  "prompt": "forklift in a warehouse",
  "classes": ["forklift"],
  "target_map50": 0.75,
  "max_iterations": 3
}
Output
accepted images
YOLO label files
train / val / test split
dataset metadata
augmented samples
exportable data.yaml
2. Pipeline Stages
Stage 1 — Source Discovery

The system gathers candidate media sources relevant to the requested object or scenario.

Purpose

Find enough relevant and diverse visual material to support training.

What the system wants
different lighting
different camera angles
different scales
different backgrounds
different levels of clutter
different levels of partial occlusion
Good sources
visually relevant
high enough resolution
likely to contain multiple usable views
not overly repetitive
Output
source_manifest.json
Example source record
{
  "source_id": "src_001",
  "title": "Forklift operations in a warehouse",
  "url": "placeholder",
  "relevance_score": 0.91,
  "status": "selected"
}
Stage 2 — Media Ingestion

Selected media is downloaded or ingested into the local pipeline.

Purpose

Normalize source assets and preserve provenance.

Responsibilities
download source media
normalize file format
store source metadata
maintain reproducibility
Output
raw media files
normalized media manifest
Stage 3 — Frame Extraction

The system extracts candidate frames from videos using ffmpeg.

Purpose

Convert raw media into candidate still images for filtering and labeling.

Parameters
frames per second
extraction interval
optional scene-change sensitivity
maximum frames per source
Example extraction metadata
{
  "frame_id": "src_001_f_00842",
  "source_id": "src_001",
  "timestamp_sec": 84.2,
  "path": "frames/src_001/frame_00842.jpg"
}
Tooling
ffmpeg
Output
extracted frame set
frame metadata log
Stage 4 — Frame Quality Scoring

Each extracted frame is scored before labeling.

Purpose

Avoid wasting labeling and training effort on weak examples.

Frame quality signals
blur
object visibility
occlusion
duplicate similarity
lighting quality
composition usefulness
estimated labelability
diversity contribution
Typical rejection reasons
blurry image
target object too small
object heavily occluded
duplicate of another frame
no target object visible
too dark or overexposed
target not reliably labelable
Example frame score record
{
  "frame_id": "src_001_f_00842",
  "quality_score": 0.82,
  "blur_score": 0.91,
  "occlusion_score": 0.24,
  "duplicate_score": 0.12,
  "decision": "accept"
}
Output
frame_scores.json
accepted frames
rejected frames
rejection reasons
Stage 5 — Frame Selection

Frames that pass the critic stage move forward.

Purpose

Create a smaller, higher-quality dataset candidate pool.

Selection goals
high visual quality
high target visibility
strong diversity
minimal redundancy
Desired result

A dataset that is not just large, but useful.

Output
accepted_frames.json
rejected_frames.json
Stage 6 — Auto-Labeling

Accepted frames are labeled automatically with bounding boxes.

Purpose

Generate YOLO-compatible object detection labels.

Label output format
<class_id> <x_center> <y_center> <width> <height>
Example
0 0.523 0.481 0.211 0.327
Labeling requirements
correct class mapping
normalized coordinates
valid box dimensions
one label file per image
consistent class IDs across the dataset
Optional metadata
label confidence
labeling model version
prompt used for box generation
Output
label text files
labels_manifest.json
Stage 7 — Label Validation

Before final packaging, labels are sanity-checked.

Purpose

Catch broken or obviously bad labels before training.

Validation rules
class ID must exist
coordinates must be normalized between 0 and 1
width and height must be positive
box must stay inside image bounds
image and label file pairs must match
Examples of invalid labels
missing label file
negative width
coordinates outside valid range
class ID not in class list
Output
validated label set
invalid label report
Stage 8 — Dataset Construction

Accepted images and valid labels are organized into YOLO format.

Purpose

Build a trainable object detection dataset.

Expected structure
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
Responsibilities
align images and labels
generate split folders
write data.yaml
preserve class order
keep source metadata
data.yaml example
path: dataset
train: images/train
val: images/val
test: images/test

names:
  0: forklift
Output
YOLO dataset folder
data.yaml
dataset manifest
Stage 9 — Data Augmentation

The system expands dataset coverage using safe augmentations.

Purpose

Improve robustness without breaking label integrity.

Base augmentations
horizontal flip
brightness adjustment
contrast adjustment
mild noise injection
Rules
label transformations must remain correct
augmentations should not destroy object visibility
aggressive transforms should be avoided in MVP
Example augmentation record
{
  "image_id": "frame_00842.jpg",
  "augmentation": "horizontal_flip",
  "derived_image_id": "frame_00842_flip.jpg"
}
Output
augmented images
transformed labels
augmentation log
Stage 10 — Split Strategy

The dataset is divided into train, validation, and optional test sets.

Purpose

Support training and honest evaluation.

Typical split
train: 70%
val: 20%
test: 10%
Goals
prevent leakage
preserve class coverage
preserve diversity across splits
Output
split manifest
train / val / test folders
Stage 11 — Dataset Export

Final dataset artifacts are packaged for reuse.

Purpose

Return a reusable, inspectable data asset to the user.

Export includes
images
labels
data.yaml
manifests
accepted/rejected frame logs
augmentation metadata
Why this matters

The system is not a black box. It returns the actual training data, not just a final model.

Part 2 — Data Quality Evaluation
3. Dataset Quality Goals

A good dataset should be:

relevant
diverse
labelable
low-noise
minimally redundant
structurally valid

The system should prefer a smaller clean dataset over a larger noisy one.

4. Data Quality Metrics

The critic stage should track dataset quality metrics before training.

4.1 Frame-Level Metrics
Blur score

Measures sharpness and image clarity.

Occlusion score

Estimates how much of the target object is hidden.

Visibility score

Measures how clearly the target appears in frame.

Duplicate score

Measures visual similarity to previously accepted frames.

Relevance score

Measures how likely the frame contains the requested object or scene.

Labelability score

Measures whether the object can be reliably boxed.

4.2 Dataset-Level Metrics
Acceptance rate

Percentage of extracted frames that survive filtering.

Diversity score

How visually varied the accepted dataset is.

Duplicate ratio

How many accepted frames are near-repeats.

Label validity rate

Percentage of generated labels that pass sanity checks.

Augmentation expansion factor

How much the dataset grows after augmentation.

Class balance

Distribution of examples per class.

5. Example Data Quality Scoring

An example combined frame quality score:

quality_score =
  0.25 * blur_score +
  0.20 * visibility_score +
  0.20 * relevance_score +
  0.15 * labelability_score +
  0.10 * diversity_score +
  0.10 * (1 - duplicate_score)

This formula is only illustrative. The exact weights can be tuned.

Decision logic example
quality_score >= 0.75 → accept
0.55 <= quality_score < 0.75 → maybe accept or recheck
quality_score < 0.55 → reject
Part 3 — Model Evaluation
6. Model Evaluation Goal

After training, the system needs to decide whether the current dataset produced a good enough detector.

It should answer:

is the detector usable?
what classes are weak?
are errors caused by bad data or not enough data?
should the system stop or run another iteration?
7. Core Model Metrics

The evaluation stage must compute at least:

mAP@50

Primary detection quality metric for the demo.

Precision

How often predicted boxes are correct.

Recall

How often true objects are found.

Per-class AP

Performance broken down by class.

These are the most important metrics for the hackathon version.

8. Optional Advanced Metrics

If available, the system can also track:

mAP@50-95
false positive rate
false negative rate
confusion trends
average confidence
performance by object size

These are useful, but not required for the MVP.

9. Evaluation Outputs

The evaluation stage should return:

metric summary
per-class performance
weak-class analysis
failure cases
next-step recommendation
Example evaluation report
{
  "map50": 0.71,
  "precision": 0.83,
  "recall": 0.68,
  "weak_classes": ["forklift"],
  "recommendation": "collect more side-angle examples and relabel small-object frames"
}
10. Weakness Analysis

The system should not just say the model is weak. It should say why.

Common causes of weak performance
too many blurry frames
not enough visual diversity
too many near-duplicates
boxes too noisy
target object often too small
one important angle underrepresented
class imbalance
Example findings
“model misses forklifts when viewed from the side”
“warehouse scenes are overrepresented, outdoor loading dock scenes are missing”
“small forklifts in distant frames were labeled inconsistently”
11. Model Quality Thresholds

Example stop conditions:

mAP@50 >= 0.75 → stop
precision >= 0.80 and recall >= 0.70 → acceptable
class-specific AP must not fall below a minimum floor

These numbers can be adjusted based on the demo.

Example policy
if the main class passes threshold, export artifacts
if it fails, iterate again if budget remains
if the budget is exhausted, export current best artifacts with warning
12. Iteration Decision Logic

Evaluation should drive what happens next.

If performance is weak because of poor data quality

Go back to:

frame filtering
label validation
source selection
If performance is weak because of low coverage

Go back to:

source collection
frame extraction
class balancing
If performance is weak because of noisy labels

Go back to:

label generation
label validation
If performance is acceptable
stop
export model
export dataset
export evaluation report
13. Example Evaluation-to-Iteration Rules
Rule 1

If mAP@50 < target and duplicate ratio is high:

gather more diverse sources
Rule 2

If recall is low and small-object detections fail:

prioritize closer or larger object frames
Rule 3

If precision is low:

relabel uncertain frames
reject low-confidence samples
Rule 4

If one class is much weaker than others:

recollect data for that class specifically
14. Final Artifacts

At the end of a successful run, the system should return:

Dataset artifacts
images
labels
data.yaml
accepted/rejected frame logs
augmentation log
source manifest
Model artifacts
trained weights
training logs
validation metrics
evaluation report
Why this matters

Users receive the full data and model package, not just a score or a black-box output.

15. Example End-to-End Flow
Input

"forklift in a warehouse"

Pipeline
discover relevant sources
ingest media
extract frames with ffmpeg
score frame quality
reject weak frames
auto-label accepted images
validate labels
package YOLO dataset
augment data
split train / val / test
train YOLO
evaluate mAP, precision, recall
iterate if below threshold
export dataset and weights
16. Success Criteria

The combined dataset pipeline and evaluation system is successful if:

it creates a valid YOLO dataset automatically
it removes low-quality examples before training
it produces measurable model metrics
it explains weak spots in the data or model
it can decide whether to stop or improve
it returns both the trained detector and the reusable dataset
17. Summary

Autonomous Dataset Agent treats dataset generation as the core problem in custom object detection. The pipeline does not just extract frames and train once. It actively builds a higher-quality dataset through source selection, frame critique, labeling, validation, augmentation, and metric-driven iteration. Evaluation is tightly connected to the dataset pipeline so the system can improve weak detectors by improving the data itself.


Next should be `DEMO.md` or `TASKS.md`.