"""Phase 0 database tables: identity and access, workspace projects, jobs, settings, audit log.

Later phases add their tables through additive Alembic migrations.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from smartagri_api.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(TimestampMixin, Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class Role(TimestampMixin, Base):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    permissions: Mapped[list[Permission]] = relationship(secondary=role_permissions, lazy="selectin")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    locale: Mapped[str] = mapped_column(String(16), default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")

    @property
    def permission_codes(self) -> set[str]:
        return {p.code for r in self.roles for p in r.permissions}


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    default_seed: Mapped[int] = mapped_column(default=42)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    kind: Mapped[str] = mapped_column(String(32), default="plugin_run")
    plugin_id: Mapped[str] = mapped_column(String(128))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(String(512), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_origin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    result_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SettingsProfile(TimestampMixin, Base):
    __tablename__ = "settings_profiles"
    __table_args__ = (UniqueConstraint("scope", "owner_id", "name"),)
    name: Mapped[str] = mapped_column(String(128), default="default")
    scope: Mapped[str] = mapped_column(String(16), default="user")  # user | project | global
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Experiment(TimestampMixin, Base):
    """A saved, reproducible experiment definition. Its runs are jobs; results live in the job's result file."""

    __tablename__ = "experiments"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    spec: Mapped[dict[str, Any]] = mapped_column(JSON)
    spec_sha256: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class SavedTopology(TimestampMixin, Base):
    """A topology designed or generated in the browser. ``layout`` holds canvas positions only."""

    __tablename__ = "topologies"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    graph: Mapped[dict[str, Any]] = mapped_column(JSON)
    layout: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class SavedWorkload(TimestampMixin, Base):
    """A workload (task classes, duration, intensity) designed in the browser."""

    __tablename__ = "workloads"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    spec: Mapped[dict[str, Any]] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class LiteratureEntry(TimestampMixin, Base):
    """One paper in the literature review, with screening stage and classification tags."""

    __tablename__ = "literature_entries"
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    bibtex_key: Mapped[str] = mapped_column(String(200), index=True)
    entry_type: Mapped[str] = mapped_column(String(40), default="article")
    title: Mapped[str] = mapped_column(Text)
    title_norm: Mapped[str] = mapped_column(String(500), index=True)
    authors: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[int | None] = mapped_column(nullable=True)
    venue: Mapped[str] = mapped_column(String(500), default="")
    doi: Mapped[str] = mapped_column(String(300), default="", index=True)
    url: Mapped[str] = mapped_column(String(1000), default="")
    abstract: Mapped[str] = mapped_column(Text, default="")
    keywords: Mapped[str] = mapped_column(Text, default="")
    raw_bibtex: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[str] = mapped_column(String(20), default="identified", index=True)
    exclusion_reason: Mapped[str] = mapped_column(String(300), default="")
    relevance: Mapped[int] = mapped_column(default=0)
    layers: Mapped[list[str]] = mapped_column(JSON, default=list)
    techniques: Mapped[list[str]] = mapped_column(JSON, default=list)
    metrics: Mapped[list[str]] = mapped_column(JSON, default=list)
    domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    evaluation: Mapped[list[str]] = mapped_column(JSON, default=list)
    datasets: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    contribution: Mapped[str] = mapped_column(Text, default="")
    limitations: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class LiteratureImport(Base):
    """One import batch, kept for the PRISMA counts (records identified, duplicates removed)."""

    __tablename__ = "literature_imports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    filename: Mapped[str] = mapped_column(String(300), default="")
    source: Mapped[str] = mapped_column(String(200), default="", doc="Database searched, e.g. Scopus")
    added: Mapped[int] = mapped_column(default=0)
    duplicates: Mapped[int] = mapped_column(default=0)
    failed: Mapped[int] = mapped_column(default=0)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Farm(TimestampMixin, Base):
    """A farm: a named location. Its fields hold boundaries, crops and soils."""

    __tablename__ = "farms"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    elevation_m: Mapped[float] = mapped_column(Float, default=0.0)
    region: Mapped[str] = mapped_column(String(200), default="")
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    fields: Mapped[list[FarmField]] = relationship(
        back_populates="farm", cascade="all, delete-orphan", order_by="FarmField.name"
    )


class FarmField(TimestampMixin, Base):
    """A field within a farm: boundary polygon, crop and sowing date, soil and irrigation set-up."""

    __tablename__ = "fields"
    farm_id: Mapped[str] = mapped_column(ForeignKey("farms.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    boundary: Mapped[list[Any]] = mapped_column(JSON, default=list)  # [[lon, lat], ...], GeoJSON order
    area_ha: Mapped[float] = mapped_column(Float, default=0.0)
    crop: Mapped[str] = mapped_column(String(40), default="wheat")
    sowing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stages: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)  # overrides the crop's stage lengths
    soil: Mapped[str] = mapped_column(String(40), default="loam")
    root_depth_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    irrigation_method: Mapped[str] = mapped_column(String(40), default="surface")
    efficiency: Mapped[float] = mapped_column(Float, default=0.6)
    rainfed: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    farm: Mapped[Farm] = relationship(back_populates="fields")


class WeatherRecord(Base):
    """One day of weather for a location and source, cached so seasons are not downloaded repeatedly."""

    __tablename__ = "weather_records"
    __table_args__ = (UniqueConstraint("location_key", "day", "source", name="uq_weather_location_day_source"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    location_key: Mapped[str] = mapped_column(String(80), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(20))  # open_meteo | csv
    forecast: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
