from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.config import Settings, get_settings
from smartagri_api.db import get_session
from smartagri_api.deps import audit, get_current_user, require
from smartagri_api.models import Role, User
from smartagri_api.schemas import TokenOut, UserCreate, UserOut
from smartagri_api.security import create_access_token, hash_password, verify_password

router = APIRouter(tags=["auth"])


def user_out(user: User, settings: Settings) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        locale=user.locale,
        roles=sorted(r.name for r in user.roles),
        permissions=sorted(user.permission_codes),
        local_mode=settings.local_mode,
    )


@router.post("/auth/login", response_model=TokenOut)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenOut:
    user = session.scalar(select(User).where(User.email == form.username))
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    audit(session, user, "auth.login", "user", user.id)
    session.commit()
    return TokenOut(access_token=create_access_token(user.id, settings.secret_key, settings.access_token_minutes))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)) -> UserOut:
    return user_out(user, settings)


@router.get("/users", response_model=list[UserOut])
def list_users(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: User = Depends(require("user:manage")),
) -> list[UserOut]:
    return [user_out(u, settings) for u in session.scalars(select(User).order_by(User.email))]


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    actor: User = Depends(require("user:manage")),
) -> UserOut:
    if session.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists")
    roles = list(session.scalars(select(Role).where(Role.name.in_(body.roles))))
    if len(roles) != len(set(body.roles)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown role in request")
    user = User(
        email=body.email, display_name=body.display_name, password_hash=hash_password(body.password), roles=roles
    )
    session.add(user)
    session.flush()
    audit(session, actor, "user.create", "user", user.id, roles=body.roles)
    session.commit()
    return user_out(user, settings)
