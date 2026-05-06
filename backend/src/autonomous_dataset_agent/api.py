from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import build_job_config
from .orchestrator import PipelineRunner
from .utils import dataclass_to_dict, read_json


class RunCreateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    classes: list[str] = Field(min_length=1)
    source_mode: Literal["manifest", "live"] | None = None
    output_root: str | None = None
    env_file: str | None = None


class RunResponse(BaseModel):
    job_id: str
    status: Literal["running", "completed", "failed"]
    summary: dict[str, Any] | None = None
    error: str | None = None


class ArtifactsResponse(BaseModel):
    job_id: str
    status: Literal["completed"]
    artifact_paths: dict[str, str]


RUN_STORE: dict[str, RunResponse] = {}


def _default_artifacts_root() -> Path:
    return Path("backend/artifacts")


def _load_summary_from_disk(job_id: str) -> dict[str, Any] | None:
    summary_path = _default_artifacts_root() / job_id / "reports" / "run_summary.json"
    if not summary_path.exists():
        return None
    payload = read_json(summary_path)
    return payload if isinstance(payload, dict) else None


def create_app() -> FastAPI:
    app = FastAPI(title="Autonomous Dataset Agent API", version="0.1.0")

    @app.post("/runs", response_model=RunResponse)
    def create_run(request: RunCreateRequest) -> RunResponse:
        classes = [item.strip() for item in request.classes if item.strip()]
        if not classes:
            raise HTTPException(status_code=400, detail="At least one non-empty class is required.")

        config = build_job_config(
            prompt=request.prompt,
            classes=classes,
            output_root=request.output_root,
            env_file=request.env_file,
            source_mode=request.source_mode,
        )
        RUN_STORE[config.job_id] = RunResponse(job_id=config.job_id, status="running")

        try:
            summary = PipelineRunner(config).run()
            response = RunResponse(
                job_id=config.job_id,
                status="completed",
                summary=dataclass_to_dict(summary),
            )
            RUN_STORE[config.job_id] = response
            return response
        except Exception as exc:
            failed = RunResponse(
                job_id=config.job_id,
                status="failed",
                error=str(exc),
            )
            RUN_STORE[config.job_id] = failed
            raise HTTPException(
                status_code=500,
                detail={"job_id": config.job_id, "error": str(exc)},
            ) from exc

    @app.get("/runs/{job_id}", response_model=RunResponse)
    def get_run(job_id: str) -> RunResponse:
        if job_id in RUN_STORE:
            return RUN_STORE[job_id]

        summary = _load_summary_from_disk(job_id)
        if summary is None:
            raise HTTPException(status_code=404, detail=f"Run '{job_id}' was not found.")

        response = RunResponse(job_id=job_id, status="completed", summary=summary)
        RUN_STORE[job_id] = response
        return response

    @app.get("/runs/{job_id}/artifacts", response_model=ArtifactsResponse)
    def get_run_artifacts(job_id: str) -> ArtifactsResponse:
        if job_id in RUN_STORE and RUN_STORE[job_id].summary:
            summary = RUN_STORE[job_id].summary
        else:
            summary = _load_summary_from_disk(job_id)

        if summary is None:
            raise HTTPException(status_code=404, detail=f"Run '{job_id}' was not found.")

        artifact_paths = summary.get("artifact_paths")
        if not isinstance(artifact_paths, dict):
            raise HTTPException(status_code=404, detail=f"Artifacts for run '{job_id}' were not found.")

        return ArtifactsResponse(
            job_id=job_id,
            status="completed",
            artifact_paths={str(key): str(value) for key, value in artifact_paths.items()},
        )

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
