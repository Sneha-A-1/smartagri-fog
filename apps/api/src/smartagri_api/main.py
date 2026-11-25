"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from smartagri_core import get_registry

from smartagri_api import __version__
from smartagri_api.config import DEFAULT_SECRET, Settings, get_settings
from smartagri_api.db import init_engine, session_scope
from smartagri_api.jobs.runner import JobEventHub, JobRunner
from smartagri_api.migrate import run_migrations
from smartagri_api.rbac import seed_access_control
from smartagri_api.routers import auth, experiments, jobs, plugins, projects, system
from smartagri_api.routers import settings as settings_router

log = logging.getLogger("smartagri_api")

WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not settings.local_mode and settings.secret_key == DEFAULT_SECRET:
            raise RuntimeError("Set SMARTAGRI_SECRET_KEY before running with local_mode disabled")
        settings.ensure_dirs()
        url = settings.resolved_database_url
        run_migrations(url)
        init_engine(url)
        with session_scope() as s:
            seed_access_control(s, settings.local_mode)
        get_registry().ensure_loaded()
        for err in get_registry().load_errors:
            log.warning("Plugin failed to load: %s", err)
        hub = JobEventHub()
        runner = JobRunner(settings, hub)
        await runner.start()
        app.state.job_hub, app.state.job_runner = hub, runner
        try:
            yield
        finally:
            await runner.stop()

    app = FastAPI(
        title="SmartAgri-Fog API",
        version=__version__,
        description="Research platform for cloud-fog-edge smart agriculture. All science lives in smartagri-core.",
        lifespan=lifespan,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for module in (system, auth, plugins, jobs, experiments, projects, settings_router):
        app.include_router(module.router, prefix="/api")

    if WEB_DIST.is_dir():  # serve the built web interface when it exists (production / one-command mode)
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = (WEB_DIST / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(WEB_DIST):
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html")

    return app
