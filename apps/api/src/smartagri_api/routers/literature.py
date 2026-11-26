"""Literature matrix: import, screen (PRISMA 2020), classify, find gaps, export."""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.db import get_session
from smartagri_api.deps import audit, require
from smartagri_api.literature import (
    DIMENSIONS,
    STAGES,
    VOCABULARY,
    make_key,
    normalize_doi,
    normalize_title,
    parse_bibtex,
    parse_csl_json,
    to_bibtex,
    to_csv,
    to_latex,
)
from smartagri_api.models import LiteratureEntry, LiteratureImport, User

router = APIRouter(tags=["literature"])

Stage = Literal["identified", "screened_out", "full_text", "excluded", "included"]
Dimension = Literal["layers", "techniques", "metrics", "domains", "evaluation", "datasets", "tags"]


class EntryIn(BaseModel):
    title: str = Field(min_length=1)
    authors: str = ""
    year: int | None = Field(None, ge=1900, le=2100)
    venue: str = ""
    doi: str = ""
    url: str = ""
    abstract: str = ""
    bibtex_key: str = ""
    project_id: str | None = None


class EntryPatch(BaseModel):
    title: str | None = None
    authors: str | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    abstract: str | None = None
    stage: Stage | None = None
    exclusion_reason: str | None = None
    relevance: int | None = Field(None, ge=0, le=3)
    layers: list[str] | None = None
    techniques: list[str] | None = None
    metrics: list[str] | None = None
    domains: list[str] | None = None
    evaluation: list[str] | None = None
    datasets: list[str] | None = None
    tags: list[str] | None = None
    contribution: str | None = None
    limitations: str | None = None
    notes: str | None = None


class EntryOut(BaseModel):
    id: str
    bibtex_key: str
    entry_type: str
    title: str
    authors: str
    year: int | None
    venue: str
    doi: str
    url: str
    abstract: str
    keywords: str
    stage: str
    exclusion_reason: str
    relevance: int
    layers: list[str]
    techniques: list[str]
    metrics: list[str]
    domains: list[str]
    evaluation: list[str]
    datasets: list[str]
    tags: list[str]
    contribution: str
    limitations: str
    notes: str
    project_id: str | None
    updated_at: str


class ImportOut(BaseModel):
    added: int
    duplicates: int
    failed: int
    duplicate_titles: list[str]


class Vocabulary(BaseModel):
    dimensions: list[str]
    stages: dict[str, str]
    suggestions: dict[str, list[str]]


class PrismaOut(BaseModel):
    identified: int = Field(description="Records identified across all imports (before de-duplication)")
    duplicates_removed: int
    by_source: dict[str, int]
    screened: int
    excluded_screening: int
    assessed_full_text: int
    excluded_full_text: int
    exclusion_reasons: dict[str, int]
    awaiting_screening: int
    awaiting_full_text: int
    included: int


class MatrixOut(BaseModel):
    rows: list[str]
    cols: list[str]
    counts: list[list[int]]
    papers: dict[str, list[str]] = Field(description="'row|col' -> entry ids")
    total: int


def _out(e: LiteratureEntry) -> dict[str, Any]:
    return {
        **{c: getattr(e, c) for c in EntryOut.model_fields if c not in ("updated_at",)},
        "updated_at": e.updated_at.isoformat(),
    }


def _entries(session: Session, stage: str | None = None, project_id: str | None = None) -> list[LiteratureEntry]:
    q = select(LiteratureEntry).order_by(LiteratureEntry.year.desc(), LiteratureEntry.title)
    if stage:
        q = q.where(LiteratureEntry.stage.in_(stage.split(",")))
    if project_id:
        q = q.where(LiteratureEntry.project_id == project_id)
    return list(session.scalars(q))


def _unique_key(session: Session, key: str) -> str:
    existing = set(session.scalars(select(LiteratureEntry.bibtex_key)))
    base, n = key or "paper", 1
    candidate = base
    while candidate in existing:
        n += 1
        candidate = f"{base}{chr(96 + n) if n <= 26 else n}"
    return candidate


@router.get("/literature/vocabulary", response_model=Vocabulary)
def vocabulary(session: Session = Depends(get_session), _: User = Depends(require("project:read"))) -> dict[str, Any]:
    """Suggested values, merged with every value already used, most used first."""
    used: dict[str, Counter[str]] = {d: Counter() for d in DIMENSIONS}
    for e in session.scalars(select(LiteratureEntry)):
        for d in DIMENSIONS:
            used[d].update(getattr(e, d) or [])
    suggestions = {}
    for d in DIMENSIONS:
        seen = [v for v, _ in used[d].most_common()]
        suggestions[d] = seen + [v for v in VOCABULARY[d] if v not in used[d]]
    return {"dimensions": DIMENSIONS, "stages": STAGES, "suggestions": suggestions}


@router.get("/literature", response_model=list[EntryOut])
def list_entries(
    stage: str | None = None,
    project_id: str | None = None,
    session: Session = Depends(get_session),
    _: User = Depends(require("project:read")),
) -> list[dict[str, Any]]:
    return [_out(e) for e in _entries(session, stage, project_id)]


@router.post("/literature", response_model=EntryOut, status_code=201)
def create_entry(
    body: EntryIn, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> dict[str, Any]:
    doi, norm = normalize_doi(body.doi), normalize_title(body.title)
    if session.scalar(
        select(LiteratureEntry).where(
            (LiteratureEntry.title_norm == norm) | ((LiteratureEntry.doi == doi) & (doi != ""))
        )
    ):
        raise HTTPException(409, "This paper is already in the matrix (same title or DOI)")
    key = _unique_key(session, body.bibtex_key or make_key(body.authors, body.year, body.title))
    e = LiteratureEntry(
        title=body.title,
        title_norm=norm,
        authors=body.authors,
        year=body.year,
        venue=body.venue,
        doi=doi,
        url=body.url,
        abstract=body.abstract,
        bibtex_key=key,
        project_id=body.project_id,
    )
    session.add(e)
    session.flush()
    audit(session, user, "literature.create", "literature", e.id)
    session.commit()
    return _out(e)


@router.post("/literature/import", response_model=ImportOut)
async def import_entries(
    file: UploadFile = File(...),
    source: str = Form(""),
    project_id: str | None = Form(None),
    session: Session = Depends(get_session),
    user: User = Depends(require("project:write")),
) -> dict[str, Any]:
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    name = file.filename or "upload"
    try:
        if name.lower().endswith(".json") or raw.lstrip().startswith(("[", "{")):
            parsed, failed = parse_csl_json(raw)
        else:
            parsed, failed = parse_bibtex(raw)
    except Exception as exc:
        raise HTTPException(422, f"Couldn't read {name}: {exc}") from None
    if not parsed and failed == 0:
        raise HTTPException(422, f"No references found in {name}. Export BibTeX (.bib) or CSL JSON from Zotero.")

    known_titles = set(session.scalars(select(LiteratureEntry.title_norm)))
    known_dois = {d for d in session.scalars(select(LiteratureEntry.doi)) if d}
    added, dup_titles = 0, []
    for p in parsed:
        norm = normalize_title(p["title"])
        if norm in known_titles or (p["doi"] and p["doi"] in known_dois):
            dup_titles.append(p["title"])
            continue
        key = _unique_key(session, p["bibtex_key"] or make_key(p["authors"], p["year"], p["title"]))
        session.add(LiteratureEntry(**p | {"bibtex_key": key}, title_norm=norm, project_id=project_id))
        session.flush()
        known_titles.add(norm)
        if p["doi"]:
            known_dois.add(p["doi"])
        added += 1
    session.add(
        LiteratureImport(
            filename=name, source=source, added=added, duplicates=len(dup_titles), failed=failed, project_id=project_id
        )
    )
    audit(session, user, "literature.import", "literature", None, file=name, added=added, duplicates=len(dup_titles))
    session.commit()
    return {"added": added, "duplicates": len(dup_titles), "failed": failed, "duplicate_titles": dup_titles[:50]}


@router.get("/literature/prisma", response_model=PrismaOut)
def prisma(session: Session = Depends(get_session), _: User = Depends(require("project:read"))) -> dict[str, Any]:
    imports = list(session.scalars(select(LiteratureImport)))
    entries = _entries(session)
    stages = Counter(e.stage for e in entries)
    by_source: Counter[str] = Counter()
    for imp in imports:
        by_source[imp.source or "Unspecified"] += imp.added + imp.duplicates
    manual = len(entries) - sum(i.added for i in imports)
    if manual > 0:
        by_source["Added manually"] += manual
    reasons = Counter(e.exclusion_reason or "No reason given" for e in entries if e.stage == "excluded")
    return {
        "identified": sum(by_source.values()),
        "duplicates_removed": sum(i.duplicates for i in imports),
        "by_source": dict(by_source),
        "screened": len(entries) - stages["identified"],
        "excluded_screening": stages["screened_out"],
        "assessed_full_text": stages["excluded"] + stages["included"],
        "excluded_full_text": stages["excluded"],
        "exclusion_reasons": dict(reasons),
        "awaiting_screening": stages["identified"],
        "awaiting_full_text": stages["full_text"],
        "included": stages["included"],
    }


@router.get("/literature/matrix", response_model=MatrixOut)
def matrix(
    rows: Dimension = "techniques",
    cols: Dimension = "layers",
    stage: str | None = "included",
    session: Session = Depends(get_session),
    _: User = Depends(require("project:read")),
) -> dict[str, Any]:
    """Cross-tabulation of two classification dimensions. Empty or sparse cells point to research gaps."""
    entries = _entries(session, stage or None)
    row_vals = sorted({v for e in entries for v in getattr(e, rows) or []}, key=str.lower)
    col_vals = sorted({v for e in entries for v in getattr(e, cols) or []}, key=str.lower)
    if cols == "layers":
        order = {v: i for i, v in enumerate(VOCABULARY["layers"])}
        col_vals.sort(key=lambda v: order.get(v, 99))
    counts = [[0] * len(col_vals) for _ in row_vals]
    papers: dict[str, list[str]] = {}
    ri, ci = {v: i for i, v in enumerate(row_vals)}, {v: i for i, v in enumerate(col_vals)}
    for e in entries:
        for r in set(getattr(e, rows) or []):
            for c in set(getattr(e, cols) or []):
                counts[ri[r]][ci[c]] += 1
                papers.setdefault(f"{r}|{c}", []).append(e.id)
    return {"rows": row_vals, "cols": col_vals, "counts": counts, "papers": papers, "total": len(entries)}


EXPORTS = {
    "bib": ("application/x-bibtex", "references.bib"),
    "csv": ("text/csv", "literature-matrix.csv"),
    "tex": ("application/x-tex", "studies-table.tex"),
}


@router.get("/literature/export/{fmt}")
def export(
    fmt: str,
    stage: str | None = None,
    session: Session = Depends(get_session),
    _: User = Depends(require("project:read")),
) -> Response:
    if fmt not in EXPORTS:
        raise HTTPException(404, f"Unknown format; use one of {', '.join(EXPORTS)}")
    entries = [_out(e) | {"raw_bibtex": e.raw_bibtex, "entry_type": e.entry_type} for e in _entries(session, stage)]
    if fmt == "bib":
        body = "\n\n".join(to_bibtex(e) for e in entries) + "\n"
    elif fmt == "csv":
        body = to_csv(entries)
    else:
        body = to_latex(entries)
    media, filename = EXPORTS[fmt]
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/literature/{entry_id}", response_model=EntryOut)
def get_entry(
    entry_id: str, session: Session = Depends(get_session), _: User = Depends(require("project:read"))
) -> dict[str, Any]:
    e = session.get(LiteratureEntry, entry_id)
    if e is None:
        raise HTTPException(404, "Paper not found")
    return _out(e)


@router.patch("/literature/{entry_id}", response_model=EntryOut)
def update_entry(
    entry_id: str,
    body: EntryPatch,
    session: Session = Depends(get_session),
    user: User = Depends(require("project:write")),
) -> dict[str, Any]:
    e = session.get(LiteratureEntry, entry_id)
    if e is None:
        raise HTTPException(404, "Paper not found")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if field in DIMENSIONS:
            value = list(dict.fromkeys(v.strip() for v in value or [] if v.strip()))
        if field == "doi":
            value = normalize_doi(value)
        setattr(e, field, value)
    if "title" in changes:
        e.title_norm = normalize_title(e.title)
    if "stage" in changes and e.stage != "excluded" and "exclusion_reason" not in changes:
        e.exclusion_reason = ""
    audit(session, user, "literature.update", "literature", e.id, fields=sorted(changes))
    session.commit()
    return _out(e)


@router.delete("/literature/{entry_id}", status_code=204)
def delete_entry(
    entry_id: str, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> Response:
    e = session.get(LiteratureEntry, entry_id)
    if e is None:
        raise HTTPException(404, "Paper not found")
    session.delete(e)
    audit(session, user, "literature.delete", "literature", entry_id, title=e.title)
    session.commit()
    return Response(status_code=204)
