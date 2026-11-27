"""Uploaded datasets: register, profile, preview, map to sensor streams, validate and export."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from smartagri_core.data.tables import (
    KNOWN_METRICS,
    MAX_BYTES,
    Mapping,
    Table,
    TableError,
    guess_mapping,
    profile,
    read_table,
    tidy_csv,
    validate,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.config import get_settings
from smartagri_api.db import get_session
from smartagri_api.deps import audit, require
from smartagri_api.models import Dataset, Project, User

router = APIRouter(tags=["datasets"])

Origin = Literal["real", "synthetic", "derived"]


class DatasetOut(BaseModel):
    id: str
    name: str
    description: str
    filename: str
    format: str
    sheet: str | None
    sheets: list[str]
    size_bytes: int
    rows: int
    columns: list[dict[str, Any]]
    warnings: list[str]
    origin: str
    source_note: str
    mapping: dict[str, Any]
    sha256: str
    project_id: str | None
    created_at: str


class DatasetPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    origin: Origin | None = None
    source_note: str | None = None
    mapping: Mapping | None = None
    sheet: str | None = None


class PreviewOut(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    offset: int
    total: int


class ValidationOut(BaseModel):
    ok: bool
    problems: list[str]
    duplicate_rows: int
    series: list[dict[str, Any]]


class MetricsOut(BaseModel):
    metrics: dict[str, str]


def dataset_dir(dataset_id: str) -> Path:
    return get_settings().data_dir.resolve() / "datasets" / dataset_id


def load_table(d: Dataset) -> Table:
    path = dataset_dir(d.id) / d.filename
    if not path.exists():
        raise HTTPException(410, "The dataset's file is missing from the data folder")
    try:
        return read_table(path.read_bytes(), d.filename, d.sheet)
    except TableError as exc:
        raise HTTPException(422, str(exc)) from None


def _out(d: Dataset, table: Table | None = None) -> dict[str, Any]:
    return {
        "id": d.id,
        "name": d.name,
        "description": d.description,
        "filename": d.filename,
        "format": d.format,
        "sheet": d.sheet,
        "sheets": table.sheets if table else ([d.sheet] if d.sheet else []),
        "size_bytes": d.size_bytes,
        "rows": d.rows,
        "columns": d.columns,
        "warnings": d.warnings,
        "origin": d.origin,
        "source_note": d.source_note,
        "mapping": d.mapping,
        "sha256": d.sha256,
        "project_id": d.project_id,
        "created_at": d.created_at.isoformat(),
    }


def _get(session: Session, dataset_id: str) -> Dataset:
    d = session.get(Dataset, dataset_id)
    if d is None:
        raise HTTPException(404, "Dataset not found")
    return d


@router.get("/datasets/metrics", response_model=MetricsOut)
def known_metrics(_: User = Depends(require("project:read"))) -> dict[str, Any]:
    return {"metrics": KNOWN_METRICS}


@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(
    session: Session = Depends(get_session), _: User = Depends(require("project:read"))
) -> list[dict[str, Any]]:
    return [_out(d) for d in session.scalars(select(Dataset).order_by(Dataset.created_at.desc()))]


@router.post("/datasets", response_model=DatasetOut, status_code=201)
async def upload_dataset(
    file: UploadFile = File(...),
    name: str = Form(""),
    origin: Origin = Form(...),
    source_note: str = Form(""),
    description: str = Form(""),
    project_id: str | None = Form(None),
    session: Session = Depends(get_session),
    user: User = Depends(require("project:write")),
) -> dict[str, Any]:
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(413, f"Files up to {MAX_BYTES // 1024 // 1024} MB are accepted")
    filename = Path(file.filename or "upload.csv").name
    try:
        table = read_table(content, filename)
    except TableError as exc:
        raise HTTPException(422, str(exc)) from None
    if project_id and session.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    prof = profile(table)
    d = Dataset(
        name=name.strip() or Path(filename).stem,
        description=description,
        filename=filename,
        format=table.format,
        sheet=table.sheet,
        size_bytes=len(content),
        rows=len(table.rows),
        columns=prof,
        warnings=table.warnings,
        origin=origin,
        source_note=source_note,
        mapping=guess_mapping(prof),
        sha256=hashlib.sha256(content).hexdigest(),
        project_id=project_id,
        created_by=user.id,
    )
    session.add(d)
    session.flush()
    folder = dataset_dir(d.id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_bytes(content)
    audit(session, user, "dataset.upload", "dataset", d.id, file=filename, rows=d.rows)
    session.commit()
    return _out(d, table)


@router.get("/datasets/{dataset_id}", response_model=DatasetOut)
def get_dataset(
    dataset_id: str, session: Session = Depends(get_session), _: User = Depends(require("project:read"))
) -> dict[str, Any]:
    d = _get(session, dataset_id)
    return _out(d, load_table(d) if d.format == "xlsx" else None)


@router.patch("/datasets/{dataset_id}", response_model=DatasetOut)
def update_dataset(
    dataset_id: str,
    body: DatasetPatch,
    session: Session = Depends(get_session),
    user: User = Depends(require("project:write")),
) -> dict[str, Any]:
    d = _get(session, dataset_id)
    changes = body.model_dump(exclude_unset=True)
    table = None
    if "sheet" in changes and changes["sheet"] != d.sheet:
        d.sheet = changes.pop("sheet")
        table = load_table(d)
        d.columns, d.rows, d.warnings = profile(table), len(table.rows), table.warnings
        d.mapping = guess_mapping(d.columns)
    changes.pop("sheet", None)
    if "mapping" in changes:
        names = {c["name"] for c in d.columns}
        m = body.mapping
        assert m is not None
        missing = [
            c
            for c in [m.time_column, m.source_column, m.metric_column, m.value_column, *m.metrics]
            if c and c not in names
        ]
        if missing:
            raise HTTPException(422, f"Not columns of this dataset: {', '.join(missing)}")
        changes["mapping"] = m.model_dump()
    for k, v in changes.items():
        setattr(d, k, v)
    audit(session, user, "dataset.update", "dataset", d.id, fields=sorted(body.model_dump(exclude_unset=True)))
    session.commit()
    return _out(d, table)


@router.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: str, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> Response:
    d = _get(session, dataset_id)
    shutil.rmtree(dataset_dir(d.id), ignore_errors=True)
    session.delete(d)
    audit(session, user, "dataset.delete", "dataset", dataset_id, name=d.name)
    session.commit()
    return Response(status_code=204)


@router.get("/datasets/{dataset_id}/preview", response_model=PreviewOut)
def preview(
    dataset_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
    _: User = Depends(require("project:read")),
) -> dict[str, Any]:
    table = load_table(_get(session, dataset_id))
    rows = [
        [v if isinstance(v, int | float | str | type(None)) else str(v) for v in r]
        for r in table.rows[offset : offset + limit]
    ]
    return {"columns": table.columns, "rows": rows, "offset": offset, "total": len(table.rows)}


@router.get("/datasets/{dataset_id}/validation", response_model=ValidationOut)
def validation(
    dataset_id: str, session: Session = Depends(get_session), _: User = Depends(require("project:read"))
) -> dict[str, Any]:
    d = _get(session, dataset_id)
    return validate(load_table(d), Mapping(**d.mapping))


@router.get("/datasets/{dataset_id}/download")
def download(
    dataset_id: str, session: Session = Depends(get_session), _: User = Depends(require("project:read"))
) -> FileResponse:
    d = _get(session, dataset_id)
    path = dataset_dir(d.id) / d.filename
    if not path.exists():
        raise HTTPException(410, "The dataset's file is missing from the data folder")
    return FileResponse(path, filename=d.filename)


@router.get("/datasets/{dataset_id}/tidy.csv")
def export_tidy(
    dataset_id: str, session: Session = Depends(get_session), _: User = Depends(require("project:read"))
) -> Response:
    d = _get(session, dataset_id)
    body = tidy_csv(load_table(d), Mapping(**d.mapping))
    stem = Path(d.filename).stem
    return Response(
        body, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{stem}-tidy.csv"'}
    )
