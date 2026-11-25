"""Experiments: saved, reproducible definitions that run as jobs and export results for papers."""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError
from smartagri_core import get_registry
from smartagri_core.experiment import AlgorithmSpec, ExperimentSpec, latex_tables, runs_to_csv
from smartagri_core.registry import PluginKind
from smartagri_core.sim.metrics import HEADLINE_METRICS, METRIC_INFO
from smartagri_core.sim.runner import ScenarioParams
from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.config import Settings, get_settings
from smartagri_api.db import get_session
from smartagri_api.deps import audit, require
from smartagri_api.jobs.runner import FINAL_STATES, JobRunner
from smartagri_api.models import Experiment, Job, Project, User
from smartagri_api.routers.jobs import get_runner, read_result
from smartagri_api.schemas import ExperimentCreate, ExperimentOut, ExperimentSchemaOut, ExperimentUpdate

router = APIRouter(tags=["experiments"])
RUNNER_PLUGIN = "simulation:experiment"


def _validate(raw: dict[str, Any]) -> ExperimentSpec:
    try:
        return ExperimentSpec.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(422, [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]) from None


def _out(exp: Experiment, session: Session) -> dict[str, Any]:
    job = session.get(Job, exp.job_id) if exp.job_id else None
    spec = ExperimentSpec.model_validate(exp.spec)
    return {
        "id": exp.id,
        "name": exp.name,
        "description": exp.description,
        "objective": exp.objective,
        "project_id": exp.project_id,
        "spec": exp.spec,
        "spec_sha256": exp.spec_sha256,
        "algorithms": [a.display for a in spec.algorithms],
        "total_runs": spec.total_runs,
        "status": job.status if job else "draft",
        "progress": job.progress if job else 0.0,
        "message": (job.error or job.message) if job else "",
        "job_id": exp.job_id,
        "has_result": bool(job and job.result_path),
        "result_summary": job.result_summary if job else None,
        "created_at": exp.created_at.isoformat(),
        "updated_at": exp.updated_at.isoformat(),
    }


def _get(session: Session, exp_id: str) -> Experiment:
    exp = session.get(Experiment, exp_id)
    if exp is None:
        raise HTTPException(404, "Experiment not found")
    return exp


def _running(exp: Experiment, session: Session) -> bool:
    job = session.get(Job, exp.job_id) if exp.job_id else None
    return job is not None and job.status not in FINAL_STATES


@router.get("/experiments/schema", response_model=ExperimentSchemaOut)
def experiment_schema(_: User = Depends(require("plugin:read"))) -> dict[str, Any]:
    reg = get_registry()

    def entries(kind: PluginKind) -> list[dict[str, str]]:
        return [{"key": s.key, "name": s.name, "summary": s.summary} for s in reg.all(kind) if s.runnable]

    default = ExperimentSpec(
        algorithms=[
            AlgorithmSpec(placement="cloud_only", discipline="edf"),
            AlgorithmSpec(placement="edge_ward", discipline="edf"),
            AlgorithmSpec(placement="mct", discipline="edf"),
        ]
    )
    return {
        "scenario_schema": ScenarioParams.model_json_schema(),
        "default_spec": default.model_dump(mode="json"),
        "placements": entries(PluginKind.PLACEMENT),
        "disciplines": entries(PluginKind.QUEUE_DISCIPLINE),
        "metrics": {k: list(v) for k, v in METRIC_INFO.items()},
        "headline_metrics": HEADLINE_METRICS,
    }


@router.get("/experiments", response_model=list[ExperimentOut])
def list_experiments(
    project_id: str | None = None, session: Session = Depends(get_session), _: User = Depends(require("job:read"))
) -> list[dict[str, Any]]:
    q = select(Experiment).order_by(Experiment.created_at.desc())
    if project_id:
        q = q.where(Experiment.project_id == project_id)
    return [_out(e, session) for e in session.scalars(q)]


@router.post("/experiments", response_model=ExperimentOut, status_code=201)
def create_experiment(
    body: ExperimentCreate, session: Session = Depends(get_session), user: User = Depends(require("job:run"))
) -> dict[str, Any]:
    spec = _validate(body.spec)
    if body.project_id and session.get(Project, body.project_id) is None:
        raise HTTPException(404, "Project not found")
    exp = Experiment(
        name=spec.name,
        description=spec.description,
        objective=spec.objective,
        spec=spec.model_dump(mode="json"),
        spec_sha256=spec.sha256,
        project_id=body.project_id,
        created_by=user.id,
    )
    session.add(exp)
    session.flush()
    audit(session, user, "experiment.create", "experiment", exp.id, name=spec.name)
    session.commit()
    return _out(exp, session)


@router.get("/experiments/{exp_id}", response_model=ExperimentOut)
def get_experiment(
    exp_id: str, session: Session = Depends(get_session), _: User = Depends(require("job:read"))
) -> dict[str, Any]:
    return _out(_get(session, exp_id), session)


@router.put("/experiments/{exp_id}", response_model=ExperimentOut)
def update_experiment(
    exp_id: str,
    body: ExperimentUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(require("job:run")),
) -> dict[str, Any]:
    exp = _get(session, exp_id)
    if exp.job_id:
        raise HTTPException(
            409,
            "This experiment has been run, so its definition is frozen to keep results "
            "reproducible. Duplicate it to make changes.",
        )
    spec = _validate(body.spec)
    exp.spec, exp.spec_sha256 = spec.model_dump(mode="json"), spec.sha256
    exp.name, exp.description, exp.objective = spec.name, spec.description, spec.objective
    audit(session, user, "experiment.update", "experiment", exp.id)
    session.commit()
    return _out(exp, session)


@router.post("/experiments/{exp_id}/run", response_model=ExperimentOut)
def run_experiment(
    exp_id: str,
    session: Session = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
    user: User = Depends(require("job:run")),
) -> dict[str, Any]:
    exp = _get(session, exp_id)
    if _running(exp, session):
        raise HTTPException(409, "This experiment is already running")
    spec = _validate(exp.spec)
    job = Job(
        plugin_id=RUNNER_PLUGIN,
        params=spec.model_dump(mode="json"),
        project_id=exp.project_id,
        created_by=user.id,
        message="Waiting for a free worker",
    )
    session.add(job)
    session.flush()
    exp.job_id = job.id
    audit(session, user, "experiment.run", "experiment", exp.id, job_id=job.id)
    session.commit()
    runner.submit(job.id, RUNNER_PLUGIN, job.params)
    return _out(exp, session)


@router.post("/experiments/{exp_id}/cancel", response_model=ExperimentOut)
def cancel_experiment(
    exp_id: str,
    session: Session = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
    user: User = Depends(require("job:run")),
) -> dict[str, Any]:
    exp = _get(session, exp_id)
    if not _running(exp, session):
        raise HTTPException(409, "This experiment is not running")
    runner.cancel(exp.job_id)  # type: ignore[arg-type]
    audit(session, user, "experiment.cancel", "experiment", exp.id)
    session.commit()
    return _out(exp, session)


@router.post("/experiments/{exp_id}/duplicate", response_model=ExperimentOut, status_code=201)
def duplicate_experiment(
    exp_id: str, session: Session = Depends(get_session), user: User = Depends(require("job:run"))
) -> dict[str, Any]:
    src = _get(session, exp_id)
    raw = dict(src.spec)
    raw["name"] = f"Copy of {src.name}"[:200]
    spec = _validate(raw)
    exp = Experiment(
        name=spec.name,
        description=spec.description,
        objective=spec.objective,
        spec=spec.model_dump(mode="json"),
        spec_sha256=spec.sha256,
        project_id=src.project_id,
        created_by=user.id,
    )
    session.add(exp)
    session.flush()
    audit(session, user, "experiment.duplicate", "experiment", exp.id, source=src.id)
    session.commit()
    return _out(exp, session)


@router.delete("/experiments/{exp_id}", status_code=204)
def delete_experiment(
    exp_id: str, session: Session = Depends(get_session), user: User = Depends(require("job:run"))
) -> Response:
    exp = _get(session, exp_id)
    if _running(exp, session):
        raise HTTPException(409, "Cancel the experiment before deleting it")
    session.delete(exp)
    audit(session, user, "experiment.delete", "experiment", exp_id, name=exp.name)
    session.commit()
    return Response(status_code=204)


@router.get("/experiments/{exp_id}/result")
def experiment_result(
    exp_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require("job:read")),
) -> Any:
    exp = _get(session, exp_id)
    return read_result(session.get(Job, exp.job_id) if exp.job_id else None, settings)


EXPORTS = {
    "csv": ("text/csv", "runs.csv"),
    "tex": ("application/x-tex", "tables.tex"),
    "json": ("application/json", "result.json"),
    "yaml": ("application/x-yaml", "experiment.yaml"),
}


@router.get("/experiments/{exp_id}/export/{fmt}")
def export_experiment(
    exp_id: str,
    fmt: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require("job:read")),
) -> Response:
    if fmt not in EXPORTS:
        raise HTTPException(404, f"Unknown format; use one of {', '.join(EXPORTS)}")
    exp = _get(session, exp_id)
    media, filename = EXPORTS[fmt]
    slug = "".join(c if c.isalnum() else "-" for c in exp.name.lower()).strip("-")[:40] or "experiment"
    if fmt == "yaml":
        body = yaml.safe_dump(exp.spec, sort_keys=False, allow_unicode=True)
    else:
        result = read_result(session.get(Job, exp.job_id) if exp.job_id else None, settings)
        if fmt == "csv":
            body = runs_to_csv(result)
        elif fmt == "tex":
            body = latex_tables(result)
        else:
            import json

            body = json.dumps(result, ensure_ascii=False, indent=2)
    return Response(
        body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{slug}-{filename}"'}
    )
