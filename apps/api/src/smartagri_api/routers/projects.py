from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.db import get_session
from smartagri_api.deps import audit, require
from smartagri_api.models import Project, User
from smartagri_api.schemas import ProjectIn, ProjectOut, ProjectPatch

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session), _: User = Depends(require("project:read"))) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.created_at.desc())))


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectIn, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> Project:
    project = Project(**body.model_dump(), created_by=user.id)
    session.add(project)
    session.flush()
    audit(session, user, "project.create", "project", project.id, name=project.name)
    session.commit()
    return project


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str, session: Session = Depends(get_session), _: User = Depends(require("project:read"))
) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: ProjectPatch,
    session: Session = Depends(get_session),
    user: User = Depends(require("project:write")),
) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(project, field, value)
    audit(session, user, "project.update", "project", project.id, changes=changes)
    session.commit()
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: str, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> Response:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    session.delete(project)
    audit(session, user, "project.delete", "project", project_id, name=project.name)
    session.commit()
    return Response(status_code=204)
