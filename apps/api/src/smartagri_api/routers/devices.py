"""Field devices, readings, ingestion from real hardware, and the digital-twin overview."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from smartagri_api.db import get_session
from smartagri_api.deps import audit, require
from smartagri_api.device_service import (
    DEFAULT_CONFIG,
    KINDS,
    METRIC_UNITS,
    hash_token,
    is_online,
    new_token,
    top_up,
)
from smartagri_api.models import Device, Farm, FarmField, Reading, User
from smartagri_api.weather_service import WeatherUnavailable

router = APIRouter(tags=["devices"])

Kind = Literal["soil_moisture", "weather_station", "valve", "gateway"]


class DeviceConfig(BaseModel):
    weather_source: Literal["open_meteo", "csv", "synthetic"] = "open_meteo"
    et_multiplier: float = Field(1.15, ge=0.5, le=2.0, description="True field water use relative to the FAO-56 model")
    noise_sd: float = Field(0.01, ge=0, le=0.1)
    bias: float = Field(0.0, ge=-0.1, le=0.1)
    dropout: float = Field(0.02, ge=0, le=0.9)
    application_mm_per_h: float = Field(5.0, gt=0, le=100)


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Kind
    field_id: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    simulated: bool = True
    interval_min: int = Field(30, ge=1, le=1440)
    config: DeviceConfig = Field(default_factory=DeviceConfig)


class DevicePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    field_id: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    interval_min: int | None = Field(None, ge=1, le=1440)
    config: DeviceConfig | None = None


class LatestValue(BaseModel):
    value: float
    ts: datetime
    origin: str


class DeviceOut(BaseModel):
    id: str
    farm_id: str
    field_id: str | None
    name: str
    kind: str
    kind_label: str
    metrics: list[str]
    latitude: float
    longitude: float
    simulated: bool
    interval_min: int
    config: dict[str, Any]
    last_seen: datetime | None
    online: bool
    latest: dict[str, LatestValue]
    token: str | None = Field(None, description="Only returned when created or reset; store it on the device")
    note: str | None = None


class DeviceKinds(BaseModel):
    kinds: dict[str, dict[str, Any]]
    metrics: dict[str, list[str]]
    default_config: dict[str, Any]


class ReadingPoint(BaseModel):
    ts: datetime
    value: float
    min: float
    max: float
    count: int


class ReadingsOut(BaseModel):
    device_id: str
    metric: str
    label: str
    unit: str
    origin: str | None
    points: list[ReadingPoint]
    total: int


class IngestReading(BaseModel):
    metric: str = Field(min_length=1, max_length=40)
    value: float
    ts: datetime | None = Field(None, description="ISO time; defaults to the time of receipt")


class IngestIn(BaseModel):
    device_id: str
    readings: list[IngestReading] = Field(min_length=1, max_length=1000)


class IngestOut(BaseModel):
    stored: int
    duplicates: int


def _latest(session: Session, device: Device) -> dict[str, dict[str, Any]]:
    out = {}
    for metric in KINDS[device.kind]["metrics"]:
        r = session.scalars(
            select(Reading).where(Reading.device_id == device.id, Reading.metric == metric).order_by(Reading.ts.desc())
        ).first()
        if r is not None:
            out[metric] = {"value": r.value, "ts": r.ts, "origin": r.origin}
    return out


def _out(session: Session, d: Device, token: str | None = None, note: str | None = None) -> dict[str, Any]:
    return {
        "id": d.id,
        "farm_id": d.farm_id,
        "field_id": d.field_id,
        "name": d.name,
        "kind": d.kind,
        "kind_label": KINDS[d.kind]["label"],
        "metrics": KINDS[d.kind]["metrics"],
        "latitude": d.latitude,
        "longitude": d.longitude,
        "simulated": d.simulated,
        "interval_min": d.interval_min,
        "config": DEFAULT_CONFIG | (d.config or {}) if d.simulated else {},
        "last_seen": d.last_seen,
        "online": is_online(d),
        "latest": _latest(session, d),
        "token": token,
        "note": note,
    }


def _refresh(session: Session, d: Device) -> str | None:
    """Top up a simulated device; returns a note if that was impossible."""
    try:
        top_up(session, d)
        session.commit()
    except WeatherUnavailable as exc:
        session.rollback()
        return str(exc)
    if KINDS[d.kind]["needs_field"] and d.simulated:
        f = session.get(FarmField, d.field_id) if d.field_id else None
        if f is None or f.sowing_date is None:
            return "Attach the device to a field with a sowing date to simulate it."
    return None


def _get(session: Session, device_id: str) -> Device:
    d = session.get(Device, device_id)
    if d is None:
        raise HTTPException(404, "Device not found")
    return d


@router.get("/devices/kinds", response_model=DeviceKinds)
def device_kinds(_: User = Depends(require("project:read"))) -> dict[str, Any]:
    return {"kinds": KINDS, "metrics": {k: list(v) for k, v in METRIC_UNITS.items()}, "default_config": DEFAULT_CONFIG}


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(
    farm_id: str | None = None, session: Session = Depends(get_session), _: User = Depends(require("project:read"))
) -> list[dict[str, Any]]:
    q = select(Device).order_by(Device.name)
    if farm_id:
        q = q.where(Device.farm_id == farm_id)
    out = []
    for d in session.scalars(q).all():
        note = _refresh(session, d)
        out.append(_out(session, d, note=note))
    return out


@router.post("/farms/{farm_id}/devices", response_model=DeviceOut, status_code=201)
def create_device(
    farm_id: str,
    body: DeviceIn,
    session: Session = Depends(get_session),
    user: User = Depends(require("project:write")),
) -> dict[str, Any]:
    if session.get(Farm, farm_id) is None:
        raise HTTPException(404, "Farm not found")
    if body.field_id:
        f = session.get(FarmField, body.field_id)
        if f is None or f.farm_id != farm_id:
            raise HTTPException(422, "The field does not belong to this farm")
    elif KINDS[body.kind]["needs_field"]:
        raise HTTPException(422, f"A {KINDS[body.kind]['label'].lower()} must be attached to a field")
    token, token_hash = (None, "") if body.simulated else new_token()
    d = Device(
        farm_id=farm_id,
        name=body.name,
        kind=body.kind,
        field_id=body.field_id,
        latitude=body.latitude,
        longitude=body.longitude,
        simulated=body.simulated,
        interval_min=body.interval_min,
        config=body.config.model_dump() if body.simulated else {},
        token_hash=token_hash,
    )
    session.add(d)
    session.flush()
    audit(session, user, "device.create", "device", d.id, kind=d.kind, simulated=d.simulated)
    session.commit()
    note = _refresh(session, d) if d.simulated else None
    return _out(session, d, token=token, note=note)


@router.patch("/devices/{device_id}", response_model=DeviceOut)
def update_device(
    device_id: str,
    body: DevicePatch,
    session: Session = Depends(get_session),
    user: User = Depends(require("project:write")),
) -> dict[str, Any]:
    d = _get(session, device_id)
    changes = body.model_dump(exclude_unset=True)
    regenerate = d.simulated and any(k in changes for k in ("config", "field_id", "interval_min"))
    for k, v in changes.items():
        setattr(d, k, v)
    if regenerate:  # simulated history depends on these settings: rebuild it
        session.query(Reading).filter(Reading.device_id == d.id).delete()
        d.last_seen = None
    audit(session, user, "device.update", "device", d.id, fields=sorted(changes))
    session.commit()
    note = _refresh(session, d)
    return _out(session, d, note=note)


@router.delete("/devices/{device_id}", status_code=204)
def delete_device(
    device_id: str, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> None:
    d = _get(session, device_id)
    session.query(Reading).filter(Reading.device_id == d.id).delete()
    session.delete(d)
    audit(session, user, "device.delete", "device", device_id)
    session.commit()


@router.post("/devices/{device_id}/token", response_model=DeviceOut)
def reset_token(
    device_id: str, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> dict[str, Any]:
    d = _get(session, device_id)
    if d.simulated:
        raise HTTPException(422, "Simulated devices do not use tokens")
    token, d.token_hash = new_token()
    audit(session, user, "device.token_reset", "device", d.id)
    session.commit()
    return _out(session, d, token=token)


@router.get("/devices/{device_id}/readings", response_model=ReadingsOut)
def device_readings(
    device_id: str,
    metric: str,
    start: datetime | None = None,
    end: datetime | None = None,
    max_points: int = Query(600, ge=10, le=5000),
    session: Session = Depends(get_session),
    _: User = Depends(require("project:read")),
) -> dict[str, Any]:
    d = _get(session, device_id)
    _refresh(session, d)
    end = end or datetime.now(UTC)
    start = start or end - timedelta(days=14)
    rows = session.execute(
        select(Reading.ts, Reading.value, Reading.origin)
        .where(Reading.device_id == d.id, Reading.metric == metric, Reading.ts >= start, Reading.ts <= end)
        .order_by(Reading.ts)
    ).all()
    label, unit = METRIC_UNITS.get(metric, (metric, ""))
    points: list[dict[str, Any]] = []
    if rows:
        size = max(1, -(-len(rows) // max_points))  # readings per bucket
        for i in range(0, len(rows), size):
            chunk = rows[i : i + size]
            vals = [r.value for r in chunk]
            points.append(
                {
                    "ts": chunk[len(chunk) // 2].ts,
                    "value": sum(vals) / len(vals),
                    "min": min(vals),
                    "max": max(vals),
                    "count": len(vals),
                }
            )
    return {
        "device_id": d.id,
        "metric": metric,
        "label": label,
        "unit": unit,
        "origin": rows[-1].origin if rows else None,
        "points": points,
        "total": len(rows),
    }


@router.post("/ingest", response_model=IngestOut, tags=["ingest"])
def ingest(
    body: IngestIn,
    x_device_token: str = Header(..., description="The device's token"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """For real devices: store readings authenticated by the device token (no user login)."""
    d = session.get(Device, body.device_id)
    if (
        d is None
        or d.simulated
        or not d.token_hash
        or not hmac.compare_digest(hash_token(x_device_token), d.token_hash)
    ):
        raise HTTPException(401, "Unknown device or wrong token")
    allowed = set(KINDS[d.kind]["metrics"])
    now = datetime.now(UTC)
    stored = dup = 0
    for r in body.readings:
        if r.metric not in allowed:
            raise HTTPException(
                422, f"A {KINDS[d.kind]['label'].lower()} reports {', '.join(sorted(allowed)) or 'nothing'}"
            )
        ts = (r.ts or now).astimezone(UTC)
        exists = session.scalar(
            select(Reading.id).where(Reading.device_id == d.id, Reading.metric == r.metric, Reading.ts == ts)
        )
        if exists:
            dup += 1
            continue
        session.add(Reading(device_id=d.id, ts=ts, metric=r.metric, value=r.value, origin="real"))
        stored += 1
        d.last_seen = max(d.last_seen.replace(tzinfo=UTC) if d.last_seen else ts, ts)
    session.commit()
    return {"stored": stored, "duplicates": dup}


# --- digital twin -----------------------------------------------------------------------------------


class TwinField(BaseModel):
    id: str
    name: str
    boundary: list[list[float]]
    area_ha: float
    crop: str
    sowing_date: str | None
    available_fraction: float | None
    action: str | None
    advice: str | None
    stress: bool | None
    sensors: int
    error: str | None


class TwinFarm(BaseModel):
    id: str
    name: str
    latitude: float
    longitude: float
    fields: list[TwinField]
    devices: list[DeviceOut]


class TwinOut(BaseModel):
    source: str
    farms: list[TwinFarm]
    generated_at: datetime


@router.get("/twin", response_model=TwinOut)
def digital_twin(
    source: Literal["open_meteo", "csv", "synthetic"] = "open_meteo",
    use_sensors: bool = True,
    session: Session = Depends(get_session),
    _: User = Depends(require("project:read")),
) -> dict[str, Any]:
    from smartagri_api.routers.agro import compute_field_balance  # shared with the irrigation page

    farms = session.scalars(select(Farm).options(selectinload(Farm.fields)).order_by(Farm.name)).all()
    out = []
    for farm in farms:
        devices = session.scalars(select(Device).where(Device.farm_id == farm.id).order_by(Device.name)).all()
        dev_out = [_out(session, d, note=_refresh(session, d)) for d in devices]
        fields = []
        for f in farm.fields:
            item: dict[str, Any] = {
                "id": f.id,
                "name": f.name,
                "boundary": f.boundary,
                "area_ha": f.area_ha,
                "crop": f.crop,
                "sowing_date": f.sowing_date.isoformat() if f.sowing_date else None,
                "available_fraction": None,
                "action": None,
                "advice": None,
                "stress": None,
                "error": None,
                "sensors": sum(1 for d in devices if d.field_id == f.id and d.kind == "soil_moisture"),
            }
            if f.sowing_date:
                try:
                    wb = compute_field_balance(session, f, farm, source, use_sensors=use_sensors)
                    last = next((d for d in reversed(wb["days"]) if not d["forecast"]), None)
                    if last:
                        item["available_fraction"] = 1 - last["depletion"] / last["taw"] if last["taw"] else None
                        item["stress"] = last["ks"] < 1
                    item["action"] = wb["recommendation"].get("action")
                    item["advice"] = wb["recommendation"].get("text")
                except HTTPException as exc:
                    item["error"] = exc.detail
            fields.append(item)
        out.append(
            {
                "id": farm.id,
                "name": farm.name,
                "latitude": farm.latitude,
                "longitude": farm.longitude,
                "fields": fields,
                "devices": dev_out,
            }
        )
    return {"source": source, "farms": out, "generated_at": datetime.now(UTC)}
