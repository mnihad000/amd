from __future__ import annotations

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

    def checkpoint(self) -> None:
        if self._abort_check is None:
            return
        abort_error = self._abort_check()
        if abort_error is not None:
            raise abort_error

    def start_stage(self, stage_name: StageName) -> None:
        self.checkpoint()
        if self._stage_update is not None:
            self._stage_update(stage_name, "running")

    def complete_stage(self, stage_name: StageName) -> None:
        if self._stage_update is not None:
            self._stage_update(stage_name, "completed")

    def fail_stage(self, stage_name: StageName) -> None:
        if self._stage_update is not None:
            self._stage_update(stage_name, "failed")

    def skip_stage(self, stage_name: StageName) -> None:
        if self._stage_update is not None:
            self._stage_update(stage_name, "skipped")
