# TASKS.md

# Autonomous Dataset Agent - Post-MVP Enterprise Roadmap

## Progress So Far

- MVP pipeline is complete end-to-end from prompt intake to dataset and model artifacts.
- CLI-first orchestration runs full jobs with class planning, ingestion, curation, labeling, dataset build, training hooks, and evaluation hooks.
- Dual ingestion paths are implemented for structured web images and YouTube-driven video extraction.
- Frame quality control and duplicate filtering are active in the frame critic stage.
- Dynamic class admission exists to avoid hard upfront class caps in multi-class requests.
- Async FastAPI job lifecycle is implemented for create, list, detail, cancel, and health endpoints.
- Persisted run state survives process restart and marks interrupted queued/running jobs as failed.
- Stage-level status and timing are recorded and exposed through the backend lifecycle.
- Artifact and file preview flows are available for manifests, outputs, and run assets.
- Frontend dashboard is live with run submission, progress polling, cancellation, and recent-run reopen.
- Dashboard surfaces class outcomes, key metrics, and artifact previews for operator review.
- Baseline backend API tests are in place and frontend lint/typecheck gates are operational.

## Future Tasks

### 1. Multi-Class Data and Label Quality Hardening

**Approved decisions**
- Hard quota policy: training is blocked if any admitted class misses train/val minimum.
- Class semantics: flat independent classes only (no hierarchy or alias merge in section 1).
- Hard negatives: mine from existing labeled runs and prior evaluation artifacts.
- Review queue policy: mandatory human resolution before training.
- Scope cut: backend + API only for section 1 (no frontend review workspace yet).
- Rollout: feature flag default on, with explicit opt-out legacy mode.

**Implementation checklist**
- [x] Add `ClassQualityConfig` with defaults and env wiring:
  - `enabled=true`
  - `min_train_samples`, `min_val_samples`
  - `review_confidence_threshold`
  - `conflict_iou_threshold`
  - `hard_negative_top_k`
  - `opt_out_legacy_mode`
- [x] Add class-quality artifacts under `reports/`:
  - `class_quality_report.json`
  - `review_queue.json`
  - `hard_negative_candidates.json`
  - `class_quota_gate.json`
- [x] Extend critic/sample selection to be class-aware:
  - pass 1: satisfy per-class minimum candidate pool for labeling
  - pass 2: maximize quality while preserving minority-class coverage
  - pass 3: enforce source mix targets
- [x] Add per-sample diagnostics in critic outputs:
  - `class_coverage_delta`
  - `minority_boost_applied`
  - class-context rejection reason
- [x] Persist class distribution before/after balancing in `class_quality_report.json`.
- [x] Extend label validation to emit review reasons:
  - low confidence
  - cross-class conflict
  - ambiguous overlap
  - insufficient box geometry
- [x] Route uncertain labels into `review_queue.json` with states:
  - `pending`, `approved`, `relabel_requested`, `rejected`
- [x] Enforce mandatory review completion:
  - block training if any required review item is still `pending`
- [x] Add hard-negative mining pass from prior artifacts:
  - scan prior `labels_manifest`, `evaluation_report`, and optional predictions
  - generate class-pair confusion candidates
  - promote top-k hard negatives into next labeling candidate set
- [x] Add hard class quota gate before training:
  - require each admitted class to satisfy `min_train_samples` and `min_val_samples`
  - write structured fail/pass reasons to `class_quota_gate.json`
- [x] Update run summary/class states with explicit quota-gate and review-gate outcomes.
- [x] Add additive API fields for run details:
  - per-class accepted/labeled/train/val counts
  - quota status per class
  - review queue summary counts
  - hard-negative mining summary
- [x] Add API endpoints for review operations:
  - fetch review queue by run
  - submit review decisions (`approve`, `relabel_requested`, `reject`)
- [x] Keep existing API contract backward-compatible (additive only).

**Validation checklist (section 1)**
- [x] Unit: class-aware sampler preserves minority classes under mixed quality.
- [x] Unit: quota gate blocks training when any class misses minimum split counts.
- [x] Unit: label validator routes low-confidence/conflict samples into review queue.
- [x] Unit: hard-negative miner returns deterministic top-k candidates.
- [x] Integration: multi-class imbalance run is blocked until quota gate passes.
- [x] Integration: pending review items block training.
- [x] Integration: resolved review decisions unblock training when quotas pass.
- [x] Integration: API review endpoints and additive run detail fields are stable.
- [x] Regression: legacy behavior preserved when opt-out legacy mode is enabled.
- [x] Regression: single-class baseline runs still succeed.

### 2. Iteration Intelligence and Decision Policy

**Approved decisions**
- Decision engine: deterministic policy rules on per-class AP/precision/recall + failure modes.
- Regression protection: hard compare to last promoted model with promotion blocking on critical-class regression.
- Budget policy: hard caps on runtime, iteration count, and label-call budget.
- Action set: full set enabled (`re-ingest`, `re-critic`, `relabel`, `rebalance`, `retrain`, `stop`, `promote`).
- Regression blocking scope: critical classes block; non-critical regressions warn.
- Critical class source: per-run user-provided list, fallback to all admitted classes.
- Threshold policy: configurable thresholds with sensible defaults (not hardcoded constants).

**Implementation checklist**
- [x] Add `IterationPolicyConfig` with env/config wiring:
  - per-class AP/precision/recall minimums
  - acceptable per-class delta vs baseline
  - minimum gain threshold for `promote`
  - max iteration count, max runtime, max label calls
- [x] Extend run input/config to accept optional `critical_classes`.
- [x] Add fallback rule: if `critical_classes` absent, use all requested/admitted classes as critical.
- [x] Replace current iteration heuristic with deterministic rule-priority engine.
- [x] Implement deterministic failure-mode-to-action mapping:
  - low AP -> targeted `re-ingest` or `rebalance`
  - precision drift -> `relabel`/`re-critic`
  - recall drift or sample scarcity -> `re-ingest`/`retrain`
  - quality recovered with gains -> `promote`
- [x] Enforce fixed rule ordering so identical inputs always produce identical output.
- [x] Add baseline loader for last promoted model metrics for matching project/class context.
- [x] Compute per-class deltas vs baseline and persist comparison.
- [x] Implement promotion guard:
  - block `promote` when any critical class exceeds negative delta tolerance
  - keep non-critical regressions as warnings only
- [x] Implement budget hard-stop checks:
  - runtime cap
  - iteration cap
  - label-call cap
- [x] Add degrade policy near budget limits:
  - prefer cheaper next action (`relabel`/`rebalance`) before costly paths (`re-ingest`/`retrain`) when valid
- [x] Emit `stop` with structured budget-exhaustion reasons when no compliant action remains.
- [x] Add section 2 artifacts:
  - `iteration_policy_report.json`
  - `baseline_comparison.json`
  - `promotion_guard.json`
- [x] Extend run summary with additive iteration-policy fields:
  - selected action
  - target classes
  - policy reasons
  - budget snapshot
  - regression gate status
- [x] Extend API run detail payload with additive objects:
  - `iteration_policy`
  - baseline comparison summary
  - critical-class regression gate summary
- [x] Preserve backward compatibility for old runs and old API consumers.

**Validation checklist (section 2)**
- [x] Unit: deterministic ordering returns same action for same inputs.
- [x] Unit: failure-mode mapping selects expected action per scenario.
- [x] Unit: critical-class regression blocks `promote`.
- [x] Unit: non-critical regression does not block `promote` and emits warnings.
- [x] Unit: budget cap exceedance forces `stop`.
- [x] Integration: weak per-class AP triggers targeted action (not generic recollect).
- [x] Integration: critical-class baseline regression blocks promotion.
- [x] Integration: exhausted label-call budget stops with explicit policy reason.
- [x] Integration: no baseline history degrades gracefully and still writes artifacts.
- [x] Regression: older runs without new policy fields remain readable via API.

### 3. Data Governance and Provenance

**Approved decisions**
- Full governance scope is required now: lineage + license enforcement + audit logs.
- Immutable manifest IDs/checksums remain source-of-truth for dataset/model versioning.
- Policy is hard-enforced: license or provenance violations block run progression and export.

**Implementation checklist**
- [x] Add immutable lineage artifacts linking:
  - source -> frame -> accepted sample -> label -> split -> dataset version -> model version -> promotion decision
- [x] Add deterministic dataset/model version IDs using manifest checksums.
- [x] Add source license metadata schema (origin, license type, usage rights, expiration, restrictions).
- [x] Enforce ingestion-time license validation with explicit allow/deny outcomes.
- [x] Enforce export-time license/compliance validation with blocking on violations.
- [x] Add actor-level audit trail events for:
  - automated decisions (search/ranking/critic/labeling/iteration/promotion)
  - human actions (review, approval, reject, relabel, override)
- [x] Add retention/deletion policy controls and artifact lifecycle status tracking.
- [x] Expose additive governance/provenance summary in run outputs and API detail payload.

**Validation checklist (section 3)**
- [x] Unit: lineage chain is complete and deterministic for identical inputs.
- [x] Unit: checksum/version IDs are reproducible and immutable post-finalization.
- [x] Unit: license policy blocks disallowed source ingestion/export.
- [x] Integration: audit trail captures automated + human actions with actor/context.
- [x] Regression: legacy runs without governance fields remain readable via API.

### 4. Training and Evaluation Hardening

**Approved decisions**
- Reproducibility and hard promotion gates are mandatory.
- Default validation mode is seeded single-run + benchmark gate (multi-seed/CV optional, not default-mandatory).
- Promotion is blocked when hard thresholds or benchmark regression checks fail.

**Implementation checklist**
- [x] Standardize training/eval runtime profile:
  - fixed random seeds
  - pinned dependencies
  - containerized execution baseline
- [x] Add promotion gate policy with explicit hard thresholds for core quality metrics.
- [x] Add deterministic benchmark suite for multi-class scenarios and long-tail stress checks.
- [x] Add baseline regression checks against approved benchmark snapshots.
- [x] Extend evaluation artifacts with class-level failure diagnostics tied to iteration actions.
- [x] Add optional advanced validation modes:
  - repeated-seed runs
  - cross-validation
  - keep these opt-in unless policy explicitly enables them
- [x] Surface additive promotion-gate outcomes in run summary/API (pass/fail reasons).

**Validation checklist (section 4)**
- [x] Unit: seeded runs are reproducible under fixed runtime profile.
- [x] Unit: promotion gate blocks failing metric thresholds.
- [x] Unit: benchmark regression checker blocks degraded models.
- [x] Integration: eval artifacts include actionable class-level failure diagnostics.
- [x] Regression: baseline single-class and multi-class flows still complete when thresholds pass.

### 5. Observability and Reliability Telemetry

**Approved decisions**
- Self-hosted observability is the primary monitoring backend (OpenTelemetry + Prometheus + Grafana + Loki).
- Telemetry must cover reliability + quality + cost and be correlation-friendly by `job_id`.
- Alerting is mandatory for operational failure and model-quality degradation states.

**Implementation checklist**
- [ ] Define telemetry contract for:
  - stage latency/throughput/failure/retry/queue depth
  - class-level acceptance rates, AP drift, label-confidence distributions
  - run/stage-level cost signals
- [ ] Propagate `job_id` end-to-end as primary correlation key across pipeline and external sinks.
- [ ] Integrate self-hosted observability stack:
  - OpenTelemetry instrumentation for traces/metrics/log correlation
  - Prometheus for metric scraping and retention
  - Loki for structured log aggregation
  - Grafana for dashboards and alerting
- [ ] Standardize structured logging envelope with correlation fields and severity taxonomy.
- [ ] Add alert policy definitions for:
  - stuck runs
  - repeated stage failures
  - class regression and drift anomalies
  - budget anomalies
- [ ] Add additive API monitoring summary objects linked to internal telemetry store.

**Validation checklist (section 5)**
- [ ] Unit: telemetry schema validation and required field completeness.
- [ ] Integration: Prometheus/Loki/Grafana pipeline returns expected run/class metrics and logs.
- [ ] Integration: alert rules trigger correctly for simulated failure/degradation scenarios.
- [ ] Regression: run flow remains operational when observability sink is temporarily unavailable.

### 6. Production Orchestrator and Workflow Resilience

**Approved decisions**
- Keep current job manager path and harden incrementally (no immediate full replacement).
- Hard requirements: idempotency, dead-letter handling, checkpoint resume, rollback to last stable promoted state.
- Backward-compatible API/run lifecycle behavior must be preserved while adding resilience metadata.

**Implementation checklist**
- [ ] Define idempotency contracts per stage (keys, side effects, replay safety rules).
- [ ] Add durable retry policy with deterministic stage replay sequencing.
- [ ] Add dead-letter capture and replay path for non-recoverable failures.
- [ ] Add checkpoint state model and resume semantics for long-running stages.
- [ ] Add rollback workflow to last stable promoted model/artifact set on promotion failure/regression block.
- [ ] Add concurrency/backpressure policies for burst control and queue stability.
- [ ] Add SLA-aware execution states and escalation policy mapping.
- [ ] Expose additive orchestration resilience status in run summary/API detail payload.

**Validation checklist (section 6)**
- [ ] Unit: stage replay preserves idempotent outputs under retries.
- [ ] Integration: dead-letter routing and replay produce deterministic outcomes.
- [ ] Integration: checkpoint resume restores execution without duplicate side effects.
- [ ] Integration: rollback restores last stable promoted artifact/model set.
- [ ] Regression: existing lifecycle endpoints remain contract-compatible.

### 7. Frontend Enterprise UX Improvements

**Approved decisions**
- Frontend spec must be detailed in roadmap/tasks now (execution can remain phased).
- Internal observability data (Prometheus/Loki/Grafana-backed) is primary for operations/health/cost views.
- RBAC requires explicit Operator / Reviewer / Admin permission matrix.
- Delivery is phased: read-only ops -> review/governance workflows -> admin/cost/compliance controls.

**Implementation checklist**
- [ ] Define operations dashboard spec with:
  - run list filters, run drill-down, stage diagnostics, failure root-cause panes
- [ ] Define class-health and regression views:
  - side-by-side model/run comparison
  - per-class AP/precision/recall trend and delta panels
- [ ] Define label QA/review workflow surfaces:
  - pending queue, decision actions, audit-linked decision history
- [ ] Define governance visibility surfaces:
  - lineage explorer
  - license/compliance status panels
  - policy violation timeline
- [ ] Define usage/cost/system health panels using internal telemetry and alert state.
- [ ] Define iteration explainability panels from deterministic policy artifacts.
- [ ] Add explicit RBAC matrix:
  - Operator: run ops + monitoring read
  - Reviewer: label/review actions + related artifact access
  - Admin: policy/config/rollback/compliance management
- [ ] Add phased frontend delivery sequence:
  - Phase 1: read-only operations + health dashboards
  - Phase 2: review workflows + governance/audit views
  - Phase 3: admin controls + cost/compliance management

**Validation checklist (section 7)**
- [ ] UX acceptance: each role only sees allowed pages/actions per RBAC matrix.
- [ ] Integration: monitoring panels reflect internal metrics/logs consistently with backend artifacts.
- [ ] Integration: class-level drilldowns match evaluation/iteration report values.
- [ ] Regression: existing dashboard routes and run detail flow remain usable during phased rollout.

## Execution Note

We will execute this roadmap one section at a time (1 through 7). Before implementing each section, we will confirm design decisions together, then update this file with the approved decisions and completion status.
