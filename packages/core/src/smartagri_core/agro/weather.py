"""Daily weather: parsing Open-Meteo responses and CSV station files, a synthetic generator, and ET0.

No network code lives here (the core is headless and offline); the API layer downloads and passes JSON in.
"""

from __future__ import annotations

import csv
import io
import math
import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from smartagri_core.agro.fao56 import DayWeather, et0_penman_monteith, wind_at_2m


@dataclass(frozen=True)
class WeatherDay:
    day: date
    tmax: float
    tmin: float
    rain: float = 0.0
    rh_max: float | None = None
    rh_min: float | None = None
    rh_mean: float | None = None
    wind_2m: float | None = None  # m/s at 2 m
    rs: float | None = None  # MJ m-2 day-1
    sunshine_hours: float | None = None
    et0_reference: float | None = None  # ET0 reported by the data provider, for comparison
    forecast: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["day"] = self.day.isoformat()
        return d


# --- Open-Meteo -------------------------------------------------------------------------------------

OPEN_METEO_DAILY = (
    "temperature_2m_max,temperature_2m_min,precipitation_sum,shortwave_radiation_sum,et0_fao_evapotranspiration"
)
OPEN_METEO_HOURLY = "relative_humidity_2m,wind_speed_10m"


def open_meteo_url(lat: float, lon: float, start: date, end: date, *, today: date | None = None) -> str:
    """Archive API (ERA5 reanalysis) for dates older than ~60 days, forecast API otherwise (up to 16 days ahead)."""
    today = today or date.today()
    base = (
        "https://archive-api.open-meteo.com/v1/archive"
        if end < today - timedelta(days=60)
        else "https://api.open-meteo.com/v1/forecast"
    )
    return (
        f"{base}?latitude={lat:.4f}&longitude={lon:.4f}&start_date={start.isoformat()}&end_date={end.isoformat()}"
        f"&daily={OPEN_METEO_DAILY}&hourly={OPEN_METEO_HOURLY}&timezone=auto&wind_speed_unit=ms"
    )


def parse_open_meteo(payload: dict[str, Any], *, today: date | None = None) -> list[WeatherDay]:
    """Daily values from an Open-Meteo response. Humidity and wind are aggregated from hourly values (RH max/min,
    mean wind at 10 m converted to 2 m with FAO-56 eq. 47). Days after ``today`` are marked as forecast."""
    if payload.get("error"):
        raise ValueError(f"Open-Meteo error: {payload.get('reason', 'unknown')}")
    today = today or date.today()
    daily = payload["daily"]
    hourly = payload.get("hourly", {})
    rh: dict[str, list[float]] = defaultdict(list)
    wind: dict[str, list[float]] = defaultdict(list)
    for t, h, w in zip(
        hourly.get("time", []), hourly.get("relative_humidity_2m", []), hourly.get("wind_speed_10m", []), strict=False
    ):
        key = t[:10]
        if h is not None:
            rh[key].append(float(h))
        if w is not None:
            wind[key].append(float(w))
    out = []
    for i, d in enumerate(daily["time"]):
        tmax, tmin = daily["temperature_2m_max"][i], daily["temperature_2m_min"][i]
        if tmax is None or tmin is None:
            continue
        day = date.fromisoformat(d)
        hs, ws = rh.get(d, []), wind.get(d, [])
        out.append(
            WeatherDay(
                day=day,
                tmax=float(tmax),
                tmin=float(tmin),
                rain=float(daily.get("precipitation_sum", [0] * (i + 1))[i] or 0.0),
                rh_max=max(hs) if hs else None,
                rh_min=min(hs) if hs else None,
                wind_2m=wind_at_2m(sum(ws) / len(ws), 10) if ws else None,
                rs=_num(daily.get("shortwave_radiation_sum"), i),
                et0_reference=_num(daily.get("et0_fao_evapotranspiration"), i),
                forecast=day > today,
            )
        )
    return out


def _num(seq: list[Any] | None, i: int) -> float | None:
    if not seq or i >= len(seq) or seq[i] is None:
        return None
    return float(seq[i])


# --- CSV ---------------------------------------------------------------------------------------------

CSV_COLUMNS = {
    "date": "YYYY-MM-DD (required)",
    "tmax": "maximum temperature, deg C (required)",
    "tmin": "minimum temperature, deg C (required)",
    "rain": "rainfall, mm",
    "rh_max": "maximum relative humidity, %",
    "rh_min": "minimum relative humidity, %",
    "rh_mean": "mean relative humidity, %",
    "wind_2m": "mean wind speed at 2 m, m/s",
    "wind_10m": "mean wind speed at 10 m, m/s (converted to 2 m)",
    "rs": "solar radiation, MJ/m2/day",
    "sunshine_hours": "bright sunshine, hours",
}


def parse_weather_csv(text: str) -> tuple[list[WeatherDay], list[str]]:
    """Parse a station CSV with a header row (column names in ``CSV_COLUMNS``). Returns days and row errors."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or not {"date", "tmax", "tmin"} <= {f.strip().lower() for f in reader.fieldnames}:
        raise ValueError("The CSV needs a header row with at least date, tmax and tmin")
    days, errors = [], []
    for n, raw in enumerate(reader, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        f = _getter(row)
        try:
            wind = f("wind_2m")
            if wind is None and f("wind_10m") is not None:
                wind = wind_at_2m(f("wind_10m"), 10)
            tmax, tmin = f("tmax"), f("tmin")
            if tmax is None or tmin is None:
                raise ValueError("tmax and tmin are required")
            if tmin > tmax:
                raise ValueError("tmin is above tmax")
            days.append(
                WeatherDay(
                    date.fromisoformat(row["date"]),
                    tmax,
                    tmin,
                    f("rain") or 0.0,
                    f("rh_max"),
                    f("rh_min"),
                    f("rh_mean"),
                    wind,
                    f("rs"),
                    f("sunshine_hours"),
                )
            )
        except (ValueError, KeyError) as exc:
            errors.append(f"Row {n}: {exc}")
    return days, errors


def _getter(row: dict[str, str]):
    def f(key: str) -> float | None:
        value = row.get(key)
        return float(value) if value not in (None, "") else None

    return f


# --- synthetic --------------------------------------------------------------------------------------


def synthetic_weather(lat: float, start: date, end: date, seed: int = 0) -> list[WeatherDay]:
    """Plausible but invented daily weather for offline demos and tests. Not a climate model.

    Temperature follows a seasonal sine (warmest about day 160 in the northern hemisphere); rain follows a
    two-state Markov chain whose wet probability peaks in July-August (a monsoon-like season), with exponential
    amounts. The same seed gives the same weather.
    """
    rng = random.Random(seed)
    out, wet = [], False
    shift = 0 if lat >= 0 else 182
    d = start
    while d <= end:
        doy = d.timetuple().tm_yday
        season = math.cos(2 * math.pi * (doy - 160 - shift) / 365)
        monsoon = max(0.0, math.cos(2 * math.pi * (doy - 215 - shift) / 365)) ** 3
        annual = 27.0 if abs(lat) <= 25 else 27.0 - 0.6 * (abs(lat) - 25)
        tmean = annual + (2 + 0.25 * abs(lat)) * season - 2.5 * monsoon + rng.gauss(0, 1.5)
        rng_t = 11 - 5 * monsoon + rng.gauss(0, 1.2)
        p_wet = (0.7 if wet else 0.25) * (0.2 + 0.8 * monsoon) + (0.05 if wet else 0.02)
        wet = rng.random() < p_wet
        rain = rng.expovariate(1 / (15 if monsoon > 0.3 else 5)) if wet else 0.0
        rh_mean = min(95.0, 45 + 40 * monsoon + (15 if wet else 0) + rng.gauss(0, 5))
        out.append(
            WeatherDay(
                d,
                round(tmean + rng_t / 2, 1),
                round(tmean - rng_t / 2, 1),
                round(rain, 1),
                rh_mean=round(rh_mean, 0),
                wind_2m=round(max(0.5, rng.gauss(2.0, 0.6)), 2),
            )
        )
        d += timedelta(days=1)
    return out


# --- ET0 --------------------------------------------------------------------------------------------


def with_et0(days: list[WeatherDay], lat: float, elevation_m: float) -> list[tuple[WeatherDay, float, bool]]:
    """(day, FAO Penman-Monteith ET0, whether radiation was estimated from temperature)."""
    out = []
    for w in days:
        r = et0_penman_monteith(
            tmax=w.tmax,
            tmin=w.tmin,
            lat_deg=lat,
            elevation_m=elevation_m,
            doy=w.day.timetuple().tm_yday,
            u2=w.wind_2m,
            rs=w.rs,
            sunshine_hours=w.sunshine_hours,
            rh_min=w.rh_min,
            rh_max=w.rh_max,
            rh_mean=w.rh_mean,
        )
        out.append((w, r.et0, r.rs_estimated))
    return out


def to_balance_weather(days: list[WeatherDay], lat: float, elevation_m: float) -> list[DayWeather]:
    return [DayWeather(w.day, et0, w.rain, w.forecast) for w, et0, _ in with_et0(days, lat, elevation_m)]
