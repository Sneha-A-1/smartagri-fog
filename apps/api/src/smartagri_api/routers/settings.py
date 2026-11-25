from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.db import get_session
from smartagri_api.deps import audit, get_current_user, require
from smartagri_api.models import SettingsProfile, User
from smartagri_api.schemas import UserSettings

router = APIRouter(tags=["settings"])


def _profile(session: Session, user: User) -> SettingsProfile | None:
    return session.scalar(
        select(SettingsProfile).where(
            SettingsProfile.scope == "user", SettingsProfile.owner_id == user.id, SettingsProfile.name == "default"
        )
    )


@router.get("/settings/me", response_model=UserSettings)
def get_my_settings(session: Session = Depends(get_session), user: User = Depends(get_current_user)) -> UserSettings:
    profile = _profile(session, user)
    return UserSettings(values=profile.values if profile else {})


@router.put("/settings/me", response_model=UserSettings)
def put_my_settings(
    body: UserSettings, session: Session = Depends(get_session), user: User = Depends(require("settings:write"))
) -> UserSettings:
    profile = _profile(session, user) or SettingsProfile(scope="user", owner_id=user.id, name="default")
    profile.values = body.values
    session.add(profile)
    audit(session, user, "settings.update", "settings_profile", profile.id)
    session.commit()
    return UserSettings(values=profile.values)
