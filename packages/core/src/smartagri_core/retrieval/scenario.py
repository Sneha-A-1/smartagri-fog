"""Synthetic farm scenarios with known ground truth, for evaluating retrieval strategies.

Each field has a soil-moisture probe; the farm has a weather station. True soil moisture comes from the FAO-56
water balance of each field, irrigated late (after stress has begun) so that stress events occur. True air
temperature follows a daily cycle from synthetic weather, with frost nights and heat days injected. Sensors add
noise, spikes, stuck episodes and missing readings. Because the truth is known, every alert can be checked.
All data is synthetic.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from pydantic import BaseModel, ConfigDict, Field

from smartagri_core.agro.fao56 import CROPS, SOILS, DayWeather, IrrigationPolicy, water_balance
from smartagri_core.agro.sensors import _depletion_at, theta_from_depletion
from smartagri_core.agro.weather import synthetic_weather, to_balance_weather
from smartagri_core.retrieval.framework import Stream

SOIL_METRIC = "soil_moisture_m3m3"
TEMP_METRIC = "air_temperature_c"


class ScenarioParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: int = Field(10, ge=1, le=200, description="Fields, each with one soil-moisture probe.")
    days: int = Field(20, ge=1, le=120, description="Length of the scenario.")
    interval_min: int = Field(15, ge=1, le=240, title="Sampling interval (minutes)")
    latitude: float = Field(28.6, ge=-60, le=60)
    start: date = Field(date(2026, 2, 10), description="First day (wheat is past mid-season then in north India).")
    crop: str = Field("wheat")
    soil_noise: float = Field(0.01, title="Soil probe noise (m3/m3)", ge=0, le=0.1)
    temp_noise: float = Field(0.3, title="Thermometer noise (deg C)", ge=0, le=5)
    spike_prob: float = Field(0.005, title="Spike probability per reading", ge=0, le=0.2)
    stuck_episodes: float = Field(
        0.3,
        title="Stuck episodes per stream",
        ge=0,
        le=10,
        description="Expected number of 6-hour stuck-sensor episodes per stream.",
    )
    dropout: float = Field(0.02, title="Missing readings", ge=0, le=0.5)
    frost_nights: int = Field(2, ge=0, le=30, description="Nights pushed below 2 deg C.")
    heat_days: int = Field(1, ge=0, le=30, description="Days pushed above 40 deg C.")
    seed: int = Field(1, ge=0)


@dataclass
class TrueEvent:
    stream: str
    name: str  # rule name (soil_stress, frost, heat) or fault (stuck)
    onset: float
    end: float


@dataclass
class Scenario:
    params: ScenarioParams
    streams: list[Stream]
    samples: dict[str, list[tuple[float, float | None]]]  # observed, per stream
    truth: dict[str, list[tuple[float, float]]]  # true values at sample times
    events: list[TrueEvent]
    horizon: float  # minutes
    start: datetime = field(default_factory=lambda: datetime(2026, 1, 1))


def _diurnal(hour: float) -> float:
    if 6 <= hour <= 15:
        return (1 - math.cos(math.pi * (hour - 6) / 9)) / 2
    since = (hour - 15) % 24
    return (1 + math.cos(math.pi * since / 15)) / 2


def _events_from_series(stream: str, name: str, series: list[tuple[float, float]], breached) -> list[TrueEvent]:
    out, onset = [], None
    for t, v in series:
        if breached(v) and onset is None:
            onset = t
        elif not breached(v) and onset is not None:
            out.append(TrueEvent(stream, name, onset, t))
            onset = None
    if onset is not None:
        out.append(TrueEvent(stream, name, onset, series[-1][0]))
    return out


def generate(p: ScenarioParams) -> Scenario:
    rng = random.Random(p.seed)
    crop = CROPS[p.crop]
    horizon = p.days * 1440.0
    times = [k * p.interval_min for k in range(int(horizon // p.interval_min))]
    start_dt = datetime.combine(p.start, time(0))
    end_day = p.start + timedelta(days=p.days)
    soils = list(SOILS.values())[2:7]  # sandy loam to silty clay loam: typical irrigated soils
    weather_days = synthetic_weather(p.latitude, p.start - timedelta(days=crop.season_days), end_day, seed=p.seed)
    balance_weather = to_balance_weather(weather_days, p.latitude, 220)

    streams: list[Stream] = []
    truth: dict[str, list[tuple[float, float]]] = {}
    events: list[TrueEvent] = []

    for f in range(p.fields):
        soil = rng.choice(soils)
        zr = crop.root_depth_m
        sowing = p.start - timedelta(days=rng.randint(55, 75))
        taw = soil.taw_per_m * zr
        # irrigate late: when depletion is well past the stress point, so stress episodes happen
        policy = IrrigationPolicy(trigger=min(0.95, crop.p + rng.uniform(0.08, 0.2)))
        days = water_balance(
            [DayWeather(w.day, w.et0, w.rain) for w in balance_weather],
            crop,
            soil,
            sowing,
            policy=policy,
            initial_depletion=rng.uniform(0, 0.5) * taw,
        ).days
        by_day = {d.day: d for d in days}
        stress_theta = theta_from_depletion(crop.p * taw, soil, zr)
        key = f"probe-{f + 1}:{SOIL_METRIC}"
        series = []
        for t in times:
            dt = start_dt + timedelta(minutes=t)
            dr = _depletion_at(by_day, dt)
            series.append((t, theta_from_depletion(dr if dr is not None else 0.0, soil, zr)))
        streams.append(
            Stream(
                key,
                f"probe-{f + 1}",
                SOIL_METRIC,
                f"field-{f + 1}",
                {"stress_theta": stress_theta, "wilting_theta": soil.wilting_point},
            )
        )
        truth[key] = series
        events += _events_from_series(key, "soil_stress", series, lambda v, s=stress_theta: v <= s)

    # weather station: daily cycle with injected frost nights and heat days
    wkey = f"station:{TEMP_METRIC}"
    by_day = {w.day: w for w in weather_days}
    day_list = [p.start + timedelta(days=k) for k in range(p.days)]
    frost = set(rng.sample(day_list, min(p.frost_nights, len(day_list))))
    heat = set(rng.sample([d for d in day_list if d not in frost], min(p.heat_days, len(day_list) - len(frost))))
    temps = []
    for t in times:
        dt = start_dt + timedelta(minutes=t)
        w = by_day[dt.date()]
        tmin, tmax = w.tmin, w.tmax
        if dt.date() in frost:
            tmin = -0.5 + (dt.toordinal() % 3) * 0.5
        if dt.date() in heat:
            tmax = 41.5 + (dt.toordinal() % 3) * 0.8
        h = dt.hour + dt.minute / 60
        temps.append((t, tmin + (tmax - tmin) * _diurnal(h)))
    streams.append(Stream(wkey, "station", TEMP_METRIC, "farm"))
    truth[wkey] = temps
    events += _events_from_series(wkey, "frost", temps, lambda v: v <= 2.0)
    events += _events_from_series(wkey, "heat", temps, lambda v: v >= 40.0)

    # sensors: noise, spikes, stuck episodes, missing readings
    samples: dict[str, list[tuple[float, float | None]]] = {}
    for s in streams:
        noise = p.soil_noise if s.metric == SOIL_METRIC else p.temp_noise
        spike = 0.15 if s.metric == SOIL_METRIC else 12.0
        n_stuck = int(p.stuck_episodes) + (1 if rng.random() < p.stuck_episodes % 1 else 0)
        stuck_windows = []
        for _ in range(n_stuck):
            a = rng.uniform(0, max(horizon - 360, 1))
            stuck_windows.append((a, a + 360))
            events.append(TrueEvent(s.key, "stuck", a, a + 360))
        obs: list[tuple[float, float | None]] = []
        frozen: float | None = None
        for t, v in truth[s.key]:
            in_stuck = any(a <= t < b for a, b in stuck_windows)
            if in_stuck:
                if frozen is None:
                    frozen = round(v + rng.gauss(0, noise), 4)
                obs.append((t, frozen))
                continue
            frozen = None
            if rng.random() < p.dropout:
                obs.append((t, None))
                continue
            x = v + rng.gauss(0, noise)
            if rng.random() < p.spike_prob:
                x += spike * (1 if rng.random() < 0.5 else -1)
            obs.append((t, round(x, 4)))
        samples[s.key] = obs
    return Scenario(p, streams, samples, truth, events, horizon, start_dt)
