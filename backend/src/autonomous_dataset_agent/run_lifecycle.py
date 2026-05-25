from __future__ import annotations

import time
from typing import Callable, Literal


StageName = Literal[
    "bootstrap",
    "class_planning",
    "source_resolution",
    "frame_extraction",
    "critic",
    "labeling",
    "dataset_build",
    "training",
    "evaluation",
    "iteration",
    "finalize",
]

StageStatus = Literal["pending", "running", "completed", "failed", "skipped"]

PIPELINE_STAGES: tuple[StageName, ...] = (
    "bootstrap",
    "class_planning",
    "source_resolution",
    "frame_extraction",
    "critic",
    "labeling",
    "dataset_build",
    "training",
    "evaluation",
    "iteration",
    "finalize",
)


class RunAbortedError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


AbortCheck = Callable[[], RunAbortedError | None]
StageUpdate = Callable[[StageName, StageStatus], None]


class PipelineRunContext:
    def __init__(
        self,
        *,
        abort_check: AbortCheck | None = None,
        stage_update: StageUpdate | None = None,
    ) -> None:
        self._abort_check = abort_check
        self._stage_update = stage_update
        self._stage_started_at: dict[StageName, float] = {}
        self._stage_attempts: dict[StageName, int] = {}
        self._stage_telemetry: list[dict[str, object]] = []

    def checkpoint(self) -> None:
        if self._abort_check is None:
            return
        abort_error = self._abort_check()
        if abort_error is not None:
            raise abort_error

    def start_stage(self, stage_name: StageName) -> None:
        self.checkpoint()
        self._stage_attempts[stage_name] = self._stage_attempts.get(stage_name, 0) + 1
        self._stage_started_at[stage_name] = time.monotonic()
        if self._stage_update is not None:
            self._stage_update(stage_name, "running")

    def complete_stage(self, stage_name: StageName) -> None:
        self._record_stage_telemetry(stage_name, "completed")
        if self._stage_update is not None:
            self._stage_update(stage_name, "completed")

    def fail_stage(self, stage_name: StageName) -> None:
        self._record_stage_telemetry(stage_name, "failed")
        if self._stage_update is not None:
            self._stage_update(stage_name, "failed")

    def skip_stage(self, stage_name: StageName) -> None:
        self._record_stage_telemetry(stage_name, "skipped")
        if self._stage_update is not None:
            self._stage_update(stage_name, "skipped")

    def stage_telemetry(self) -> list[dict[str, object]]:
        return [dict(item) for item in self._stage_telemetry]

    def _record_stage_telemetry(self, stage_name: StageName, status: StageStatus) -> None:
        started_at = self._stage_started_at.pop(stage_name, None)
        duration_ms = 0
        if started_at is not None:
            duration_ms = max(0, int((time.monotonic() - started_at) * 1000))
        attempts = self._stage_attempts.get(stage_name, 1)
        self._stage_telemetry.append(
            {
                "stage": stage_name,
                "status": status,
                "attempt": attempts,
                "duration_ms": duration_ms,
            }
        )
