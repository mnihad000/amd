# PRD.md

## Product Requirements Document

## Product Name
**Autonomous Dataset Agent**

## One-Line Summary
Autonomous Dataset Agent is an agentic computer vision pipeline that takes a target object or scenario and automatically builds a labeled dataset, trains a YOLO detector, evaluates it, and returns both the model and the dataset.

---

## 1. Problem

Training a custom object detector usually requires too much manual work:
- finding enough images or videos
- extracting useful frames
- labeling bounding boxes
- removing blurry or duplicate samples
- training and evaluating multiple times
- collecting more data when the model fails

This process is slow, repetitive, and hard to scale for niche or custom classes.

---

## 2. Product Vision

Build a system where a user can type something like:

> `"forklift in a warehouse"`

and the platform will:
1. collect relevant visual data
2. extract candidate images/frames
3. filter bad samples
4. auto-label accepted samples
5. package a YOLO dataset
6. train a detector
7. evaluate quality
8. iterate if needed
9. return the model and the dataset

The goal is to make custom object detection feel closer to **prompting a system** than manually building an ML pipeline.

---

## 3. Users

### Primary Users
- hackathon teams
- ML engineers prototyping custom detectors
- researchers testing niche object classes
- developers who want fast object detection bootstrapping

### Secondary Users
- startups building vertical vision tools
- operations teams needing custom detection for warehouses, construction, logistics, or monitoring
- students learning applied ML systems

---

## 4. Core Use Case

A user wants a detector for a custom object or scenario but does not want to manually build the dataset.

### Example
Input:
- target class: `forklift`
- context: `warehouse`
- optional source preferences
- optional performance target

Output:
- labeled dataset in YOLO format
- train/val/test split
- augmentation outputs
- trained YOLO weights
- evaluation summary
- weak-class or weak-sample analysis

---

## 5. Goals

### Primary Goals
- automate dataset creation for object detection
- reduce manual labeling effort
- produce a usable YOLO model
- return the dataset as a reusable artifact
- make the pipeline self-improving through evaluation-driven iteration

### Secondary Goals
- support multiple data sources
- support multiple labeling backends
- make the system modular and agent-based
- make demo results understandable and visually convincing

---

## 6. Non-Goals

The first version will **not** aim to:
- replace state-of-the-art enterprise annotation platforms
- support every computer vision task
- train giant foundation models
- guarantee production-grade performance on every class
- solve legal/compliance coverage for every web source
- perform detailed human-in-the-loop review workflows

The first version is focused on:
- object detection
- YOLO-compatible datasets
- automated collection, labeling, training, and evaluation

---

## 7. Product Principles

### 1. Dataset-first
The product should not only output a model. It must return the dataset used to train it.

### 2. Evaluation-driven
The system should use measurable metrics to decide whether to stop or improve.

### 3. Agentic but grounded
Agents should perform concrete actions: collect, filter, label, train, evaluate, and decide next steps.

### 4. Modular
Each stage should be separable so components can be swapped later.

### 5. Demoable
The project should produce outputs that are easy to show live:
- accepted/rejected frames
- labeled samples
- training metrics
- final detector behavior

---

## 8. Key Features

### 8.1 Prompt-Based Detector Creation
User provides:
- object/class name
- optional scenario/context
- optional source preferences
- optional desired performance threshold

### 8.2 Autonomous Data Collection
The system gathers candidate visual material from supported sources such as:
- web images
- public datasets
- video sources
- uploaded files

### 8.3 Frame / Image Filtering
A critic step removes bad samples based on:
- blur
- occlusion
- duplication
- low object visibility
- low labelability
- poor confidence

### 8.4 Automatic Label Generation
A vision-capable model creates bounding box labels in structured format.

### 8.5 Dataset Packaging
Accepted samples are converted into YOLO dataset structure with:
- image folders
- label folders
- split metadata
- dataset config

### 8.6 Data Augmentation
Apply transformations such as:
- flip
- brightness adjustment
- contrast adjustment
- noise
- optional additional augmentation later

### 8.7 YOLO Training
Use the generated dataset to train a detector.

### 8.8 Evaluation Loop
Evaluate training results with:
- mAP@50
- precision
- recall
- per-class AP
- failure pattern analysis

### 8.9 Iteration Logic
If performance is weak, the system should:
- gather more data
- relabel poor samples
- retrain
- target weak classes

### 8.10 Exportable Artifacts
Final outputs should include:
- dataset
- model
- metrics
- logs / summary

---

## 9. User Flow

### Happy Path
1. User enters target class and context
2. System collects candidate sources
3. System extracts or downloads candidate images
4. Critic filters poor samples
5. Labeler annotates accepted samples
6. Dataset builder creates YOLO dataset
7. Trainer trains model
8. Evaluator scores model
9. If threshold is met, artifacts are exported
10. User receives detector + dataset + report

### Recovery Path
If the model underperforms:
1. evaluator identifies likely cause
2. system recollects or relabels
3. training runs again
4. artifacts update after improvement

---

## 10. Inputs

### Required Inputs
- target class or classes

### Optional Inputs
- context or environment
- desired confidence/performance target
- max runtime budget
- allowed data sources
- number of iterations
- label backend
- training configuration preset

### Example Inputs
- `"forklift in a warehouse"`
- `"hard hats on construction sites"`
- `"pallet jack in a storage room"`

---

## 11. Outputs

### Primary Outputs
- trained YOLO model weights
- labeled dataset in YOLO format

### Secondary Outputs
- evaluation report
- dataset quality summary
- accepted vs rejected sample counts
- rejection reasons
- per-class performance summary
- run logs
- artifact bundle for reuse

---

## 12. Success Metrics

### Product Success
- user can go from prompt to trained detector with minimal manual work
- pipeline completes end to end without human labeling
- returned dataset is reusable
- results are understandable enough to demo clearly

### Model Success
Baseline prototype targets:
- mAP@50 >= 0.75
- precision >= 0.70
- recall >= 0.70

### Dataset Success
- enough accepted images per class to train
- balanced enough class distribution
- reasonable source diversity
- low duplicate concentration
- acceptable label confidence

---

## 13. Functional Requirements

### FR1: Class Prompt Intake
The system must accept a class prompt and optional context.

### FR2: Source Collection
The system must gather candidate data from supported sources.

### FR3: Media Processing
The system must be able to:
- extract frames from videos
- download/process images
- normalize image formats

### FR4: Sample Critique
The system must score and filter candidate samples.

### FR5: Label Generation
The system must generate bounding box labels for accepted samples.

### FR6: YOLO Dataset Export
The system must export a valid YOLO training dataset.

### FR7: Training
The system must trigger YOLO training on the generated dataset.

### FR8: Evaluation
The system must calculate model metrics and summarize failures.

### FR9: Iteration Decision
The system must decide whether to stop, recollect, relabel, or retrain.

### FR10: Artifact Delivery
The system must return both dataset and model artifacts.

---

## 14. Non-Functional Requirements

### NFR1: Speed
Prototype should be fast enough for hackathon demo flow.

Target:
- usable first-pass result in minutes, not hours, for a small class setup

### NFR2: Modularity
Each pipeline stage should be independently replaceable.

### NFR3: Reliability
Pipeline should fail gracefully and surface which stage broke.

### NFR4: Transparency
System should expose:
- accepted/rejected sample counts
- evaluation metrics
- next-step decision

### NFR5: Reproducibility
Runs should log enough metadata to repeat or compare experiments.

---

## 15. Risks

### Risk 1: Bad Data Quality
Poor source material may lead to weak labels and weak training.

### Risk 2: Duplicate Video Frames
Too many near-identical frames can create fake dataset size without real diversity.

### Risk 3: Label Noise
Automatic box generation may introduce incorrect labels.

### Risk 4: Slow Iteration
Training and recollection may take too long for a live demo.

### Risk 5: Distribution Mismatch
The model may perform well on validation but poorly in the final demo environment.

---

## 16. Risk Mitigations

- use critic filtering before labeling
- prefer source diversity over raw frame volume
- keep video as secondary depth source, not dominant source
- use validation and deployment-like test samples
- allow lightweight training presets for demo mode
- surface failure reasons clearly

---

## 17. MVP Scope

The MVP must support:
- one or a few classes
- image + optional video-derived samples
- auto-labeling
- YOLO dataset generation
- YOLO training
- metric evaluation
- one feedback iteration
- artifact export

### MVP Demo Goal
User types a class prompt, waits through the pipeline, and receives:
- labeled dataset preview
- training metrics
- model output on a test image or webcam feed

---

## 18. Future Scope

Possible future additions:
- broader source adapters
- synthetic image generation
- human correction interface
- multi-class planning assistant
- active learning loop
- deployment dashboard
- healthcare / urban monitoring presets
- privacy-safe domain modes

---

## 19. Open Questions

- which data sources are allowed in the first prototype?
- how many classes can reasonably be supported in one run?
- what is the live-demo runtime budget?
- which labeling backend is most reliable for bounding boxes?
- what minimum threshold should trigger recollection vs relabeling?
- how much augmentation helps before it starts hurting realism?

---

## 20. Demo Narrative

The most important story is:

> A user describes what they want to detect, and instead of manually building the dataset, the system autonomously creates it, trains the detector, evaluates the results, and gives both the model and the dataset back.

This should feel like:
- less manual ML workflow
- more autonomous vision infrastructure

---

## 21. Final Definition of Success

Autonomous Dataset Agent is successful if it can take a simple detection request and autonomously produce:
1. a valid labeled dataset
2. a trained YOLO detector
3. an evaluation report
4. a clear next-step decision if the model is not yet strong enough

The core value is not just model training.  
The core value is automating the hardest part of custom object detection: **building and improving the dataset**.