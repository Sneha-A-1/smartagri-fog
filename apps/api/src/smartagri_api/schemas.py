"""Request and response models. Their descriptions appear in the API docs and the generated TS client."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Health(BaseModel):
    status: str
    version: str
    commit: str = Field("unknown", description="Git commit of the running server")
    core_version: str
    local_mode: bool
    database: str


class SystemInfo(BaseModel):
    version: str
    core_version: str
    python: str
    local_mode: bool
    data_dir: str
    results_dir: str
    job_workers: int
    plugin_counts: dict[str, int] = Field(description="Number of catalogue entries per capability status")
    plugin_load_errors: list[str]


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    locale: str
    roles: list[str]
    permissions: list[str]
    local_mode: bool


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    roles: list[str] = Field(default_factory=lambda: ["researcher"])


class PluginSummary(BaseModel):
    id: str
    kind: str
    key: str
    name: str
    version: str
    status: str
    runnable: bool
    summary: str
    description: str
    layers: list[str]
    agri_applications: list[str]
    inputs: list[str]
    outputs: list[str]
    metrics: list[str]
    references: list[str]
    phase: int | None
    source: str
    tags: list[str]


class PluginDetail(PluginSummary):
    params_schema: dict[str, Any]
    default_params: dict[str, Any]


class ParamsIn(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class ParamsValidated(BaseModel):
    valid: bool
    params: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)


class JobCreate(BaseModel):
    plugin_id: str = Field(examples=["data_generator:soil_moisture_demo"])
    params: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None


class JobOut(BaseModel):
    id: str
    kind: str
    plugin_id: str
    params: dict[str, Any]
    status: str = Field(description="queued | running | succeeded | failed | cancelled | interrupted")
    progress: float
    message: str
    error: str | None
    data_origin: str | None
    result_summary: dict[str, Any] | None
    has_result: bool
    project_id: str | None
    created_at: str | None
    started_at: str | None
    finished_at: str | None


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    default_seed: int = Field(42, ge=0)


class ProjectPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    default_seed: int | None = Field(None, ge=0)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str
    default_seed: int
    created_at: datetime
    updated_at: datetime


class UserSettings(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict, description="Free-form per-user preferences")


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    at: datetime
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    details: dict[str, Any]


class ExperimentCreate(BaseModel):
    spec: dict[str, Any] = Field(description="An ExperimentSpec (see /api/experiments/schema)")
    project_id: str | None = None


class ExperimentUpdate(BaseModel):
    spec: dict[str, Any]


class ExperimentOut(BaseModel):
    id: str
    name: str
    description: str
    objective: str
    project_id: str | None
    spec: dict[str, Any]
    spec_sha256: str
    algorithms: list[str]
    total_runs: int
    status: str = Field(description="draft | queued | running | succeeded | failed | cancelled | interrupted")
    progress: float
    message: str
    job_id: str | None
    has_result: bool
    result_summary: dict[str, Any] | None
    created_at: str
    updated_at: str


class PolicyOption(BaseModel):
    key: str
    name: str
    summary: str


class ExperimentSchemaOut(BaseModel):
    scenario_schema: dict[str, Any]
    default_spec: dict[str, Any]
    placements: list[PolicyOption]
    disciplines: list[PolicyOption]
    metrics: dict[str, list[Any]]
    headline_metrics: list[str]
