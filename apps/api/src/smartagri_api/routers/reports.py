"""Reports: PDF, Excel, LaTeX, figures and reproducibility bundles for finished jobs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from smartagri_core import get_registry
from smartagri_core.reports import FORMATS, KIND_TITLES, build_report, export, figure_svg, supported
from smartagri_core.reports.model import CI, fmt_ci, fmt_num
from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.config import Settings, get_settings
from smartagri_api.db import get_session
from smartagri_api.deps import require
from smartagri_api.models import Job, User
from smartagri_api.routers.jobs import read_result

router = APIRouter(tags=["reports"])
_KIND = re.compile(r'"kind"\s*:\s*"([^"]+)"')


def _result_kind(path: Path) -> str | None:
    """The result's kind, read from the start of the file when possible (results can be large)."""
    try:
        with path.open(encoding="utf-8") as f:
            head = f.read(4096)
        m = _KIND.search(head)
        if m:
            return m.group(1)
        return str(json.loads(path.read_text(encoding="utf-8")).get("kind", "")) or None
    except (OSError, ValueError):
        return None


@router.get("/reports")
def list_reports(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require("job:read")),
) -> list[dict[str, Any]]:
    """Finished jobs that have a result, newest first, with the report layout their result supports."""
    reg = get_registry()
    out = []
    jobs = session.scalars(select(Job).where(Job.status == "succeeded").order_by(Job.created_at.desc())).all()
    for job in jobs:
        if not job.result_path:
            continue
        path = Path(job.result_path).resolve()
        if not path.is_relative_to(settings.resolved_results_dir) or not path.exists():
            continue
        kind = _result_kind(path) or ""
        try:
            name = reg.get(job.plugin_id).name
        except Exception:  # noqa: BLE001 - a plugin removed since the job ran still has a result to export
            name = job.plugin_id
        out.append(
            {
                "job_id": job.id,
                "plugin_id": job.plugin_id,
                "plugin_name": name,
                "kind": kind,
                "title": KIND_TITLES.get(kind, name),
                "dedicated_layout": supported(kind),
                "data_origin": job.data_origin,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            }
        )
    return out


def _job_result(job_id: str, session: Session, settings: Settings) -> tuple[Job, dict[str, Any]]:
    job = session.get(Job, job_id)
    result = read_result(job, settings)
    if not isinstance(result, dict):
        raise HTTPException(422, "This job's result cannot be turned into a report")
    return job, result


def _text(v: Any, decimals: int | None) -> str:
    if isinstance(v, CI):
        return fmt_ci(v, decimals) + {"better": " ▼", "worse": " ▲"}.get(v.mark, "")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return fmt_num(v, decimals)
    return "" if v is None else str(v)


@router.get("/reports/{job_id}/preview")
def preview(
    job_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require("job:read")),
) -> dict[str, Any]:
    job, result = _job_result(job_id, session, settings)
    rep = build_report(result)
    return {
        "job_id": job.id,
        "plugin_id": job.plugin_id,
        "kind": rep.kind,
        "title": rep.title,
        "subtitle": rep.subtitle,
        "data_origin": rep.data_origin,
        "summary": rep.summary,
        "caveats": rep.caveats,
        "tables": [
            {
                "key": t.key,
                "caption": t.caption,
                "columns": [c.header for c in t.columns],
                "numeric": [c.kind != "text" for c in t.columns],
                "rows": [[_text(v, c.decimals) for v, c in zip(row, t.columns, strict=True)] for row in t.rows],
                "notes": t.notes,
                "highlight_row": t.highlight_row,
            }
            for t in rep.tables
        ],
        "figures": [{"key": f.key, "caption": f.caption} for f in rep.figures],
        "formats": list(FORMATS),
    }


@router.get("/reports/{job_id}/figure/{key}.svg")
def figure(
    job_id: str,
    key: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require("job:read")),
) -> Response:
    _, result = _job_result(job_id, session, settings)
    try:
        svg = figure_svg(result, key)
    except KeyError:
        raise HTTPException(404, "No such figure") from None
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/reports/{job_id}/export/{fmt}")
def export_report(
    job_id: str,
    fmt: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require("job:read")),
) -> Response:
    if fmt not in FORMATS:
        raise HTTPException(404, f"Unknown format; use one of {', '.join(FORMATS)}")
    job, result = _job_result(job_id, session, settings)
    result_path = Path(job.result_path or "")
    cache = result_path.parent / "reports" / job.id / FORMATS[fmt][1]
    media = FORMATS[fmt][0]
    if cache.exists() and cache.stat().st_mtime >= result_path.stat().st_mtime:
        data = cache.read_bytes()
    else:
        data, media, _name = export(result, fmt, plugin_id=job.plugin_id, params=job.params)
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
        except OSError:
            pass  # caching is only an optimisation
    title = KIND_TITLES.get(str(result.get("kind", "")), job.plugin_id)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "report"
    filename = f"{slug}-{job.id[:8]}-{FORMATS[fmt][1]}"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
