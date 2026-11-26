"""Designed topologies and workloads, and single simulations that use them."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError
from smartagri_core.sim.engine import SimSettings
from smartagri_core.sim.policies import DISCIPLINE_KEYS, PLACEMENT_KEYS
from smartagri_core.sim.topology import (
    DEVICE_PRESETS,
    LINK_KIND_PRESETS,
    FarmTopologyParams,
    Layer,
    Topology,
    farm_topology,
)
from smartagri_core.sim.workload import AGRI_TASK_CLASSES, TaskClass, WorkloadSpec, agri_workload
from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.db import get_session
from smartagri_api.deps import audit, require
from smartagri_api.jobs.runner import JobRunner, job_to_dict
from smartagri_api.models import Job, Project, SavedTopology, SavedWorkload, User
from smartagri_api.routers.jobs import get_runner
from smartagri_api.schemas import JobOut

router = APIRouter(tags=["designs"])

LAYER_Y = {"cloud": 60.0, "fog": 220.0, "edge": 380.0, "iot": 540.0}


def auto_layout(topo: Topology) -> dict[str, dict[str, float]]:
    """Rows by layer (cloud at the top, gateways at the bottom), nodes spread evenly in each row."""
    layout: dict[str, dict[str, float]] = {}
    widest = max((len(topo.by_layer(layer)) for layer in Layer), default=1)
    for layer in Layer:
        nodes = topo.by_layer(layer)
        offset = (widest - len(nodes)) * 140.0 / 2  # centre each row under the widest one
        for i, n in enumerate(nodes):
            layout[n.id] = {"x": 80.0 + offset + i * 140.0, "y": LAYER_Y[str(layer)]}
    return layout


def _validate_topology(raw: dict[str, Any]) -> tuple[Topology | None, list[str]]:
    try:
        topo = Topology.model_validate(raw)
    except ValidationError as exc:
        return None, [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}".lstrip(": ") for e in exc.errors()]
    return topo, topo.validation_report()


def _validate_workload(raw: dict[str, Any]) -> WorkloadSpec:
    try:
        return WorkloadSpec.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(422, [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]) from None


# --- schemas -------------------------------------------------------------------------------------


class TopologyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    topology: dict[str, Any]
    layout: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None


class TopologyCheck(BaseModel):
    topology: dict[str, Any]


class TopologyCheckOut(BaseModel):
    valid: bool
    problems: list[str]
    summary: dict[str, Any] | None


class TopologyListItem(BaseModel):
    id: str
    name: str
    description: str
    nodes: int
    links: int
    sha256: str
    project_id: str | None
    updated_at: str


class TopologyOut(TopologyListItem):
    topology: dict[str, Any]
    layout: dict[str, Any]
    summary: dict[str, Any]
    problems: list[str]


class GeneratedTopology(BaseModel):
    topology: dict[str, Any]
    layout: dict[str, Any]
    summary: dict[str, Any]


class DesignPresets(BaseModel):
    devices: dict[str, dict[str, float]]
    link_kinds: dict[str, dict[str, float]]
    generator_schema: dict[str, Any]


class WorkloadIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    spec: dict[str, Any]
    project_id: str | None = None


class WorkloadListItem(BaseModel):
    id: str
    name: str
    description: str
    classes: int
    duration_s: float
    intensity: float
    sha256: str
    project_id: str | None
    updated_at: str


class WorkloadOut(WorkloadListItem):
    spec: dict[str, Any]


class WorkloadTemplate(BaseModel):
    spec: dict[str, Any]
    task_class_schema: dict[str, Any]


class WorkloadPreviewIn(BaseModel):
    spec: dict[str, Any]
    topology: dict[str, Any] | None = None


class WorkloadPreviewOut(BaseModel):
    sources: int
    classes: list[dict[str, Any]]
    tasks_per_hour: float
    expected_tasks: float
    demand_mips: float
    capacity_mips: float | None
    load_ratio: float | None


class SimulationIn(BaseModel):
    topology_id: str
    workload_id: str
    placement: PLACEMENT_KEYS = "mct"
    discipline: DISCIPLINE_KEYS = "edf"
    seed: int = Field(1, ge=0)
    settings: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None


# --- helpers --------------------------------------------------------------------------------------


def _topo_item(row: SavedTopology) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "nodes": len(row.graph.get("nodes", [])),
        "links": len(row.graph.get("links", [])),
        "sha256": row.sha256,
        "project_id": row.project_id,
        "updated_at": row.updated_at.isoformat(),
    }


def _topo_out(row: SavedTopology) -> dict[str, Any]:
    topo, problems = _validate_topology(row.graph)
    return {
        **_topo_item(row),
        "topology": row.graph,
        "layout": row.layout,
        "summary": topo.summary() if topo else {},
        "problems": problems,
    }


def _wl_item(row: SavedWorkload) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "classes": len(row.spec.get("classes", [])),
        "duration_s": row.spec.get("duration_s", 0),
        "intensity": row.spec.get("intensity", 1),
        "sha256": row.sha256,
        "project_id": row.project_id,
        "updated_at": row.updated_at.isoformat(),
    }


def _check_project(session: Session, project_id: str | None) -> None:
    if project_id and session.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")


# --- topologies -----------------------------------------------------------------------------------


@router.get("/topologies/presets", response_model=DesignPresets)
def design_presets(_: User = Depends(require("plugin:read"))) -> dict[str, Any]:
    return {
        "devices": DEVICE_PRESETS,
        "link_kinds": LINK_KIND_PRESETS,
        "generator_schema": FarmTopologyParams.model_json_schema(),
    }


@router.post("/topologies/generate", response_model=GeneratedTopology)
def generate_topology(params: FarmTopologyParams, _: User = Depends(require("plugin:read"))) -> dict[str, Any]:
    topo = farm_topology(params)
    return {"topology": topo.model_dump(mode="json"), "layout": auto_layout(topo), "summary": topo.summary()}


@router.post("/topologies/validate", response_model=TopologyCheckOut)
def validate_topology(body: TopologyCheck, _: User = Depends(require("plugin:read"))) -> dict[str, Any]:
    topo, problems = _validate_topology(body.topology)
    return {
        "valid": topo is not None and not problems,
        "problems": problems,
        "summary": topo.summary() if topo else None,
    }


@router.get("/topologies", response_model=list[TopologyListItem])
def list_topologies(
    session: Session = Depends(get_session), _: User = Depends(require("plugin:read"))
) -> list[dict[str, Any]]:
    return [_topo_item(r) for r in session.scalars(select(SavedTopology).order_by(SavedTopology.updated_at.desc()))]


@router.post("/topologies", response_model=TopologyOut, status_code=201)
def create_topology(
    body: TopologyIn, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> dict[str, Any]:
    topo, _problems = _validate_topology(body.topology)
    if topo is None:
        raise HTTPException(422, "The topology is not well formed: " + "; ".join(_problems))
    _check_project(session, body.project_id)
    row = SavedTopology(
        name=body.name,
        description=body.description,
        graph=topo.model_dump(mode="json"),
        layout=body.layout,
        sha256=topo.sha256,
        project_id=body.project_id,
        created_by=user.id,
    )
    session.add(row)
    session.flush()
    audit(session, user, "topology.create", "topology", row.id, name=body.name)
    session.commit()
    return _topo_out(row)


@router.get("/topologies/{topo_id}", response_model=TopologyOut)
def get_topology(
    topo_id: str, session: Session = Depends(get_session), _: User = Depends(require("plugin:read"))
) -> dict[str, Any]:
    row = session.get(SavedTopology, topo_id)
    if row is None:
        raise HTTPException(404, "Topology not found")
    return _topo_out(row)


@router.put("/topologies/{topo_id}", response_model=TopologyOut)
def update_topology(
    topo_id: str,
    body: TopologyIn,
    session: Session = Depends(get_session),
    user: User = Depends(require("project:write")),
) -> dict[str, Any]:
    row = session.get(SavedTopology, topo_id)
    if row is None:
        raise HTTPException(404, "Topology not found")
    topo, problems = _validate_topology(body.topology)
    if topo is None:
        raise HTTPException(422, "The topology is not well formed: " + "; ".join(problems))
    row.name, row.description = body.name, body.description
    row.graph, row.layout, row.sha256 = topo.model_dump(mode="json"), body.layout, topo.sha256
    audit(session, user, "topology.update", "topology", row.id)
    session.commit()
    return _topo_out(row)


@router.post("/topologies/{topo_id}/duplicate", response_model=TopologyOut, status_code=201)
def duplicate_topology(
    topo_id: str, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> dict[str, Any]:
    src = session.get(SavedTopology, topo_id)
    if src is None:
        raise HTTPException(404, "Topology not found")
    row = SavedTopology(
        name=f"Copy of {src.name}"[:200],
        description=src.description,
        graph=src.graph,
        layout=src.layout,
        sha256=src.sha256,
        project_id=src.project_id,
        created_by=user.id,
    )
    session.add(row)
    session.flush()
    audit(session, user, "topology.duplicate", "topology", row.id, source=src.id)
    session.commit()
    return _topo_out(row)


@router.delete("/topologies/{topo_id}", status_code=204)
def delete_topology(
    topo_id: str, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> Response:
    row = session.get(SavedTopology, topo_id)
    if row is None:
        raise HTTPException(404, "Topology not found")
    session.delete(row)
    audit(session, user, "topology.delete", "topology", topo_id, name=row.name)
    session.commit()
    return Response(status_code=204)


# --- workloads ------------------------------------------------------------------------------------


@router.get("/workloads/template", response_model=WorkloadTemplate)
def workload_template(_: User = Depends(require("plugin:read"))) -> dict[str, Any]:
    return {"spec": agri_workload().model_dump(mode="json"), "task_class_schema": TaskClass.model_json_schema()}


@router.post("/workloads/preview", response_model=WorkloadPreviewOut)
def preview_workload(body: WorkloadPreviewIn, _: User = Depends(require("plugin:read"))) -> dict[str, Any]:
    """Expected load before running anything: arrivals and compute demand versus capacity."""
    spec = _validate_workload(body.spec)
    topo = None
    if body.topology is not None:
        topo, problems = _validate_topology(body.topology)
        if topo is None:
            raise HTTPException(422, "; ".join(problems))
    sources = len(spec.sources) if spec.sources else (len(topo.by_layer(Layer.IOT)) if topo else 1)
    classes = []
    total_rate = 0.0
    demand = 0.0
    for c in spec.classes:
        rate_h = c.rate_per_source_per_h * spec.intensity * sources
        total_rate += rate_h
        demand += rate_h / 3600.0 * c.length_mi
        classes.append(
            {
                "name": c.name,
                "priority": c.priority,
                "tasks_per_hour": rate_h,
                "demand_mips": rate_h / 3600.0 * c.length_mi,
            }
        )
    capacity = None
    if topo is not None:
        capacity = sum(n.cores * n.mips for n in topo.nodes if n.can_compute)
    return {
        "sources": sources,
        "classes": classes,
        "tasks_per_hour": total_rate,
        "expected_tasks": total_rate * spec.duration_s / 3600.0,
        "demand_mips": demand,
        "capacity_mips": capacity,
        "load_ratio": (demand / capacity) if capacity else None,
    }


@router.get("/workloads", response_model=list[WorkloadListItem])
def list_workloads(
    session: Session = Depends(get_session), _: User = Depends(require("plugin:read"))
) -> list[dict[str, Any]]:
    return [_wl_item(r) for r in session.scalars(select(SavedWorkload).order_by(SavedWorkload.updated_at.desc()))]


@router.post("/workloads", response_model=WorkloadOut, status_code=201)
def create_workload(
    body: WorkloadIn, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> dict[str, Any]:
    spec = _validate_workload({**body.spec, "name": body.name})
    _check_project(session, body.project_id)
    row = SavedWorkload(
        name=body.name,
        description=body.description,
        spec=spec.model_dump(mode="json"),
        sha256=_wl_sha(spec),
        project_id=body.project_id,
        created_by=user.id,
    )
    session.add(row)
    session.flush()
    audit(session, user, "workload.create", "workload", row.id, name=body.name)
    session.commit()
    return {**_wl_item(row), "spec": row.spec}


@router.get("/workloads/{wl_id}", response_model=WorkloadOut)
def get_workload(
    wl_id: str, session: Session = Depends(get_session), _: User = Depends(require("plugin:read"))
) -> dict[str, Any]:
    row = session.get(SavedWorkload, wl_id)
    if row is None:
        raise HTTPException(404, "Workload not found")
    return {**_wl_item(row), "spec": row.spec}


@router.put("/workloads/{wl_id}", response_model=WorkloadOut)
def update_workload(
    wl_id: str,
    body: WorkloadIn,
    session: Session = Depends(get_session),
    user: User = Depends(require("project:write")),
) -> dict[str, Any]:
    row = session.get(SavedWorkload, wl_id)
    if row is None:
        raise HTTPException(404, "Workload not found")
    spec = _validate_workload({**body.spec, "name": body.name})
    row.name, row.description, row.spec, row.sha256 = (
        body.name,
        body.description,
        spec.model_dump(mode="json"),
        _wl_sha(spec),
    )
    audit(session, user, "workload.update", "workload", row.id)
    session.commit()
    return {**_wl_item(row), "spec": row.spec}


@router.post("/workloads/{wl_id}/duplicate", response_model=WorkloadOut, status_code=201)
def duplicate_workload(
    wl_id: str, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> dict[str, Any]:
    src = session.get(SavedWorkload, wl_id)
    if src is None:
        raise HTTPException(404, "Workload not found")
    name = f"Copy of {src.name}"[:200]
    row = SavedWorkload(
        name=name,
        description=src.description,
        spec={**src.spec, "name": name},
        sha256=src.sha256,
        project_id=src.project_id,
        created_by=user.id,
    )
    session.add(row)
    session.flush()
    audit(session, user, "workload.duplicate", "workload", row.id, source=src.id)
    session.commit()
    return {**_wl_item(row), "spec": row.spec}


@router.delete("/workloads/{wl_id}", status_code=204)
def delete_workload(
    wl_id: str, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> Response:
    row = session.get(SavedWorkload, wl_id)
    if row is None:
        raise HTTPException(404, "Workload not found")
    session.delete(row)
    audit(session, user, "workload.delete", "workload", wl_id, name=row.name)
    session.commit()
    return Response(status_code=204)


def _wl_sha(spec: WorkloadSpec) -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps(spec.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


# --- simulations ----------------------------------------------------------------------------------


@router.post("/simulations", response_model=JobOut, status_code=201)
def start_simulation(
    body: SimulationIn,
    session: Session = Depends(get_session),
    runner: JobRunner = Depends(get_runner),
    user: User = Depends(require("job:run")),
) -> dict[str, Any]:
    trow = session.get(SavedTopology, body.topology_id)
    wrow = session.get(SavedWorkload, body.workload_id)
    if trow is None or wrow is None:
        raise HTTPException(404, "Topology or workload not found")
    topo, problems = _validate_topology(trow.graph)
    if topo is None or problems:
        raise HTTPException(422, "The topology can't be simulated: " + "; ".join(problems))
    try:
        settings = SimSettings.model_validate(body.settings)
    except ValidationError as exc:
        raise HTTPException(422, [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]) from None
    params = {
        "topology": trow.graph,
        "workload": wrow.spec,
        "placement": body.placement,
        "discipline": body.discipline,
        "seed": body.seed,
        "settings": settings.model_dump(mode="json"),
        "topology_name": trow.name,
        "workload_name": wrow.name,
    }
    job = Job(
        plugin_id="simulation:custom_run",
        params=params,
        project_id=body.project_id,
        created_by=user.id,
        message="Waiting for a free worker",
    )
    session.add(job)
    session.flush()
    audit(session, user, "simulation.start", "job", job.id, topology=trow.id, workload=wrow.id)
    session.commit()
    runner.submit(job.id, "simulation:custom_run", params)
    return job_to_dict(job)


__all__ = ["router", "AGRI_TASK_CLASSES"]
