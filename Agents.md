# AGENTS.md

# Autonomous Dataset Agent — Agent Definitions

## Overview

Autonomous Dataset Agent is built as a multi-agent system where each agent owns one part of the dataset-generation and model-training loop.

Instead of one monolithic pipeline trying to do everything, the system uses specialized agents that:
- search for useful visual data
- critique and filter candidate frames
- label accepted images
- build a trainable dataset
- train and evaluate a YOLO model
- decide whether to iterate or stop

This modular setup makes the pipeline easier to debug, improve, and explain.

---

## Agent Philosophy

Each agent should follow three principles:

### 1. Be specialized
Every agent should do one job well instead of mixing too many responsibilities.

### 2. Produce inspectable outputs
Each stage should leave behind artifacts, scores, or logs that can be reviewed.

### 3. Be replaceable
Agents should be modular so different models or heuristics can be swapped in later.

---

## Agent List

The system uses the following core agents:

1. Source Search Agent  
2. Source Ranking Agent  
3. Frame Critic Agent  
4. Label Agent  
5. Dataset Builder Agent  
6. Training Agent  
7. Evaluation Agent  
8. Iteration Agent  
9. Orchestrator Agent

---

# 1. Source Search Agent

## Purpose
Find relevant visual source material for a target object or scenario.

## Example input
- `"forklift in a warehouse"`
- `"helmet on construction workers"`
- `"delivery truck"`

## Responsibilities
- convert prompt into source search queries
- gather candidate videos or media sources
- broaden search to capture variation in angle, lighting, and context
- return candidate sources for ranking

## Inputs
- prompt
- target classes
- optional domain hints

## Outputs
- candidate source list
- source metadata
- relevance score
- source provenance

## Success criteria
- sources are relevant to the target class
- sources are visually diverse
- sources have enough usable content for frame extraction

## Failure cases
- too few relevant sources
- highly repetitive sources
- poor-quality or low-resolution media
- sources without clear object visibility

---

# 2. Source Ranking Agent

## Purpose
Rank discovered sources before downloading or processing them heavily.

## Responsibilities
- score relevance to target class
- estimate likely object visibility
- prefer diversity across environments and viewpoints
- reduce low-value or duplicate source selection

## Inputs
- candidate sources
- prompt
- class list

## Outputs
- ranked source list
- source scores
- selection justification

## Example ranking criteria
- relevance to class
- expected visual diversity
- source resolution
- camera stability
- expected object frequency
- duplication risk

## Why it matters
This prevents the system from wasting time extracting thousands of poor or repetitive frames.

---

# 3. Frame Critic Agent

## Purpose
Filter extracted frames and decide which ones are worth labeling.

## Responsibilities
- reject blurry frames
- reject near-duplicate frames
- reject heavily occluded or unusable examples
- prioritize frames where the target object is visible and learnable
- score frame quality

## Inputs
- extracted frames
- frame metadata
- prompt or class target

## Outputs
- accepted frames
- rejected frames
- rejection reasons
- quality score per frame

## Example rejection reasons
- blur too high
- target object not visible
- severe occlusion
- duplicate of earlier frame
- too far away to label reliably
- poor lighting

## Example scoring dimensions
- blur score
- object visibility
- labelability
- diversity contribution
- duplication similarity
- confidence of relevance

## Success criteria
- accepted set is smaller but much higher quality
- dataset quality improves without excessive data loss
- output is more diverse than naive frame sampling

## Why this agent is important
This is one of the biggest differentiators in the project. The system is not just extracting frames — it is curating a better training set.

---

# 4. Label Agent

## Purpose
Generate object annotations for accepted frames.

## Responsibilities
- identify target objects
- generate bounding boxes
- map boxes into YOLO format
- optionally attach confidence scores
- reject uncertain labels when needed

## Inputs
- accepted frames
- class list
- labeling prompt or schema

## Outputs
- YOLO label files
- label confidence metadata
- optional frame-level notes

## YOLO output format
```text
<class_id> <x_center> <y_center> <width> <height>
Example
0 0.523 0.481 0.211 0.327
Success criteria
labels are structurally valid
boxes align well with objects
confidence is high enough for training
class IDs remain consistent across dataset
Failure cases
missing objects
loose or inaccurate boxes
inconsistent class mapping
hallucinated objects
invalid coordinate format
Notes

This agent can use a vision-capable model for structured box generation and may optionally pass uncertain samples back for re-checking.

5. Dataset Builder Agent
Purpose

Package images and labels into a trainable YOLO dataset.

Responsibilities
organize accepted frames into dataset structure
align images and labels correctly
create train / val / test split
write data.yaml
apply augmentations
preserve dataset metadata
Inputs
accepted images
labels
class names
augmentation configuration
Outputs
dataset folder in YOLO format
split summary
augmentation log
dataset manifest
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
Example augmentations
horizontal flip
brightness adjustment
contrast shift
noise injection
Success criteria
dataset is valid and trainable
labels stay aligned after augmentations
class mapping is correct
splits are reproducible
6. Training Agent
Purpose

Train a YOLO model on the generated dataset.

Responsibilities
load dataset configuration
run training job
save checkpoints
track training logs
return the best model artifact
Inputs
dataset path
YOLO config
hyperparameters
training budget
Outputs
trained weights
logs
metrics files
checkpoint summary
Example artifacts
best.pt
last.pt
results.csv
Success criteria
training completes without breaking
weights are saved correctly
metrics are produced
model is ready for evaluation
Notes

For hackathon scope, this agent only needs to support one strong YOLO training path well.

7. Evaluation Agent
Purpose

Judge the model and determine how well the current dataset performed.

Responsibilities
compute evaluation metrics
identify weak classes
identify likely failure modes
surface whether another iteration is needed
Inputs
trained model
validation set
evaluation config
Outputs
evaluation report
metric summary
weak-class analysis
recommendation
Core metrics
mAP@50
precision
recall
per-class AP
Optional deeper signals
confusion trends
false positive patterns
false negative patterns
label confidence correlation
Success criteria
metrics are clear and reproducible
weak spots are actionable
output can guide the next improvement step
Example recommendation
“class performance is weak because examples are too small and too repetitive”
“collect more side-angle forklift examples”
“relabel low-confidence warehouse frames”
8. Iteration Agent
Purpose

Control the improvement loop.

Responsibilities
read evaluation results
decide whether to stop or continue
choose which upstream stage to revisit
avoid unnecessary retraining
Inputs
evaluation report
run history
target threshold
iteration limit
Outputs
stop decision
retry plan
next-stage instruction
Possible actions
gather more sources
extract more frames
relabel low-confidence examples
rebalance dataset
retrain model
stop and export artifacts
Example decision rules
if mAP@50 is below threshold, continue
if one class is weak, gather more data for that class
if labels are noisy, relabel before training again
if iteration budget is exhausted, stop
Success criteria
retries are metric-driven
system does not loop blindly
each new iteration has a clear purpose
9. Orchestrator Agent
Purpose

Coordinate all other agents and manage the full lifecycle of a run.

Responsibilities
create job state
call agents in the right order
pass artifacts between stages
log progress
track failures
stop gracefully when needed
Inputs
user prompt
config
system defaults
Outputs
full job state
stage logs
final artifacts
final summary
Why it matters

Without the orchestrator, the system is just a set of disconnected tools. This agent turns them into a coherent pipeline.

Agent Interaction Flow
User Prompt
  -> Orchestrator Agent
  -> Source Search Agent
  -> Source Ranking Agent
  -> Frame Extraction
  -> Frame Critic Agent
  -> Label Agent
  -> Dataset Builder Agent
  -> Training Agent
  -> Evaluation Agent
  -> Iteration Agent
  -> Final Dataset + Model Export
Example End-to-End Run
Prompt

"forklift in a warehouse"

Agent flow
Orchestrator starts a new job
Source Search Agent finds candidate warehouse footage
Source Ranking Agent prioritizes the most useful sources
Frames are extracted from selected videos
Frame Critic Agent filters bad frames
Label Agent generates forklift bounding boxes
Dataset Builder Agent creates YOLO dataset
Training Agent trains model
Evaluation Agent scores performance
Iteration Agent decides whether to gather more data or stop
Final artifacts are exported
Shared Data Contracts

To keep agents modular, each agent should communicate using structured outputs.

Example shared artifacts
source_manifest.json
frame_scores.json
accepted_frames.json
labels_manifest.json
dataset_manifest.json
training_results.json
evaluation_report.json
Why this matters

Structured outputs make the pipeline:

debuggable
reproducible
easy to swap components in and out
Agent Priorities
Source Search Agent priority

maximize relevance and diversity

Source Ranking Agent priority

reduce wasted processing on bad media

Frame Critic Agent priority

maximize data quality before labeling

Label Agent priority

produce consistent and accurate boxes

Dataset Builder Agent priority

create valid, trainable dataset artifacts

Training Agent priority

produce stable model checkpoints and logs

Evaluation Agent priority

surface measurable performance and weaknesses

Iteration Agent priority

make smart retry decisions, not endless loops

Orchestrator Agent priority

keep the full system coordinated and reliable

Minimal Hackathon Version

For the hackathon MVP, some agents can be simplified.

Must-have agents
Orchestrator Agent
Frame Critic Agent
Label Agent
Training Agent
Evaluation Agent
Can be lighter or heuristic-based
Source Ranking Agent
Iteration Agent
Can be partially manual in fallback
Source Search Agent

This keeps the core story intact even if every stage is not fully autonomous on day one.

Future Agent Extensions

Potential future agents include:

Diversity Agent

Measures dataset diversity across viewpoint, scale, and background.

Provenance Agent

Tracks where every training frame came from.

Human Review Agent

Lets a user quickly approve or reject uncertain labels.

Deployment Agent

Exports trained detector into live webcam or RTSP deployment.

Domain Template Agent

Applies domain-specific defaults for warehouse, healthcare, or urban monitoring.

Summary

Autonomous Dataset Agent works because each part of the pipeline is handled by a specialized agent with a clear job, clear outputs, and measurable success criteria. The most important agents are the ones that improve data quality before training: source selection, frame critique, and labeling. Together, these agents make the system feel less like a normal ML script and more like an autonomous dataset engineer for object detection.