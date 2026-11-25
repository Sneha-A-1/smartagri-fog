"""Roles and permissions. Roles are bundles of permissions, so a new role needs no code changes elsewhere."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.models import Permission, Role, User

LOCAL_ADMIN_EMAIL = "local-admin@smartagri.local"

PERMISSIONS: dict[str, str] = {
    "plugin:read": "Browse the algorithm catalogue",
    "job:run": "Start jobs and experiments",
    "job:read": "View jobs and their results",
    "project:read": "View projects",
    "project:write": "Create, edit and delete projects",
    "farm:read": "View farms, fields and sensors",
    "farm:write": "Edit farms, fields and sensors",
    "agri:analyse": "Use crop-health and agricultural analysis tools",
    "settings:write": "Change your own settings",
    "user:manage": "Manage users and roles",
    "system:configure": "Change system-wide configuration",
    "audit:read": "Read the audit log",
}

ROLES: dict[str, tuple[str, list[str]]] = {
    "admin": ("Full access, system configuration and user management", list(PERMISSIONS)),
    "researcher": (
        "Experiments, algorithms, simulation and evaluation",
        [
            "plugin:read",
            "job:run",
            "job:read",
            "project:read",
            "project:write",
            "farm:read",
            "farm:write",
            "agri:analyse",
            "settings:write",
        ],
    ),
    "farmer": ("Farm monitoring, recommendations and irrigation", ["farm:read", "job:read", "settings:write"]),
    "expert": (
        "Crop health, disease detection and agricultural analysis",
        ["farm:read", "agri:analyse", "plugin:read", "job:read", "job:run", "settings:write"],
    ),
}


def seed_access_control(session: Session, local_mode: bool) -> None:
    """Create permissions, roles and (in local mode) the default user. Safe to run on every start."""
    perms = {p.code: p for p in session.scalars(select(Permission))}
    for code, description in PERMISSIONS.items():
        if code not in perms:
            perms[code] = Permission(code=code, description=description)
            session.add(perms[code])
    session.flush()

    roles = {r.name: r for r in session.scalars(select(Role))}
    for name, (description, codes) in ROLES.items():
        role = roles.get(name) or Role(name=name, description=description)
        role.permissions = [perms[c] for c in codes]
        session.add(role)
        roles[name] = role
    session.flush()

    if local_mode and session.scalar(select(User).where(User.email == LOCAL_ADMIN_EMAIL)) is None:
        session.add(User(email=LOCAL_ADMIN_EMAIL, display_name="Researcher (local mode)", roles=[roles["admin"]]))
    session.commit()
