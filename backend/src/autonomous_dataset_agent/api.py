from __future__ import annotations

import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .config import JobConfig, build_job_config
from .orchestrator import PipelineRunner
from .run_management import (
    JobManager,
    RunError,
    RunListResponse,
    RunResource,
    RunStore,
    RunnerFactory,
)
from .utils import read_json


class RunCreateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    classes: list[str] = Field(min_length=1)
    source_mode: Literal["manifest", "live"] | None = None
    output_root: str | None = None
    env_file: str | None = None


class ArtifactDescriptor(BaseModel):
    path: str
    api_url: str
    file_url: str | None = None
    exists: bool


class ArtifactsResponse(BaseModel):
    job_id: str
    status: Literal["completed"]
    artifact_paths: dict[str, str]
    artifacts: dict[str, ArtifactDescriptor]


class HealthResponse(BaseModel):
    status: Literal["ready", "draining"]
    accepting_runs: bool
    active_worker_count: int
    queued_run_count: int
    artifacts_root: str
    index_path: str


BuildJobConfigFn = Callable[[str, list[str], str | Path | None, str | Path | None, str | None], JobConfig]


def _default_artifacts_root() -> Path:
    return Path("backend/artifacts")


def _default_index_path(artifacts_root: Path) -> Path:
    return artifacts_root / "run_index.json"


def _default_cors_origins() -> list[str]:
    configured = os.getenv("API_ALLOW_ORIGINS")
    if configured:
        return [item.strip() for item in configured.split(",") if item.strip()]
    return [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]


def _error_payload(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=_error_payload(code, message))


def _run_root(record) -> Path:
    return Path(record.output_root) / record.job_id


def _resolve_safe_path(root: Path, requested_path: str) -> Path:
    resolved_root = root.resolve()
    resolved_path = (resolved_root / requested_path).resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError("Requested path escapes the run root.")
    return resolved_path


def _relative_path_within_root(root: Path, target_path: Path) -> str | None:
    try:
        return target_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _artifact_links(request: Request, record, artifact_paths: dict[str, str]) -> dict[str, ArtifactDescriptor]:
    run_root = _run_root(record)
    descriptors: dict[str, ArtifactDescriptor] = {}
    for artifact_name, raw_path in artifact_paths.items():
        artifact_path = Path(str(raw_path))
        candidate_path = artifact_path.resolve() if artifact_path.exists() else artifact_path
        relative_path = _relative_path_within_root(run_root, candidate_path)
        if relative_path is None and not artifact_path.is_absolute():
            try:
                rooted_candidate = _resolve_safe_path(run_root, artifact_path.as_posix())
                if rooted_candidate.exists():
                    relative_path = rooted_candidate.relative_to(run_root.resolve()).as_posix()
            except ValueError:
                relative_path = None
        file_url = None
        if relative_path is not None:
            file_url = str(request.url_for("get_run_file", job_id=record.job_id, file_path=relative_path))

        descriptors[str(artifact_name)] = ArtifactDescriptor(
            path=str(raw_path),
            api_url=str(request.url_for("get_run_artifact", job_id=record.job_id, artifact_name=str(artifact_name))),
            file_url=file_url,
            exists=artifact_path.exists(),
        )
    return descriptors


def _artifact_path(record, artifact_name: str) -> Path | None:
    summary = record.summary or {}
    artifact_paths = summary.get("artifact_paths")
    if not isinstance(artifact_paths, dict):
        return None
    raw_path = artifact_paths.get(artifact_name)
    if raw_path is None:
        return None
    artifact_path = Path(str(raw_path))
    run_root = _run_root(record)
    if artifact_path.exists():
        relative_path = _relative_path_within_root(run_root, artifact_path.resolve())
        if relative_path is not None:
            return _resolve_safe_path(run_root, relative_path)
    if not artifact_path.is_absolute():
        try:
            rooted_candidate = _resolve_safe_path(run_root, artifact_path.as_posix())
            if rooted_candidate.exists():
                return rooted_candidate
        except ValueError:
            pass
    try:
        relative_path = artifact_path.resolve().relative_to(run_root.resolve()).as_posix()
        return _resolve_safe_path(run_root, relative_path)
    except ValueError:
        return None


def create_app(
    *,
    artifacts_root: Path | None = None,
    index_path: Path | None = None,
    build_config_fn: BuildJobConfigFn = build_job_config,
    runner_factory: RunnerFactory = PipelineRunner,
    max_workers: int = 1,
    shutdown_grace_period_seconds: float = 2.0,
) -> FastAPI:
    resolved_artifacts_root = artifacts_root or _default_artifacts_root()
    resolved_index_path = index_path or _default_index_path(resolved_artifacts_root)
    store = RunStore(resolved_index_path)
    manager = JobManager(
        store=store,
        runner_factory=runner_factory,
        max_workers=max_workers,
        shutdown_grace_period_seconds=shutdown_grace_period_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        manager.start()
        try:
            yield
        finally:
            manager.stop()

    app = FastAPI(title="Autonomous Dataset Agent API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_default_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.run_store = store
    app.state.job_manager = manager
    app.state.artifacts_root = resolved_artifacts_root
    app.state.index_path = resolved_index_path

    @app.post("/runs", response_model=RunResource, status_code=202)
    def create_run(request: RunCreateRequest) -> RunResource | JSONResponse:
        classes = [item.strip() for item in request.classes if item.strip()]
        if not classes:
            return _error_response(400, "invalid_request", "At least one non-empty class is required.")

        config = build_config_fn(
            request.prompt,
            classes,
            request.output_root,
            request.env_file,
            request.source_mode,
        )
        try:
            return manager.enqueue(config)
        except RuntimeError as exc:
            return _error_response(503, "invalid_request", str(exc))

    @app.get("/runs", response_model=RunListResponse)
    def list_runs(limit: int = Query(default=10, ge=1, le=50)) -> RunListResponse:
        return RunListResponse(runs=store.list_resources(limit))

    @app.get("/runs/{job_id}", response_model=RunResource)
    def get_run(job_id: str) -> RunResource | JSONResponse:
        response = store.load_or_rehydrate(job_id, resolved_artifacts_root)
        if response is None:
            return _error_response(404, "run_not_found", f"Run '{job_id}' was not found.")
        return response

    @app.post("/runs/{job_id}/cancel", response_model=RunResource, status_code=202)
    def cancel_run(job_id: str) -> RunResource | JSONResponse:
        outcome, response = store.request_cancel(job_id)
        if outcome == "missing":
            return _error_response(404, "run_not_found", f"Run '{job_id}' was not found.")
        if outcome == "terminal":
            return _error_response(409, "invalid_request", f"Run '{job_id}' is already terminal.")
        assert response is not None
        return response

    @app.get("/health", response_model=HealthResponse)
    def get_health() -> HealthResponse:
        accepting_runs = manager.accepting_runs()
        return HealthResponse(
            status="ready" if accepting_runs else "draining",
            accepting_runs=accepting_runs,
            active_worker_count=manager.active_count(),
            queued_run_count=manager.queued_count(),
            artifacts_root=str(resolved_artifacts_root),
            index_path=str(resolved_index_path),
        )

    @app.get("/runs/{job_id}/artifacts", response_model=ArtifactsResponse)
    def get_run_artifacts(job_id: str, request: Request) -> ArtifactsResponse | JSONResponse:
        response = store.load_or_rehydrate(job_id, resolved_artifacts_root)
        if response is None:
            return _error_response(404, "run_not_found", f"Run '{job_id}' was not found.")
        if response.status != "completed":
            return _error_response(404, "artifacts_not_found", f"Artifacts for run '{job_id}' were not found.")

        record = store.get_record(job_id)
        if record is None:
            return _error_response(404, "run_not_found", f"Run '{job_id}' was not found.")

        summary = response.summary or {}
        artifact_paths = summary.get("artifact_paths")
        if not isinstance(artifact_paths, dict) or not artifact_paths:
            return _error_response(404, "artifacts_not_found", f"Artifacts for run '{job_id}' were not found.")

        return ArtifactsResponse(
            job_id=job_id,
            status="completed",
            artifact_paths={str(key): str(value) for key, value in artifact_paths.items()},
            artifacts=_artifact_links(request, record, artifact_paths),
        )

    @app.get("/runs/{job_id}/artifacts/{artifact_name}", name="get_run_artifact")
    def get_run_artifact(job_id: str, artifact_name: str) -> JSONResponse:
        response = store.load_or_rehydrate(job_id, resolved_artifacts_root)
        if response is None:
            return _error_response(404, "run_not_found", f"Run '{job_id}' was not found.")

        record = store.get_record(job_id)
        if record is None:
            return _error_response(404, "run_not_found", f"Run '{job_id}' was not found.")

        artifact_path = _artifact_path(record, artifact_name)
        if artifact_path is None or artifact_path.suffix.lower() != ".json":
            return _error_response(404, "artifacts_not_found", f"Artifact '{artifact_name}' was not found.")
        if not artifact_path.exists():
            return _error_response(404, "artifacts_not_found", f"Artifact '{artifact_name}' was not found.")

        payload = read_json(artifact_path)
        if not isinstance(payload, (dict, list)):
            return _error_response(404, "artifacts_not_found", f"Artifact '{artifact_name}' is not JSON content.")
        return JSONResponse(status_code=200, content=payload)

    @app.get("/runs/{job_id}/files/{file_path:path}", name="get_run_file")
    def get_run_file(job_id: str, file_path: str):
        record = store.get_record(job_id)
        if record is None:
            return _error_response(404, "run_not_found", f"Run '{job_id}' was not found.")

        run_root = _run_root(record)
        try:
            resolved_path = _resolve_safe_path(run_root, file_path)
        except ValueError:
            return _error_response(400, "invalid_request", "Requested file path is outside the run root.")

        if not resolved_path.exists() or not resolved_path.is_file():
            return _error_response(404, "artifacts_not_found", f"File '{file_path}' was not found.")
        return FileResponse(resolved_path)

    return app


app = create_app()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Autonomous Dataset Agent FastAPI server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run("autonomous_dataset_agent.api:app", host=args.host, port=args.port, reload=False)
    return 0
