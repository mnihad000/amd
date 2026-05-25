from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from threading import Event, RLock, Thread
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from .config import JobConfig
from .run_lifecycle import PIPELINE_STAGES, PipelineRunContext, RunAbortedError, StageName, StageStatus
from .utils import dataclass_to_dict, read_json, write_json


RunStatus = Literal["queued", "running", "completed", "failed"]


class RunError(BaseModel):
    code: str
    message: str


class StageRecord(BaseModel):
    name: StageName
    status: StageStatus = "pending"
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None


class RunProgress(BaseModel):
    total_stages: int
    completed_stages: int
    skipped_stages: int
    failed_stages: int
    percent: float


class RunResource(BaseModel):
    job_id: str
    status: RunStatus
    prompt: str
    classes: list[str]
    source_mode: Literal["manifest", "live"]
    current_stage: StageName | None = None
    cancel_requested: bool = False
    created_at: str
    updated_at: str
    error: RunError | None = None
    summary: dict[str, Any] | None = None
    iteration_policy: dict[str, Any] | None = None
    baseline_comparison: dict[str, Any] | None = None
    promotion_guard: dict[str, Any] | None = None
    runtime_profile: dict[str, Any] | None = None
    promotion_gate: dict[str, Any] | None = None
    benchmark_summary: dict[str, Any] | None = None
    benchmark_regression: dict[str, Any] | None = None
    advanced_validation: dict[str, Any] | None = None
    governance_summary: dict[str, Any] | None = None
    lineage_summary: dict[str, Any] | None = None
    license_compliance: dict[str, Any] | None = None
    version_summary: dict[str, Any] | None = None
    artifact_lifecycle: dict[str, Any] | None = None
    monitoring_summary: dict[str, Any] | None = None
    orchestration_resilience: dict[str, Any] | None = None
    stage_history: list[StageRecord] = Field(default_factory=list)
    progress: RunProgress


class RunListResponse(BaseModel):
    runs: list[RunResource]


class PersistedRunRecord(BaseModel):
    job_id: str
    status: RunStatus
    output_root: str
    prompt: str
    classes: list[str]
    source_mode: Literal["manifest", "live"]
    current_stage: StageName | None = None
    cancel_requested: bool = False
    created_at: str
    updated_at: str
    summary_path: str | None = None
    summary: dict[str, Any] | None = None
    error: RunError | None = None
    stage_history: list[StageRecord] = Field(default_factory=list)


RunnerFactory = Callable[[JobConfig], Any]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _duration_ms(started_at: str | None, completed_at: datetime) -> int:
    if not started_at:
        return 0
    started = datetime.fromisoformat(started_at)
    return max(0, int((completed_at - started).total_seconds() * 1000))


def _default_stage_history() -> list[StageRecord]:
    return [StageRecord(name=stage_name) for stage_name in PIPELINE_STAGES]


def _clone_stage_history(stage_history: list[StageRecord] | None) -> list[StageRecord]:
    if not stage_history:
        return _default_stage_history()
    return [item.model_copy(deep=True) for item in stage_history]


def _with_all_stages(stage_history: list[StageRecord]) -> list[StageRecord]:
    by_name = {item.name: item for item in stage_history}
    return [by_name.get(stage_name, StageRecord(name=stage_name)) for stage_name in PIPELINE_STAGES]


class RunStore:
    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path
        self._lock = RLock()
        self._records: dict[str, PersistedRunRecord] = {}
        self._load()
        self.mark_incomplete_runs_failed()

    def allocate_job_id(self, desired_job_id: str, output_root: Path) -> str:
        with self._lock:
            candidate = desired_job_id
            if self._job_id_available(candidate, output_root):
                return candidate

            suffix = _utc_now().strftime("%Y%m%d%H%M%S")
            candidate = f"{desired_job_id}-{suffix}"
            counter = 2
            while not self._job_id_available(candidate, output_root):
                candidate = f"{desired_job_id}-{suffix}-{counter}"
                counter += 1
            return candidate

    def create_queued(self, config: JobConfig) -> RunResource:
        with self._lock:
            now = _utc_now_iso()
            record = PersistedRunRecord(
                job_id=config.job_id,
                status="queued",
                output_root=str(config.output_root),
                prompt=config.prompt,
                classes=list(config.classes),
                source_mode=config.source.source_mode,
                created_at=now,
                updated_at=now,
                summary_path=str(self._summary_path(config.output_root, config.job_id)),
                stage_history=_default_stage_history(),
            )
            self._records[config.job_id] = record
            self._save_locked()
            return self._to_resource_locked(record)

    def mark_run_started(self, job_id: str) -> RunResource | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            if record.status != "queued":
                return self._to_resource_locked(record)
            now = _utc_now_iso()
            record.status = "running"
            record.updated_at = now
            record.error = None
            self._save_locked()
            return self._to_resource_locked(record)

    def update_stage(self, job_id: str, stage_name: StageName, status: StageStatus) -> RunResource | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None or record.status in {"completed", "failed"}:
                return self._to_resource_locked(record) if record is not None else None

            stage = self._stage_record_locked(record, stage_name)
            now = _utc_now()
            now_iso = now.isoformat()

            if status == "running":
                stage.status = "running"
                stage.started_at = stage.started_at or now_iso
                stage.completed_at = None
                stage.duration_ms = None
                record.current_stage = stage_name
            elif status == "completed":
                stage.status = "completed"
                stage.completed_at = now_iso
                stage.duration_ms = _duration_ms(stage.started_at, now)
                record.current_stage = stage_name
            elif status == "failed":
                stage.status = "failed"
                stage.started_at = stage.started_at or now_iso
                stage.completed_at = now_iso
                stage.duration_ms = _duration_ms(stage.started_at, now)
                record.current_stage = stage_name
            else:
                stage.status = "skipped"
                stage.completed_at = now_iso
                stage.duration_ms = 0

            record.updated_at = now_iso
            self._save_locked()
            return self._to_resource_locked(record)

    def complete_run(self, job_id: str, summary: dict[str, Any]) -> RunResource | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            if record.status == "failed":
                return self._to_resource_locked(record)

            raw_summary_path = summary.get("artifact_paths", {}).get("run_summary")
            resolved_summary_path = (
                Path(str(raw_summary_path))
                if raw_summary_path
                else self._summary_path(Path(record.output_root), record.job_id)
            )
            now = _utc_now_iso()
            record.status = "completed"
            record.updated_at = now
            record.summary_path = str(resolved_summary_path)
            record.summary = summary
            record.error = None
            record.current_stage = "finalize"
            self._save_locked()
            return self._to_resource_locked(record)

    def fail_run(self, job_id: str, error: RunError) -> RunResource | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            if record.status == "completed":
                return self._to_resource_locked(record)

            now = _utc_now()
            now_iso = now.isoformat()
            running_stage = self._running_stage_locked(record)
            if running_stage is not None:
                running_stage.status = "failed"
                running_stage.started_at = running_stage.started_at or now_iso
                running_stage.completed_at = now_iso
                running_stage.duration_ms = _duration_ms(running_stage.started_at, now)
                record.current_stage = running_stage.name

            self._skip_pending_stages_locked(record, now_iso)
            record.status = "failed"
            record.updated_at = now_iso
            record.error = error
            self._save_locked()
            return self._to_resource_locked(record)

    def request_cancel(self, job_id: str) -> tuple[Literal["accepted", "terminal", "missing"], RunResource | None]:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return "missing", None
            if record.status in {"completed", "failed"}:
                return "terminal", self._to_resource_locked(record)

            record.cancel_requested = True
            record.updated_at = _utc_now_iso()
            if record.status == "queued":
                error = RunError(code="run_cancelled", message="Run was cancelled before execution started.")
                failed = self.fail_run(job_id, error)
                return "accepted", failed

            self._save_locked()
            return "accepted", self._to_resource_locked(record)

    def mark_timeout_requested(self, job_id: str) -> None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None or record.status in {"completed", "failed"}:
                return
            record.cancel_requested = True
            record.updated_at = _utc_now_iso()
            self._save_locked()

    def interrupt_running_and_queued(self) -> None:
        with self._lock:
            for job_id in list(self._records):
                record = self._records[job_id]
                if record.status not in {"queued", "running"}:
                    continue
                record.cancel_requested = True
                error = RunError(
                    code="run_interrupted",
                    message="Run was interrupted by process shutdown or restart.",
                )
                self.fail_run(job_id, error)

    def mark_incomplete_runs_failed(self) -> None:
        self.interrupt_running_and_queued()

    def current_abort_error(self, job_id: str) -> RunAbortedError | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return RunAbortedError("run_interrupted", "Run state is no longer available.")
            if record.status == "failed" and record.error is not None:
                return RunAbortedError(record.error.code, record.error.message)
            if record.cancel_requested:
                return RunAbortedError("run_cancelled", "Run cancellation was requested.")
            return None

    def is_terminal(self, job_id: str) -> bool:
        with self._lock:
            record = self._records.get(job_id)
            return record is not None and record.status in {"completed", "failed"}

    def get_resource(self, job_id: str) -> RunResource | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            return self._to_resource_locked(record)

    def get_record(self, job_id: str) -> PersistedRunRecord | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            return record.model_copy(deep=True)

    def update_summary(self, job_id: str, summary: dict[str, Any]) -> RunResource | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            record.summary = summary
            summary_path = summary.get("artifact_paths", {}).get("run_summary")
            if summary_path:
                record.summary_path = str(summary_path)
            record.updated_at = _utc_now_iso()
            self._save_locked()
            return self._to_resource_locked(record)

    def list_resources(self, limit: int) -> list[RunResource]:
        with self._lock:
            ordered = sorted(
                self._records.values(),
                key=lambda item: item.updated_at,
                reverse=True,
            )
            return [self._to_resource_locked(record) for record in ordered[:limit]]

    def load_or_rehydrate(self, job_id: str, artifacts_root: Path) -> RunResource | None:
        with self._lock:
            record = self._records.get(job_id)
            if record is not None:
                return self._to_resource_locked(record)

        summary_path = self._summary_path(artifacts_root, job_id)
        if not summary_path.exists():
            return None

        summary = read_json(summary_path)
        if not isinstance(summary, dict):
            return None

        prompt = str(summary.get("prompt", job_id))
        requested_classes = summary.get("requested_classes")
        classes = [str(item) for item in requested_classes] if isinstance(requested_classes, list) else []
        completed_at = _utc_now_iso()
        record = PersistedRunRecord(
            job_id=job_id,
            status="completed",
            output_root=str(artifacts_root),
            prompt=prompt,
            classes=classes,
            source_mode="manifest",
            current_stage="finalize",
            created_at=completed_at,
            updated_at=completed_at,
            summary_path=str(summary_path),
            summary=summary,
            stage_history=[
                StageRecord(
                    name=stage_name,
                    status="completed",
                    started_at=completed_at,
                    completed_at=completed_at,
                    duration_ms=0,
                )
                for stage_name in PIPELINE_STAGES
            ],
        )
        with self._lock:
            self._records[job_id] = record
            self._save_locked()
            return self._to_resource_locked(record)

    def _job_id_available(self, job_id: str, output_root: Path) -> bool:
        return job_id not in self._records and not (output_root / job_id).exists()

    def _load(self) -> None:
        if not self.index_path.exists():
            return

        payload = read_json(self.index_path)
        records = payload.get("runs", {}) if isinstance(payload, dict) else {}
        if not isinstance(records, dict):
            return

        for job_id, raw_record in records.items():
            if not isinstance(raw_record, dict):
                continue
            normalized = self._normalize_loaded_record(job_id, raw_record)
            if normalized is not None:
                self._records[job_id] = normalized

    def _normalize_loaded_record(self, job_id: str, raw_record: dict[str, Any]) -> PersistedRunRecord | None:
        summary = raw_record.get("summary")
        summary_dict = summary if isinstance(summary, dict) else None
        output_root = str(raw_record.get("output_root", "backend/artifacts"))
        prompt = str(raw_record.get("prompt") or (summary_dict.get("prompt") if summary_dict else job_id))
        classes_value = raw_record.get("classes")
        if isinstance(classes_value, list):
            classes = [str(item) for item in classes_value]
        else:
            requested_classes = summary_dict.get("requested_classes") if summary_dict else None
            classes = [str(item) for item in requested_classes] if isinstance(requested_classes, list) else []

        source_mode = str(raw_record.get("source_mode", "manifest")).lower()
        if source_mode not in {"manifest", "live"}:
            source_mode = "manifest"

        stage_history_value = raw_record.get("stage_history")
        stage_history: list[StageRecord]
        if isinstance(stage_history_value, list):
            parsed_history: list[StageRecord] = []
            for item in stage_history_value:
                if isinstance(item, dict):
                    parsed_history.append(StageRecord.model_validate(item))
            stage_history = _with_all_stages(parsed_history or _default_stage_history())
        else:
            stage_history = _default_stage_history()

        created_at = str(raw_record.get("created_at") or _utc_now_iso())
        updated_at = str(raw_record.get("updated_at") or created_at)
        status = str(raw_record.get("status", "failed")).lower()
        if status not in {"queued", "running", "completed", "failed"}:
            status = "failed"

        if status == "completed" and not raw_record.get("stage_history"):
            stage_history = [
                StageRecord(
                    name=stage_name,
                    status="completed",
                    started_at=created_at,
                    completed_at=updated_at,
                    duration_ms=0,
                )
                for stage_name in PIPELINE_STAGES
            ]

        summary_path = raw_record.get("summary_path")
        if not summary_path and summary_dict:
            summary_path = summary_dict.get("artifact_paths", {}).get("run_summary")

        current_stage = raw_record.get("current_stage")
        if current_stage not in PIPELINE_STAGES:
            current_stage = None

        try:
            return PersistedRunRecord(
                job_id=str(raw_record.get("job_id", job_id)),
                status=status,
                output_root=output_root,
                prompt=prompt,
                classes=classes,
                source_mode=source_mode,
                current_stage=current_stage,
                cancel_requested=bool(raw_record.get("cancel_requested", False)),
                created_at=created_at,
                updated_at=updated_at,
                summary_path=str(summary_path) if summary_path else str(self._summary_path(Path(output_root), job_id)),
                summary=summary_dict,
                error=RunError.model_validate(raw_record["error"]) if isinstance(raw_record.get("error"), dict) else None,
                stage_history=stage_history,
            )
        except Exception:
            return None

    def _save_locked(self) -> None:
        payload = {
            "runs": {
                job_id: record.model_dump(mode="json")
                for job_id, record in sorted(self._records.items())
            }
        }
        write_json(self.index_path, payload)

    def _to_resource_locked(self, record: PersistedRunRecord) -> RunResource:
        summary = record.summary
        if summary is None and record.status == "completed" and record.summary_path:
            summary_path = Path(record.summary_path)
            if summary_path.exists():
                loaded_summary = read_json(summary_path)
                if isinstance(loaded_summary, dict):
                    record.summary = loaded_summary
                    summary = loaded_summary
                    self._save_locked()

        stage_history = _clone_stage_history(record.stage_history)
        completed_stages = sum(1 for item in stage_history if item.status == "completed")
        skipped_stages = sum(1 for item in stage_history if item.status == "skipped")
        failed_stages = sum(1 for item in stage_history if item.status == "failed")
        total_stages = len(stage_history)
        terminal_stages = completed_stages + skipped_stages + failed_stages

        return RunResource(
            job_id=record.job_id,
            status=record.status,
            prompt=record.prompt,
            classes=list(record.classes),
            source_mode=record.source_mode,
            current_stage=record.current_stage,
            cancel_requested=record.cancel_requested,
            created_at=record.created_at,
            updated_at=record.updated_at,
            error=record.error.model_copy(deep=True) if record.error is not None else None,
            summary=summary,
            iteration_policy=summary.get("iteration_policy") if isinstance(summary, dict) else None,
            baseline_comparison=summary.get("baseline_comparison_summary") if isinstance(summary, dict) else None,
            promotion_guard=summary.get("promotion_guard_summary") if isinstance(summary, dict) else None,
            runtime_profile=summary.get("runtime_profile") if isinstance(summary, dict) else None,
            promotion_gate=summary.get("promotion_gate_summary") if isinstance(summary, dict) else None,
            benchmark_summary=summary.get("benchmark_summary") if isinstance(summary, dict) else None,
            benchmark_regression=summary.get("benchmark_regression_summary") if isinstance(summary, dict) else None,
            advanced_validation=summary.get("advanced_validation_summary") if isinstance(summary, dict) else None,
            governance_summary=summary.get("governance_summary") if isinstance(summary, dict) else None,
            lineage_summary=summary.get("lineage_summary") if isinstance(summary, dict) else None,
            license_compliance=summary.get("license_compliance") if isinstance(summary, dict) else None,
            version_summary=summary.get("version_summary") if isinstance(summary, dict) else None,
            artifact_lifecycle=summary.get("artifact_lifecycle") if isinstance(summary, dict) else None,
            monitoring_summary=summary.get("monitoring_summary") if isinstance(summary, dict) else None,
            orchestration_resilience=summary.get("orchestration_resilience") if isinstance(summary, dict) else None,
            stage_history=stage_history,
            progress=RunProgress(
                total_stages=total_stages,
                completed_stages=completed_stages,
                skipped_stages=skipped_stages,
                failed_stages=failed_stages,
                percent=round((terminal_stages / total_stages) * 100, 1) if total_stages else 0.0,
            ),
        )

    def _stage_record_locked(self, record: PersistedRunRecord, stage_name: StageName) -> StageRecord:
        for item in record.stage_history:
            if item.name == stage_name:
                return item
        stage = StageRecord(name=stage_name)
        record.stage_history.append(stage)
        return stage

    def _running_stage_locked(self, record: PersistedRunRecord) -> StageRecord | None:
        for item in record.stage_history:
            if item.status == "running":
                return item
        return None

    def _skip_pending_stages_locked(self, record: PersistedRunRecord, completed_at: str) -> None:
        for item in record.stage_history:
            if item.status != "pending":
                continue
            item.status = "skipped"
            item.completed_at = completed_at
            item.duration_ms = 0

    @staticmethod
    def _summary_path(output_root: Path | str, job_id: str) -> Path:
        return Path(output_root) / job_id / "reports" / "run_summary.json"


class JobManager:
    def __init__(
        self,
        *,
        store: RunStore,
        runner_factory: RunnerFactory,
        max_workers: int = 1,
        max_queue_size: int = 100,
        shutdown_grace_period_seconds: float = 2.0,
    ) -> None:
        self.store = store
        self.runner_factory = runner_factory
        self.max_workers = max(1, max_workers)
        self.max_queue_size = max(1, max_queue_size)
        self.shutdown_grace_period_seconds = shutdown_grace_period_seconds
        self._queue: Queue[JobConfig | None] = Queue()
        self._queued_job_ids: set[str] = set()
        self._active_runs: dict[str, float] = {}
        self._state_lock = RLock()
        self._stop_event = Event()
        self._workers: list[Thread] = []
        self._accepting_runs = True

    def start(self) -> None:
        with self._state_lock:
            if self._workers:
                return
            self._stop_event.clear()
            for index in range(self.max_workers):
                worker = Thread(
                    target=self._worker_loop,
                    name=f"run-worker-{index + 1}",
                    daemon=True,
                )
                worker.start()
                self._workers.append(worker)

    def stop(self) -> None:
        with self._state_lock:
            self._accepting_runs = False

        self.store.interrupt_running_and_queued()

        deadline = time.monotonic() + self.shutdown_grace_period_seconds
        while time.monotonic() < deadline:
            with self._state_lock:
                if not self._active_runs:
                    break
            time.sleep(0.05)

        with self._state_lock:
            interrupted_job_ids = list(self._active_runs.keys())
        for job_id in interrupted_job_ids:
            self.store.fail_run(
                job_id,
                RunError(
                    code="run_interrupted",
                    message="Run was interrupted by process shutdown or restart.",
                ),
            )

        self._stop_event.set()
        worker_count = len(self._workers)
        for _ in range(worker_count):
            self._queue.put(None)
        for worker in self._workers:
            worker.join(timeout=self.shutdown_grace_period_seconds)
        with self._state_lock:
            self._workers.clear()
            self._queued_job_ids.clear()
            self._active_runs.clear()

    def enqueue(self, config: JobConfig) -> RunResource:
        with self._state_lock:
            if not self._accepting_runs:
                raise RuntimeError("Service is shutting down and cannot accept new runs.")
            if len(self._queued_job_ids) >= self.max_queue_size:
                raise RuntimeError("Run queue is at capacity; backpressure is rejecting new runs.")

        allocated_job_id = self.store.allocate_job_id(config.job_id, config.output_root)
        resolved_config = replace(config, job_id=allocated_job_id)
        response = self.store.create_queued(resolved_config)

        with self._state_lock:
            self._queued_job_ids.add(resolved_config.job_id)
        self._queue.put(resolved_config)
        return response

    def queued_count(self) -> int:
        with self._state_lock:
            return len(self._queued_job_ids)

    def active_count(self) -> int:
        with self._state_lock:
            return len(self._active_runs)

    def accepting_runs(self) -> bool:
        with self._state_lock:
            return self._accepting_runs

    def backpressure_state(self) -> dict[str, Any]:
        with self._state_lock:
            queued_count = len(self._queued_job_ids)
            return {
                "queue_limit": self.max_queue_size,
                "queued_count": queued_count,
                "active_count": len(self._active_runs),
                "backpressure_state": "rejecting" if queued_count >= self.max_queue_size else "accepting",
            }

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                config = self._queue.get(timeout=0.1)
            except Empty:
                continue

            if config is None:
                self._queue.task_done()
                break

            with self._state_lock:
                self._queued_job_ids.discard(config.job_id)

            try:
                self._execute(config)
            finally:
                self._queue.task_done()

    def _execute(self, config: JobConfig) -> None:
        if self.store.is_terminal(config.job_id):
            return

        started = self.store.mark_run_started(config.job_id)
        if started is None or started.status != "running":
            return

        started_at_monotonic = time.monotonic()
        with self._state_lock:
            self._active_runs[config.job_id] = started_at_monotonic

        run_context = PipelineRunContext(
            abort_check=lambda: self._abort_error(config.job_id, config.budgets.max_runtime_seconds, started_at_monotonic),
            stage_update=lambda stage_name, status: self.store.update_stage(config.job_id, stage_name, status),
        )

        try:
            runner = self.runner_factory(config)
            if hasattr(runner, "set_run_context"):
                runner.set_run_context(run_context)
            summary = dataclass_to_dict(runner.run())
        except RunAbortedError as exc:
            self.store.fail_run(config.job_id, RunError(code=exc.code, message=exc.message))
        except TimeoutError:
            self.store.fail_run(
                config.job_id,
                RunError(code="run_timed_out", message="Run exceeded the configured timeout budget."),
            )
        except Exception as exc:
            self.store.fail_run(
                config.job_id,
                RunError(code="run_failed", message=str(exc)),
            )
        else:
            self.store.complete_run(config.job_id, summary)
        finally:
            with self._state_lock:
                self._active_runs.pop(config.job_id, None)

    def _abort_error(
        self,
        job_id: str,
        max_runtime_seconds: int,
        started_at_monotonic: float,
    ) -> RunAbortedError | None:
        current_abort = self.store.current_abort_error(job_id)
        if current_abort is not None:
            return current_abort

        elapsed_seconds = time.monotonic() - started_at_monotonic
        if elapsed_seconds > max_runtime_seconds:
            self.store.mark_timeout_requested(job_id)
            return RunAbortedError("run_timed_out", "Run exceeded the configured timeout budget.")
        return None
