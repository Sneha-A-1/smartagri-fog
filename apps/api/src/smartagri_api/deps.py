"""Request dependencies: current user and permission checks."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.config import Settings, get_settings
from smartagri_api.db import get_session
from smartagri_api.models import AuditLog, User
from smartagri_api.rbac import LOCAL_ADMIN_EMAIL
from smartagri_api.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    if settings.local_mode and not token:
        user = session.scalar(select(User).where(User.email == LOCAL_ADMIN_EMAIL))
        if user is None:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Local user missing; restart the API")
        return user
    user_id = decode_access_token(token, settings.secret_key) if token else None
    user = session.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in", headers={"WWW-Authenticate": "Bearer"})
    return user


def require(permission: str) -> Callable[..., User]:
    def checker(user: User = Depends(get_current_user)) -> User:
        if permission not in user.permission_codes:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {permission}")
        return user

    return checker


def audit(
    session: Session,
    actor: User | None,
    action: str,
    entity_type: str = "",
    entity_id: str | None = None,
    **details: object,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )
