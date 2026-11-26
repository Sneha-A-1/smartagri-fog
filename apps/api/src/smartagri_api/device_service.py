"""Simulated device readings (generated on demand up to the current time) and helpers for real devices."""

from __future__ import annotations

import dataclasses
import hashlib
import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Any

from smartagri_core.agro.fao56 import CROPS, SOILS, IrrigationPolicy
from smartagri_core.agro.sensors import (
    SensorModel,
    daily_depletion_observations,
    soil_moisture_readings,
    true_balance,
    valve_readings,
    weather_station_readings,
)
from smartagri_core.agro.weather import to_balance_weather
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from smartagri_api.models import Device, Farm, FarmField, Reading
from smartagri_api.weather_service import SOURCE_INFO, get_weather

KINDS: dict[str, dict[str, Any]] = {
    "soil_moisture": {"label": "Soil-moisture sensor", "metrics": ["soil_moisture_m3m3"], "needs_field": True},
    "weather_station": {
        "label": "Weather station",
        "metrics": ["air_temperature_c", "relative_humidity_pct", "rain_mm"],
        "needs_field": False,
    },
    "valve": {"label": "Irrigation valve", "metrics": ["valve_open"], "needs_field": True},
    "gateway": {"label": "Gateway (LoRa/WiFi)", "metrics": [], "needs_field": False},
}
METRIC_UNITS = {
    "soil_moisture_m3m3": ("Soil moisture", "m³/m³"),
    "air_temperature_c": ("Air temperature", "°C"),
    "relative_humidity_pct": ("Relative humidity", "%"),
    "rain_mm": ("Rain", "mm"),
    "valve_open": ("Valve open", "0/1"),
}
DEFAULT_CONFIG = {
    "weather_source": "open_meteo",
    "et_multiplier": 1.15,
    "noise_sd": 0.01,
    "bias": 0.0,
    "dropout": 0.02,
    "application_mm_per_h": 5.0,
}
MAX_HISTORY_DAYS = 400


def new_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(24)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def solar_offset(longitude: float) -> timedelta:
    """Local solar time offset from UTC, to the quarter hour. Simulated days follow the sun, not the time zone."""
    return timedelta(hours=round(longitude / 15 * 4) / 4)


def field_model(session: Session, f: FarmField) -> tuple[Any, Any, float, IrrigationPolicy]:
    crop = CROPS[f.crop]
    if f.stages:
        crop = dataclasses.replace(crop, stages=tuple(f.stages))
    return (
        crop,
        SOILS[f.soil],
        f.root_depth_m or crop.root_depth_m,
        IrrigationPolicy(rainfed=f.rainfed, efficiency=f.efficiency),
    )


def top_up(session: Session, device: Device, now: datetime | None = None) -> int:
    """Generate the simulated readings missing between the device's last reading and now. Returns rows added.

    Readings are a deterministic function of the device and the time, so a regenerated period is identical.
    Raises WeatherUnavailable if the configured weather source cannot be reached.
    """
    if not device.simulated or device.kind == "gateway":
        return 0
    now = now or datetime.now(UTC)
    offset = solar_offset(device.longitude)
    local_now = (now + offset).replace(tzinfo=None, second=0, microsecond=0)
    cfg = DEFAULT_CONFIG | (device.config or {})
    source = cfg["weather_source"]
    farm = session.get(Farm, device.farm_id)
    last = session.scalar(select(func.max(Reading.ts)).where(Reading.device_id == device.id))
    floor = local_now - timedelta(days=MAX_HISTORY_DAYS)

    field = session.get(FarmField, device.field_id) if device.field_id else None
    if KINDS[device.kind]["needs_field"]:
        if field is None or field.sowing_date is None:
            return 0
        start = datetime.combine(field.sowing_date, datetime.min.time())
    else:
        start = local_now - timedelta(days=30)
    if last is not None:
        last_local = (last if last.tzinfo else last.replace(tzinfo=UTC)) + offset
        start = last_local.replace(tzinfo=None) + timedelta(minutes=1)
    start = max(start, floor)
    if start > local_now:
        return 0

    rows: list[tuple[datetime, str, float]] = []
    if device.kind == "weather_station":
        days = get_weather(session, farm, start.date(), local_now.date(), source)
        rows = weather_station_readings(days, start, local_now, device.interval_min, key=device.id)
        origin = "derived" if SOURCE_INFO[source][0] == "real" else "synthetic"
    else:
        crop, soil, zr, policy = field_model(session, field)
        days = get_weather(session, farm, field.sowing_date, local_now.date(), source)
        truth = true_balance(
            to_balance_weather(days, farm.latitude, farm.elevation_m),
            crop,
            soil,
            field.sowing_date,
            zr,
            policy,
            _sensor_model(cfg),
        )
        if device.kind == "soil_moisture":
            rows = [
                (t, "soil_moisture_m3m3", v)
                for t, v in soil_moisture_readings(
                    truth, soil, zr, start, local_now, device.interval_min, _sensor_model(cfg), key=device.id
                )
            ]
        else:
            rows = [
                (t, "valve_open", v) for t, v in valve_readings(truth, start, local_now, cfg["application_mm_per_h"])
            ]
        origin = "synthetic"

    for t, metric, value in rows:
        session.add(
            Reading(device_id=device.id, ts=(t - offset).replace(tzinfo=UTC), metric=metric, value=value, origin=origin)
        )
    if rows:
        device.last_seen = (rows[-1][0] - offset).replace(tzinfo=UTC)
    session.flush()
    return len(rows)


def _sensor_model(cfg: dict[str, Any]) -> SensorModel:
    return SensorModel(
        noise_sd=float(cfg["noise_sd"]),
        bias=float(cfg["bias"]),
        dropout=float(cfg["dropout"]),
        et_multiplier=float(cfg["et_multiplier"]),
    )


def field_observations(session: Session, f: FarmField, farm: Farm) -> tuple[dict[date, float], int]:
    """End-of-day depletion per day from the field's soil-moisture sensors (all of them averaged)."""
    devices = list(session.scalars(select(Device).where(Device.field_id == f.id, Device.kind == "soil_moisture")))
    if not devices:
        return {}, 0
    for d in devices:
        top_up(session, d)
    session.commit()
    _, soil, zr, _ = field_model(session, f)
    offset = solar_offset(farm.longitude)
    readings = session.execute(
        select(Reading.ts, Reading.value).where(
            Reading.device_id.in_([d.id for d in devices]), Reading.metric == "soil_moisture_m3m3"
        )
    ).all()
    local = [((ts if ts.tzinfo else ts.replace(tzinfo=UTC)) + offset, v) for ts, v in readings]
    return daily_depletion_observations([(t.replace(tzinfo=None), v) for t, v in local], soil, zr), len(devices)


def is_online(device: Device, now: datetime | None = None) -> bool:
    if device.last_seen is None:
        return False
    now = now or datetime.now(UTC)
    seen = device.last_seen if device.last_seen.tzinfo else device.last_seen.replace(tzinfo=UTC)
    return now - seen <= timedelta(minutes=max(3 * device.interval_min, 10))
