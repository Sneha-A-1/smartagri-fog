from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from smartagri_core import get_registry
from smartagri_core.registry import PluginNotFoundError
from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.config import Settings, get_settings
from smartagri_api.db import get_session
from smartagri_api.deps import audit, require
from smartagri_api.jobs.runner import FINAL_STATES, JobRunner, job_to_dict
from smartagri_api.models import Job, Project, User
from smartagri_api.schemas import JobCreate, JobOut

router = APIRouter(tags=["jobs"])


def get_runner(request: Request) -> JobRunner:
    return request.app.state.job_runner


@router.post("/jobs", response_model=JobOut, status_code=201)
def create_job(
    body: JobCreate,
    session: Session = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
    user: User = Depends(require("job:run")),
) -> dict[str, Any]:
    try:
        spec = get_registry().get(body.plugin_id)
    except PluginNotFoundError as exc:
        raise HTTPException(404, str(exc)) from None
    if not spec.runnable:
        raise HTTPException(
            409,
            f"{spec.name} is '{spec.status}' and cannot be run"
            + (f" (scheduled for Phase {spec.phase})" if spec.phase is not None else ""),
        )
    try:
        params = spec.validate_params(body.params).model_dump(mode="json")
    except ValidationError as exc:
        raise HTTPException(422, [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]) from None
    if body.project_id and session.get(Project, body.project_id) is None:
        raise HTTPException(404, "Project not found")

    job = Job(
        plugin_id=spec.id,
        params=params,
        project_id=body.project_id,
        created_by=user.id,
        message="Waiting for a free worker",
    )
    session.add(job)
    session.flush()
    audit(session, user, "job.create", "job", job.id, plugin_id=spec.id)
    session.commit()
    runner.submit(job.id, spec.id, params)
    return job_to_dict(job)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    limit: int = 50, session: Session = Depends(get_session), _: User = Depends(require("job:read"))
) -> list[dict[str, Any]]:
    jobs = session.scalars(select(Job).order_by(Job.created_at.desc()).limit(min(limit, 500)))
    return [job_to_dict(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: str, session: Session = Depends(get_session), _: User = Depends(require("job:read"))
) -> dict[str, Any]:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job_to_dict(job)


@router.get("/jobs/{job_id}/result")
def get_job_result(
    job_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require("job:read")),
) -> Any:
    job = session.get(Job, job_id)
    if job is None or job.result_path is None:
        raise HTTPException(404, "No result for this job")
    path = Path(job.result_path).resolve()
    if not path.is_relative_to(settings.resolved_results_dir) or not path.exists():
        raise HTTPException(404, "Result file is missing (was the results folder moved?)")
    return json.loads(path.read_text(encoding="utf-8"))


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(
    job_id: str,
    session: Session = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
    user: User = Depends(require("job:run")),
) -> dict[str, Any]:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status in FINAL_STATES:
        raise HTTPException(409, f"Job already {job.status}")
    runner.cancel(job_id)
    audit(session, user, "job.cancel", "job", job_id)
    session.commit()
    return job_to_dict(job)


@router.websocket("/ws/jobs")
async def jobs_ws(websocket: WebSocket) -> None:
    """Live job events: ``job.progress`` and ``job.finished`` messages as JSON."""
    await websocket.accept()
    hub = websocket.app.state.job_hub
    q = hub.subscribe()
    try:
        while True:
            await websocket.send_json(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(q)
