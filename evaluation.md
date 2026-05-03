# EVALUATION.md

## Overview

This document defines how Autonomous Dataset Agent evaluates both **dataset quality** and **model quality**, and how those scores drive the system's automatic retraining loop.

The evaluation layer answers four questions:

1. Is the collected data good enough to train on?
2. Is the trained YOLO model good enough to ship?
3. If not, what is the failure mode?
4. What should the agent do next: recollect, relabel, retrain, or stop?

---

## Evaluation Goals

The system should not blindly train on every collected frame.

Instead, it should:
- reject low-value training samples
- measure detector performance with standard object detection metrics
- identify weak classes and weak data sources
- decide how to improve performance automatically

---

## Evaluation Layers

The pipeline evaluates output at two levels:

1. **Dataset Quality Evaluation**
2. **Model Performance Evaluation**

---

# 1. Dataset Quality Evaluation

## Purpose

Before training begins, the system scores candidate frames to ensure the dataset is useful, diverse, and labelable.

## Frame Quality Checks

Each extracted frame is scored on the following dimensions:

### Blur Score
Measures whether the frame is too blurry to provide useful object boundaries.

- High blur → reject
- Moderate blur → keep only if the object is still clearly visible
- Low blur → accept

### Occlusion Score
Measures how much of the target object is hidden.

- Heavy occlusion → reject
- Partial occlusion → may keep for robustness if enough object is visible
- Clear object → accept

### Duplicate Score
Measures near-duplicate similarity against already accepted frames.

- Near-identical frames → reject
- Slightly different viewpoint/timing → maybe keep
- Diverse frames → accept

### Label Confidence Score
Measures confidence in the bounding box annotation from the labeling model.

- Low confidence → reject or relabel
- Medium confidence → optionally send for second-pass labeling
- High confidence → accept

### Object Visibility Score
Checks whether the target object is large enough and visible enough to help training.

- Tiny, barely visible object → reject
- Clear and trainable object → accept

### Diversity Score
Measures how much new information a frame adds to the dataset.

Signals may include:
- camera angle
- scale
- lighting
- background
- clutter
- scene type
- object pose

Low-diversity frames are deprioritized.

---

## Frame Acceptance Rule

A frame is accepted only if it passes minimum thresholds for:

- blur
- visibility
- label confidence
- non-duplication

Example rule:

- blur score >= 0.60
- visibility score >= 0.65
- label confidence >= 0.70
- duplicate similarity <= 0.92

These thresholds are tunable.

---

## Dataset-Level Health Checks

After frame-level filtering, the system evaluates the full dataset.

### Class Balance
Checks whether one class dominates the dataset.

Bad example:
- forklift: 900 images
- pallet jack: 80 images

Action:
- collect more examples for underrepresented classes

### Source Diversity
Checks whether the dataset is overly dependent on one source.

Bad example:
- 80% from one warehouse video

Action:
- gather more images or videos from different sources

### Environment Diversity
Checks whether the object only appears in one setting.

Bad example:
- all forklifts indoors with identical lighting

Action:
- search for outdoor, nighttime, cluttered, and alternate-angle examples

### Trainability Check
Confirms there are enough usable samples to begin training.

Example minimum:
- at least 100 accepted labeled images per class for first-pass training
- at least 3 distinct source environments per class

---

## Dataset Quality Score

The system combines frame and dataset checks into a single score:

**Dataset Quality Score (DQS)**

Example weighted formula:

- 25% label confidence
- 20% blur quality
- 20% diversity
- 15% visibility
- 10% duplicate reduction
- 10% class balance

Score range:
- 0.90 - 1.00 → excellent
- 0.75 - 0.89 → usable
- 0.60 - 0.74 → weak, improve before training
- below 0.60 → insufficient

---

# 2. Model Performance Evaluation

## Purpose

After training, the system evaluates the YOLO model using standard object detection metrics.

## Primary Metrics

### mAP@50
Main quality metric for hackathon/demo purposes.

Tracks how well predicted boxes match ground truth at IoU = 0.50.

### Precision
Measures how many predicted detections were correct.

Low precision usually means:
- noisy labels
- too many false positives
- ambiguous or low-quality training data

### Recall
Measures how many real objects were successfully detected.

Low recall usually means:
- not enough training examples
- insufficient viewpoint diversity
- missing hard cases

### Per-Class AP
Measures model performance per class.

Used to identify weak classes that need more data.

---

## Secondary Metrics

### False Positive Rate
Helpful for understanding precision failures.

### False Negative Rate
Helpful for understanding recall failures.

### Confidence Distribution
Used to check whether the detector is uncertain even on correct predictions.

### Class Weakness Ranking
Ranks classes from strongest to weakest based on AP, recall, and confidence.

---

## Validation Set Policy

The validation set should reflect the same broad distribution as training, but contain unseen samples.

Recommended split:
- train: 70%
- val: 20%
- test: 10%

Training data may include both:
- web images
- selected video-derived frames

Validation should also include a held-out mix of both.

Test data should be the most deployment-like set available.

Example:
- if deployment is webcam or warehouse footage, the test set should resemble that

---

## Model Quality Score

The system combines detection metrics into a single score:

**Model Quality Score (MQS)**

Example weighted formula:

- 40% mAP@50
- 20% precision
- 20% recall
- 20% per-class balance

Score range:
- 0.90 - 1.00 → production-quality for prototype
- 0.80 - 0.89 → strong
- 0.70 - 0.79 → acceptable, but improve if time allows
- below 0.70 → retrain or recollect

---

# 3. Stop / Retry Logic

## Stop Condition

The system stops iterating when both conditions are met:

- Dataset Quality Score >= target threshold
- Model Quality Score >= target threshold

Example:
- DQS >= 0.80
- MQS >= 0.80

## Retry Condition

If the model underperforms, the system chooses a next action based on the failure pattern.

---

# 4. Failure Diagnosis Rules

## Case A: Low Precision
Symptoms:
- many false positives
- detector fires on wrong objects/background clutter

Likely causes:
- noisy labels
- ambiguous classes
- poor-quality frames
- weak negative examples

Recommended action:
- filter bad frames
- relabel low-confidence samples
- add harder negatives
- tighten acceptance thresholds

## Case B: Low Recall
Symptoms:
- misses real objects often

Likely causes:
- not enough examples
- weak viewpoint diversity
- missing occluded/small/far-away cases

Recommended action:
- collect more data
- increase source diversity
- add harder positive examples
- increase representation of weak classes

## Case C: One Weak Class
Symptoms:
- overall metrics are okay, but one class is bad

Likely causes:
- class imbalance
- weak labeling quality for that class
- too few unique scenes for that class

Recommended action:
- targeted recollection for the weak class
- relabel hard samples
- oversample during training if needed

## Case D: Good Validation, Bad Real-World Test
Symptoms:
- model performs well in eval but fails in demo

Likely causes:
- test distribution mismatch
- training data too clean
- not enough deployment-like samples

Recommended action:
- gather more realistic camera data
- increase video-derived realism
- build test set closer to deployment conditions

---

# 5. Agent Decision Rules

After each run, the evaluator recommends one of four actions:

## 1. ACCEPT
Use when:
- metrics meet threshold
- no major class weakness
- demo/test performance is stable

## 2. RECOLLECT
Use when:
- recall is low
- diversity is low
- class balance is weak
- too few good samples exist

## 3. RELABEL
Use when:
- precision is low
- label confidence is low
- boxes are noisy or inconsistent

## 4. RETRAIN
Use when:
- data quality is acceptable
- labels are acceptable
- performance can likely improve with different hyperparameters or better sampling

---

# 6. Baseline Thresholds

These are default thresholds for the prototype.

## Dataset thresholds
- minimum accepted images per class: 100
- minimum label confidence: 0.70
- maximum duplicate similarity: 0.92
- minimum diversity score: 0.65

## Model thresholds
- target mAP@50: 0.75
- minimum precision: 0.70
- minimum recall: 0.70
- no class AP below: 0.55

These values can be tuned depending on object difficulty and hackathon scope.

---

# 7. Run Comparison

Each run should log:

- run ID
- classes
- number of accepted frames
- source breakdown
- dataset quality score
- training config
- mAP@50
- precision
- recall
- per-class AP
- decision outcome
- recommended next action

This allows the system to compare iterations and justify why a retrain or recollection happened.

---

# 8. Final Deliverables Per Run

Each completed run should return:

- dataset quality summary
- accepted vs rejected frame counts
- rejection reasons
- model evaluation metrics
- weak-class analysis
- final decision:
  - accepted
  - recollect
  - relabel
  - retrain

---

# 9. Success Definition

A run is considered successful when the system produces:

1. a usable labeled dataset
2. a trained YOLO model
3. a measurable evaluation report
4. a clear explanation of why the model is or is not ready

The project is not only judged by whether a model trains, but by whether the system can **evaluate itself and improve automatically**.

---

## Summary

Autonomous Dataset Agent is not just a training pipeline. Its core value comes from the feedback loop.

The evaluation system is what makes that loop real:
- it filters weak data
- scores model quality
- diagnoses failure modes
- drives the next action automatically

Without evaluation, the system is just automation.  
With evaluation, it becomes an agentic training pipeline.