from __future__ import annotations

import platform
from collections import Counter

import smartagri_core
from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from smartagri_api import __commit__, __version__
from smartagri_api.config import Settings, get_settings
from smartagri_api.db import get_session
from smartagri_api.deps import require
from smartagri_api.models import AuditLog, User
from smartagri_api.schemas import AuditEntry, Health, SystemInfo

router = APIRouter(tags=["system"])


@router.get("/health", response_model=Health)
def health(session: Session = Depends(get_session), settings: Settings = Depends(get_settings)) -> Health:
    try:
        session.execute(text("SELECT 1"))
        db = "ok"
    except Exception as exc:  # pragma: no cover - reported, not raised
        db = f"error: {exc}"
    return Health(
        status="ok" if db == "ok" else "degraded",
        version=__version__,
        commit=__commit__,
        core_version=smartagri_core.__version__,
        local_mode=settings.local_mode,
        database=db,
    )


@router.get("/system/info", response_model=SystemInfo)
def system_info(settings: Settings = Depends(get_settings), _: User = Depends(require("plugin:read"))) -> SystemInfo:
    registry = smartagri_core.get_registry()
    counts = Counter(str(s.status) for s in registry.all())
    return SystemInfo(
        version=__version__,
        core_version=smartagri_core.__version__,
        python=platform.python_version(),
        local_mode=settings.local_mode,
        data_dir=str(settings.data_dir.resolve()),
        results_dir=str(settings.resolved_results_dir),
        job_workers=settings.job_workers,
        plugin_counts=dict(counts),
        plugin_load_errors=registry.load_errors,
    )


@router.get("/audit", response_model=list[AuditEntry])
def audit_log(
    limit: int = 100, session: Session = Depends(get_session), _: User = Depends(require("audit:read"))
) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(min(limit, 1000))))
