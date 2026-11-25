from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from smartagri_core import get_registry
from smartagri_core.registry import PluginNotFoundError

from smartagri_api.deps import require
from smartagri_api.models import User
from smartagri_api.schemas import ParamsIn, ParamsValidated, PluginDetail, PluginSummary

router = APIRouter(tags=["plugins"])


@router.get("/plugins", response_model=list[PluginSummary])
def list_plugins(
    kind: str | None = None, status: str | None = None, _: User = Depends(require("plugin:read"))
) -> list[dict]:
    specs = get_registry().all()
    return [
        s.to_dict()
        for s in specs
        if (kind is None or str(s.kind) == kind) and (status is None or str(s.status) == status)
    ]


@router.get("/plugins/{plugin_id}", response_model=PluginDetail)
def get_plugin(plugin_id: str, _: User = Depends(require("plugin:read"))) -> dict:
    try:
        return get_registry().get(plugin_id).to_dict(include_schema=True)
    except PluginNotFoundError as exc:
        raise HTTPException(404, str(exc)) from None


@router.post("/plugins/{plugin_id}/validate", response_model=ParamsValidated)
def validate_params(plugin_id: str, body: ParamsIn, _: User = Depends(require("plugin:read"))) -> ParamsValidated:
    try:
        spec = get_registry().get(plugin_id)
    except PluginNotFoundError as exc:
        raise HTTPException(404, str(exc)) from None
    try:
        model = spec.validate_params(body.params)
    except ValidationError as exc:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return ParamsValidated(valid=False, errors=errors)
    return ParamsValidated(valid=True, params=model.model_dump(mode="json"))
