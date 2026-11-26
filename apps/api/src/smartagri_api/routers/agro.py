"""Farms, fields, weather and FAO-56 irrigation scheduling."""

from __future__ import annotations

import dataclasses
import math
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator
from smartagri_core.agro.fao56 import CROPS, SOILS, IrrigationPolicy, recommendation, water_balance
from smartagri_core.agro.weather import CSV_COLUMNS, parse_weather_csv, to_balance_weather, with_et0
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from smartagri_api.db import get_session
from smartagri_api.deps import audit, require
from smartagri_api.models import Farm, FarmField, Project, User, WeatherRecord
from smartagri_api.weather_service import SOURCE_INFO, Source, WeatherUnavailable, get_weather, location_key, store

router = APIRouter(tags=["agro"])

IRRIGATION_METHODS = {"surface": 0.60, "sprinkler": 0.75, "drip": 0.90}  # typical application efficiencies


# --- schemas ----------------------------------------------------------------------------------------


class FarmIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    elevation_m: float = Field(0.0, ge=-500, le=9000)
    region: str = ""
    project_id: str | None = None


class FarmPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    elevation_m: float | None = Field(None, ge=-500, le=9000)
    region: str | None = None


class FieldIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    boundary: list[list[float]] = Field(default_factory=list, description="[[lon, lat], ...]")
    crop: str = "wheat"
    sowing_date: date | None = None
    stages: list[int] | None = None
    soil: str = "loam"
    root_depth_m: float | None = Field(None, gt=0, le=5)
    irrigation_method: Literal["surface", "sprinkler", "drip"] = "surface"
    efficiency: float | None = Field(None, gt=0, le=1)
    rainfed: bool = False
    notes: str = ""

    @field_validator("crop")
    @classmethod
    def _crop(cls, v: str) -> str:
        if v not in CROPS:
            raise ValueError(f"Unknown crop; choose one of {', '.join(CROPS)}")
        return v

    @field_validator("soil")
    @classmethod
    def _soil(cls, v: str) -> str:
        if v not in SOILS:
            raise ValueError(f"Unknown soil; choose one of {', '.join(SOILS)}")
        return v

    @field_validator("stages")
    @classmethod
    def _stages(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and (len(v) != 4 or any(x < 1 or x > 400 for x in v)):
            raise ValueError("Give four stage lengths (initial, development, mid, late) of 1-400 days")
        return v

    @field_validator("boundary")
    @classmethod
    def _boundary(cls, v: list[list[float]]) -> list[list[float]]:
        if v and (len(v) < 3 or any(len(p) != 2 or not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90) for p in v)):
            raise ValueError("A boundary needs at least 3 points of [longitude, latitude]")
        return v


class FieldPatch(FieldIn):
    name: str | None = Field(None, min_length=1, max_length=200)  # type: ignore[assignment]
    crop: str | None = None  # type: ignore[assignment]
    soil: str | None = None  # type: ignore[assignment]
    irrigation_method: Literal["surface", "sprinkler", "drip"] | None = None  # type: ignore[assignment]
    rainfed: bool | None = None  # type: ignore[assignment]
    boundary: list[list[float]] | None = None  # type: ignore[assignment]
    notes: str | None = None  # type: ignore[assignment]


class FieldOut(BaseModel):
    id: str
    farm_id: str
    name: str
    boundary: list[list[float]]
    area_ha: float
    crop: str
    sowing_date: date | None
    stages: list[int] | None
    soil: str
    root_depth_m: float | None
    irrigation_method: str
    efficiency: float
    rainfed: bool
    notes: str
    updated_at: str


class FarmOut(BaseModel):
    id: str
    name: str
    description: str
    latitude: float
    longitude: float
    elevation_m: float
    region: str
    project_id: str | None
    fields: list[FieldOut]
    total_area_ha: float
    updated_at: str


class CropOut(BaseModel):
    key: str
    name: str
    kc_ini: float
    kc_mid: float
    kc_end: float
    stages: list[int]
    root_depth_m: float
    p: float
    ky: float | None


class SoilOut(BaseModel):
    key: str
    name: str
    field_capacity: float
    wilting_point: float
    taw_per_m: float


class AgroPresets(BaseModel):
    crops: list[CropOut]
    soils: list[SoilOut]
    irrigation_methods: dict[str, float]
    csv_columns: dict[str, str]
    weather_sources: dict[str, list[str]]


class WeatherDayOut(BaseModel):
    day: date
    tmax: float
    tmin: float
    rain: float
    rh_max: float | None
    rh_min: float | None
    rh_mean: float | None
    wind_2m: float | None
    rs: float | None
    et0: float
    et0_reference: float | None
    radiation_estimated: bool
    forecast: bool


class WeatherOut(BaseModel):
    farm_id: str
    source: str
    data_origin: str
    source_description: str
    days: list[WeatherDayOut]
    et0_mean_abs_difference: float | None = Field(
        description="Mean |our ET0 - provider ET0| over days where the provider reports ET0"
    )


class CsvImportOut(BaseModel):
    imported: int
    errors: list[str]


class BalanceDayOut(BaseModel):
    day: date
    stage_day: int
    et0: float
    kc: float
    etc: float
    etc_adj: float
    ks: float
    rain: float
    effective_rain: float
    irrigation_net: float
    irrigation_gross: float
    deep_percolation: float
    depletion: float
    taw: float
    raw: float
    p: float
    forecast: bool
    model_depletion: float | None = None
    correction: float = 0.0


class WaterBalanceOut(BaseModel):
    field_id: str
    field_name: str
    crop: CropOut
    soil: SoilOut
    root_depth_m: float
    efficiency: float
    rainfed: bool
    season_start: date
    season_end: date
    source: str
    data_origin: str
    source_description: str
    days: list[BalanceDayOut]
    summary: dict[str, float | int | None]
    recommendation: dict[str, Any]
    assumptions: list[str]
    sensors_used: int = Field(0, description="Soil-moisture sensors whose readings corrected the model")


# --- helpers ----------------------------------------------------------------------------------------


def polygon_area_ha(boundary: list[list[float]]) -> float:
    """Area of a small lon/lat polygon: equal-area projection about its centroid, shoelace formula."""
    if len(boundary) < 3:
        return 0.0
    lat0 = math.radians(sum(p[1] for p in boundary) / len(boundary))
    r = 6371008.8
    pts = [(math.radians(lon) * r * math.cos(lat0), math.radians(lat) * r) for lon, lat in boundary]
    s = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1], strict=True))
    return abs(s) / 2 / 10_000


def _field_out(f: FarmField) -> dict[str, Any]:
    return {c: getattr(f, c) for c in FieldOut.model_fields if c != "updated_at"} | {
        "updated_at": f.updated_at.isoformat()
    }


def _farm_out(farm: Farm) -> dict[str, Any]:
    fields = [_field_out(f) for f in farm.fields]
    return {
        "id": farm.id,
        "name": farm.name,
        "description": farm.description,
        "latitude": farm.latitude,
        "longitude": farm.longitude,
        "elevation_m": farm.elevation_m,
        "region": farm.region,
        "project_id": farm.project_id,
        "fields": fields,
        "total_area_ha": sum(f["area_ha"] for f in fields),
        "updated_at": farm.updated_at.isoformat(),
    }


def _crop_out(c: Any) -> dict[str, Any]:
    return dataclasses.asdict(c) | {"stages": list(c.stages)}


def _soil_out(s: Any) -> dict[str, Any]:
    return dataclasses.asdict(s) | {"taw_per_m": s.taw_per_m}


def _get_farm(session: Session, farm_id: str) -> Farm:
    farm = session.get(Farm, farm_id, options=[selectinload(Farm.fields)])
    if farm is None:
        raise HTTPException(404, "Farm not found")
    return farm


def _get_field(session: Session, field_id: str) -> FarmField:
    f = session.get(FarmField, field_id)
    if f is None:
        raise HTTPException(404, "Field not found")
    return f


def _weather(session: Session, farm: Farm, start: date, end: date, source: Source, seed: int) -> list[Any]:
    try:
        return get_weather(session, farm, start, end, source, seed=seed)
    except WeatherUnavailable as exc:
        raise HTTPException(502, str(exc)) from None


# --- routes -----------------------------------------------------------------------------------------


@router.get("/agro/presets", response_model=AgroPresets)
def presets(_: User = Depends(require("project:read"))) -> dict[str, Any]:
    return {
        "crops": [_crop_out(c) for c in CROPS.values()],
        "soils": [_soil_out(s) for s in SOILS.values()],
        "irrigation_methods": IRRIGATION_METHODS,
        "csv_columns": CSV_COLUMNS,
        "weather_sources": {k: list(v) for k, v in SOURCE_INFO.items()},
    }


@router.get("/farms", response_model=list[FarmOut])
def list_farms(
    session: Session = Depends(get_session), _: User = Depends(require("project:read"))
) -> list[dict[str, Any]]:
    farms = session.scalars(select(Farm).options(selectinload(Farm.fields)).order_by(Farm.name))
    return [_farm_out(f) for f in farms]


@router.post("/farms", response_model=FarmOut, status_code=201)
def create_farm(
    body: FarmIn, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> dict[str, Any]:
    if body.project_id and session.get(Project, body.project_id) is None:
        raise HTTPException(404, "Project not found")
    farm = Farm(**body.model_dump(), created_by=user.id)
    session.add(farm)
    session.flush()
    audit(session, user, "farm.create", "farm", farm.id)
    session.commit()
    return _farm_out(_get_farm(session, farm.id))


@router.get("/farms/{farm_id}", response_model=FarmOut)
def get_farm(
    farm_id: str, session: Session = Depends(get_session), _: User = Depends(require("project:read"))
) -> dict[str, Any]:
    return _farm_out(_get_farm(session, farm_id))


@router.patch("/farms/{farm_id}", response_model=FarmOut)
def update_farm(
    farm_id: str,
    body: FarmPatch,
    session: Session = Depends(get_session),
    user: User = Depends(require("project:write")),
) -> dict[str, Any]:
    farm = _get_farm(session, farm_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(farm, k, v)
    audit(session, user, "farm.update", "farm", farm.id)
    session.commit()
    return _farm_out(_get_farm(session, farm_id))


@router.delete("/farms/{farm_id}", status_code=204)
def delete_farm(
    farm_id: str, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> None:
    farm = _get_farm(session, farm_id)
    session.execute(delete(WeatherRecord).where(WeatherRecord.location_key == f"farm:{farm.id}"))
    session.delete(farm)
    audit(session, user, "farm.delete", "farm", farm_id, name=farm.name)
    session.commit()


@router.post("/farms/{farm_id}/fields", response_model=FieldOut, status_code=201)
def create_field(
    farm_id: str, body: FieldIn, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> dict[str, Any]:
    _get_farm(session, farm_id)
    data = body.model_dump()
    data["efficiency"] = data["efficiency"] or IRRIGATION_METHODS[body.irrigation_method]
    f = FarmField(farm_id=farm_id, **data, area_ha=polygon_area_ha(body.boundary))
    session.add(f)
    session.flush()
    audit(session, user, "field.create", "field", f.id)
    session.commit()
    return _field_out(f)


@router.patch("/fields/{field_id}", response_model=FieldOut)
def update_field(
    field_id: str,
    body: FieldPatch,
    session: Session = Depends(get_session),
    user: User = Depends(require("project:write")),
) -> dict[str, Any]:
    f = _get_field(session, field_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(f, k, v)
    if "boundary" in changes:
        f.area_ha = polygon_area_ha(f.boundary or [])
    if "irrigation_method" in changes and "efficiency" not in changes:
        f.efficiency = IRRIGATION_METHODS[f.irrigation_method]
    audit(session, user, "field.update", "field", f.id, fields=sorted(changes))
    session.commit()
    return _field_out(f)


@router.delete("/fields/{field_id}", status_code=204)
def delete_field(
    field_id: str, session: Session = Depends(get_session), user: User = Depends(require("project:write"))
) -> None:
    f = _get_field(session, field_id)
    session.delete(f)
    audit(session, user, "field.delete", "field", field_id)
    session.commit()


@router.get("/farms/{farm_id}/weather", response_model=WeatherOut)
def farm_weather(
    farm_id: str,
    start: date | None = None,
    end: date | None = None,
    source: Source = "open_meteo",
    seed: int = Query(1, ge=0),
    session: Session = Depends(get_session),
    _: User = Depends(require("project:read")),
) -> dict[str, Any]:
    farm = _get_farm(session, farm_id)
    today = date.today()
    end = end or today + timedelta(days=7)
    start = start or end - timedelta(days=60)
    if start > end or (end - start).days > 3 * 366:
        raise HTTPException(422, "Choose a date range of up to three years with start before end")
    days = _weather(session, farm, start, end, source, seed)
    rows, diffs = [], []
    for w, et0, estimated in with_et0(days, farm.latitude, farm.elevation_m):
        if w.et0_reference is not None:
            diffs.append(abs(et0 - w.et0_reference))
        rows.append(
            {
                **w.to_dict(),
                "day": w.day,
                "et0": et0,
                "radiation_estimated": estimated,
                "forecast": w.forecast or w.day > today,
            }
        )
    origin, description = SOURCE_INFO[source]
    return {
        "farm_id": farm.id,
        "source": source,
        "data_origin": origin,
        "source_description": description,
        "days": rows,
        "et0_mean_abs_difference": sum(diffs) / len(diffs) if diffs else None,
    }


@router.post("/farms/{farm_id}/weather/csv", response_model=CsvImportOut)
async def import_weather_csv(
    farm_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: User = Depends(require("project:write")),
) -> dict[str, Any]:
    farm = _get_farm(session, farm_id)
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    try:
        days, errors = parse_weather_csv(text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not days:
        raise HTTPException(422, "No valid rows. " + " ".join(errors[:5]))
    store(session, location_key(farm, "csv"), "csv", days)
    audit(session, user, "weather.import", "farm", farm.id, rows=len(days), file=file.filename)
    session.commit()
    return {"imported": len(days), "errors": errors[:50]}


def compute_field_balance(
    session: Session,
    f: FarmField,
    farm: Farm,
    source: Source,
    *,
    seed: int = 1,
    trigger: float | None = None,
    use_sensors: bool = False,
) -> dict[str, Any]:
    """The FAO-56 water balance of a field for its season to date plus the forecast (shared with the twin)."""
    from smartagri_api.device_service import field_observations

    if f.sowing_date is None:
        raise HTTPException(422, "Set the field's sowing date to compute its water balance")
    crop = CROPS[f.crop]
    if f.stages:
        crop = dataclasses.replace(crop, stages=tuple(f.stages))
    soil = SOILS[f.soil]
    today = date.today()
    start = f.sowing_date
    season_end = start + timedelta(days=crop.season_days - 1)
    if start > today + timedelta(days=7):
        raise HTTPException(422, "The season has not started yet: the sowing date is more than a week away")
    end = min(season_end, today + timedelta(days=7))
    days = _weather(session, farm, start, end, source, seed)
    days = [dataclasses.replace(d, forecast=d.forecast or d.day > today) for d in days]
    observations, sensors = ({}, 0)
    if use_sensors:
        try:
            observations, sensors = field_observations(session, f, farm)
        except WeatherUnavailable as exc:
            raise HTTPException(502, f"Couldn't simulate the field's sensors: {exc}") from None
    policy = IrrigationPolicy(rainfed=f.rainfed, trigger=trigger, efficiency=f.efficiency)
    result = water_balance(
        to_balance_weather(days, farm.latitude, farm.elevation_m),
        crop,
        soil,
        start,
        root_depth_m=f.root_depth_m,
        policy=policy,
        observations=observations or None,
    )
    origin, description = SOURCE_INFO[source]
    assumptions = [
        "FAO-56 single crop coefficient; ET0 by FAO Penman-Monteith from the weather data.",
        "The soil starts the season at field capacity (after a pre-sowing irrigation).",
        "Fixed root depth; no capillary rise; rain below 20% of ET0 is lost to interception; water above "
        "field capacity drains the same day.",
        "Irrigation refills the root zone to field capacity when depletion reaches the trigger "
        "(by default the crop's p, the onset of water stress).",
        "Relative yield uses the FAO-33 seasonal yield response factor Ky where one is published.",
    ]
    if sensors:
        assumptions.append(
            "Sensor correction: on each day with readings, the modelled depletion is replaced by the one derived from "
            "the mean soil moisture after 21:00 (all of the field's sensors), using field capacity and root depth."
        )
    return {
        "field_id": f.id,
        "field_name": f.name,
        "crop": _crop_out(crop),
        "soil": _soil_out(soil),
        "root_depth_m": f.root_depth_m or crop.root_depth_m,
        "efficiency": f.efficiency,
        "rainfed": f.rainfed,
        "season_start": start,
        "season_end": season_end,
        "source": source,
        "data_origin": "derived" if origin == "real" else "synthetic",
        "source_description": description,
        "days": [dataclasses.asdict(d) for d in result.days],
        "summary": result.summary(crop),
        "recommendation": recommendation(result, policy),
        "assumptions": assumptions,
        "sensors_used": sensors,
    }


@router.get("/fields/{field_id}/water-balance", response_model=WaterBalanceOut)
def field_water_balance(
    field_id: str,
    source: Source = "open_meteo",
    seed: int = Query(1, ge=0),
    trigger: float | None = Query(None, gt=0, lt=1, description="Depletion fraction that triggers irrigation"),
    use_sensors: bool = Query(False, description="Correct the model with the field's soil-moisture sensors"),
    session: Session = Depends(get_session),
    _: User = Depends(require("project:read")),
) -> dict[str, Any]:
    f = _get_field(session, field_id)
    farm = _get_farm(session, f.farm_id)
    return compute_field_balance(session, f, farm, source, seed=seed, trigger=trigger, use_sensors=use_sensors)
