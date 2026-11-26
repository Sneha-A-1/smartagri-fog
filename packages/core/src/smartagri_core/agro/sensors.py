"""Simulated field devices driven by the FAO-56 water balance, and conversion of sensor readings.

A simulated soil-moisture sensor reports the volumetric water content of a "true" field. The truth is a water
balance like the model's but with a different crop water use (``et_multiplier``), because in practice the FAO-56
coefficients rarely match a particular field exactly. The sensor adds measurement noise and bias and can drop
readings. Comparing model-only and sensor-corrected irrigation on such a field is a controlled experiment of
the value of sensing. All values are synthetic and labelled as such.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from smartagri_core.agro.fao56 import BalanceDay, Crop, DayWeather, IrrigationPolicy, Soil, water_balance
from smartagri_core.agro.weather import WeatherDay


@dataclass(frozen=True)
class SensorModel:
    noise_sd: float = 0.01  # m3/m3, typical of low-cost capacitive probes after calibration
    bias: float = 0.0  # m3/m3
    dropout: float = 0.0  # probability that a reading is missing
    et_multiplier: float = 1.15  # true crop water use relative to the FAO-56 model


def theta_from_depletion(depletion_mm: float, soil: Soil, root_depth_m: float) -> float:
    """Volumetric water content (m3/m3) averaged over the root zone."""
    return soil.field_capacity - depletion_mm / (1000 * root_depth_m)


def depletion_from_theta(theta: float, soil: Soil, root_depth_m: float) -> float:
    taw = soil.taw_per_m * root_depth_m
    return min(max((soil.field_capacity - theta) * 1000 * root_depth_m, 0.0), taw)


def _rng(key: str, ts: datetime) -> random.Random:
    """Deterministic per (device, time): regenerating a period always gives the same readings."""
    digest = hashlib.sha256(f"{key}|{ts.isoformat()}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def true_balance(
    weather: list[DayWeather],
    crop: Crop,
    soil: Soil,
    sowing: date,
    root_depth_m: float,
    policy: IrrigationPolicy,
    model: SensorModel,
) -> list[BalanceDay]:
    truth_weather = [DayWeather(w.day, w.et0 * model.et_multiplier, w.rain, w.forecast) for w in weather]
    observed = [w for w in truth_weather if not w.forecast]
    return water_balance(observed, crop, soil, sowing, root_depth_m=root_depth_m, policy=policy).days


def _depletion_at(days: dict[date, BalanceDay], ts: datetime) -> float | None:
    """Depletion during a day: it rises with crop water use until 06:00, when the day's irrigation and rain are
    applied, then moves linearly to the day's end-of-day value."""
    today = days.get(ts.date())
    if today is None:
        return None
    prev = days.get(ts.date() - timedelta(days=1))
    prev_end = prev.depletion if prev else 0.0
    minutes = ts.hour * 60 + ts.minute
    if minutes < 360:
        return prev_end + today.etc_adj * minutes / 1440
    at_six = max(0.0, prev_end + today.etc_adj * 0.25 - today.irrigation_net - today.effective_rain)
    return at_six + (today.depletion - at_six) * (minutes - 360) / 1080


def soil_moisture_readings(
    truth: list[BalanceDay],
    soil: Soil,
    root_depth_m: float,
    start: datetime,
    end: datetime,
    interval_min: int,
    model: SensorModel,
    key: str,
) -> list[tuple[datetime, float]]:
    by_day = {d.day: d for d in truth}
    out = []
    t = _align(start, interval_min)
    while t <= end:
        dr = _depletion_at(by_day, t)
        if dr is not None:
            rng = _rng(key, t)
            if rng.random() >= model.dropout:
                theta = theta_from_depletion(dr, soil, root_depth_m) + model.bias + rng.gauss(0, model.noise_sd)
                out.append((t, round(min(max(theta, 0.0), 0.6), 4)))
        t += timedelta(minutes=interval_min)
    return out


def valve_readings(
    truth: list[BalanceDay], start: datetime, end: datetime, application_mm_per_h: float = 5.0
) -> list[tuple[datetime, float]]:
    """Hourly valve state (1 open, 0 closed). On an irrigation day the valve opens at 06:00 and stays open for
    gross depth / application rate hours, continuing past midnight if needed."""
    windows = []
    for d in truth:
        if d.irrigation_gross > 0:
            opened = datetime.combine(d.day, time(6), tzinfo=start.tzinfo)
            windows.append((opened, opened + timedelta(hours=d.irrigation_gross / application_mm_per_h)))
    out = []
    t = _align(start, 60)
    while t <= end:
        out.append((t, 1.0 if any(a <= t < b for a, b in windows) else 0.0))
        t += timedelta(hours=1)
    return out


def weather_station_readings(
    days: list[WeatherDay], start: datetime, end: datetime, interval_min: int, key: str
) -> list[tuple[datetime, str, float]]:
    """Air temperature (sine between Tmin at 06:00 and Tmax at 15:00), relative humidity (from the daily range, or
    the daily mean) and rain (the daily total, reported at 16:00), with small sensor noise."""
    by_day = {d.day: d for d in days if not d.forecast}
    out = []
    t = _align(start, interval_min)
    while t <= end:
        w = by_day.get(t.date())
        if w:
            h = t.hour + t.minute / 60
            phase = (
                (math.cos(math.pi * (h - 15) / 9) + 1) / 2
                if 6 <= h <= 24
                else (math.cos(math.pi * (h + 9) / 15) + 1) / 2
            )
            temp = w.tmin + (w.tmax - w.tmin) * phase
            if w.rh_min is not None and w.rh_max is not None:
                rh = w.rh_max - (w.rh_max - w.rh_min) * phase
            else:
                rh = (w.rh_mean or 60.0) + 15 * (0.5 - phase)
            rng = _rng(key, t)
            out.append((t, "air_temperature_c", round(temp + rng.gauss(0, 0.2), 2)))
            out.append((t, "relative_humidity_pct", round(min(100.0, max(1.0, rh + rng.gauss(0, 1.0))), 1)))
            if t.hour == 16 and t.minute < interval_min:
                out.append((t, "rain_mm", round(w.rain, 1)))
        t += timedelta(minutes=interval_min)
    return out


def _diurnal(hour: float) -> float:
    """0 at 06:00 (coolest), 1 at 15:00 (warmest), smooth in between."""
    if 6 <= hour <= 15:
        return (1 - math.cos(math.pi * (hour - 6) / 9)) / 2
    since = (hour - 15) % 24  # 0..15 hours after the maximum
    return (1 + math.cos(math.pi * since / 15)) / 2


def daily_depletion_observations(
    readings: list[tuple[datetime, float]], soil: Soil, root_depth_m: float
) -> dict[date, float]:
    """End-of-day depletion per day: mean of the readings from 21:00 onwards (the last three hours)."""
    late: dict[date, list[float]] = {}
    for ts, theta in readings:
        if ts.hour >= 21:
            late.setdefault(ts.date(), []).append(theta)
    return {d: depletion_from_theta(sum(v) / len(v), soil, root_depth_m) for d, v in late.items()}


def _align(t: datetime, interval_min: int) -> datetime:
    minutes = (t.hour * 60 + t.minute + interval_min - 1) // interval_min * interval_min
    return datetime.combine(t.date(), time(0), tzinfo=t.tzinfo) + timedelta(minutes=minutes)


# --- closed-loop experiment -------------------------------------------------------------------------

STRATEGIES = {
    "model": "FAO-56 model only",
    "sensor": "Model replaced by the soil-moisture reading each evening",
    "fused": "Model and sensor combined by a Kalman filter",
    "oracle": "Perfect knowledge of the field (upper bound)",
}


def closed_loop_season(
    weather: list[DayWeather],
    crop: Crop,
    soil: Soil,
    sowing: date,
    root_depth_m: float,
    policy: IrrigationPolicy,
    model: SensorModel,
    strategy: str,
    key: str,
    process_cv: float = 0.25,
) -> dict[str, float]:
    """One season in which irrigation is decided from the farmer's belief and applied to the true field.

    The belief follows the FAO-56 model (``model``), is reset each evening to a noisy sensor reading of the
    truth (``sensor``), combines the two with a one-dimensional Kalman filter (``fused``: the model's variance
    grows by ``(process_cv * ETc)^2`` per day, the sensor's variance is its noise converted to mm), or equals
    the truth (``oracle``). The farmer irrigates when the believed depletion
    reaches the trigger, applying the believed depletion. Outcomes are measured on the true field.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}")
    from smartagri_core.agro.fao56 import adjusted_p, day_step  # local import keeps the public API small

    taw = soil.taw_per_m * root_depth_m
    true_dr = belief = 0.0
    variance = 0.0  # Kalman filter: variance of the belief, mm^2 (the season starts at field capacity, known)
    obs_variance = (model.noise_sd * 1000 * root_depth_m) ** 2
    tot = {"etc": 0.0, "eta": 0.0, "irr_net": 0.0, "dp": 0.0, "stress": 0, "events": 0, "abs_error": 0.0, "days": 0}
    for w in sorted((x for x in weather if not x.forecast), key=lambda x: x.day):
        n = (w.day - sowing).days
        if n < 0:
            continue
        if n >= crop.season_days:
            break
        p = adjusted_p(crop.p, crop.kc(n) * w.et0)
        trigger = (policy.trigger if policy.trigger is not None else p) * taw
        irr = belief if (not policy.rainfed and belief >= trigger and belief > 0) else 0.0
        truth = day_step(true_dr, DayWeather(w.day, w.et0 * model.et_multiplier, w.rain), crop, n, taw, policy, irr)
        modelled = day_step(belief, w, crop, n, taw, policy, irr)
        true_dr = truth.depletion
        if strategy == "oracle":
            belief = true_dr
        elif strategy in ("sensor", "fused"):
            rng = _rng(key, datetime.combine(w.day, time(23)))
            reading = None
            if rng.random() >= model.dropout:
                theta = theta_from_depletion(true_dr, soil, root_depth_m) + model.bias + rng.gauss(0, model.noise_sd)
                reading = depletion_from_theta(theta, soil, root_depth_m)
            if strategy == "sensor":
                belief = reading if reading is not None else modelled.depletion
            else:
                variance += (process_cv * modelled.etc) ** 2
                belief = modelled.depletion
                if reading is not None:
                    gain = variance / (variance + obs_variance) if variance + obs_variance > 0 else 0.0
                    belief = min(max(belief + gain * (reading - belief), 0.0), taw)
                    variance *= 1 - gain
        else:
            belief = modelled.depletion
        tot["etc"] += truth.etc
        tot["eta"] += truth.etc_adj
        tot["irr_net"] += irr
        tot["dp"] += truth.deep_percolation
        tot["stress"] += truth.ks < 1
        tot["events"] += irr > 0
        tot["abs_error"] += abs(belief - true_dr)
        tot["days"] += 1
    rel = 1 - crop.ky * (1 - tot["eta"] / tot["etc"]) if crop.ky is not None and tot["etc"] > 0 else None
    return {
        "relative_yield": max(0.0, rel) if rel is not None else math.nan,
        "stress_days": float(tot["stress"]),
        "irrigation_gross_mm": tot["irr_net"] / policy.efficiency,
        "irrigation_events": float(tot["events"]),
        "deep_percolation_mm": tot["dp"],
        "belief_error_mm": tot["abs_error"] / max(tot["days"], 1),
    }
