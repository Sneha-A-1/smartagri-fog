"""Fetching and caching daily weather for farms (Open-Meteo, imported CSV, or synthetic)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Literal

import httpx
from smartagri_core.agro.weather import WeatherDay, open_meteo_url, parse_open_meteo, synthetic_weather
from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.models import Farm, WeatherRecord

Source = Literal["open_meteo", "csv", "synthetic"]

SOURCE_INFO = {
    "open_meteo": (
        "real",
        "Open-Meteo: ERA5 reanalysis for past dates, weather models for recent days and the forecast",
    ),
    "csv": ("real", "Your imported station data"),
    "synthetic": ("synthetic", "Invented weather from a seeded generator, for demos and offline use"),
}
FORECAST_MAX_AGE = timedelta(hours=6)


class WeatherUnavailable(Exception):
    pass


def location_key(farm: Farm, source: Source) -> str:
    if source == "csv":
        return f"farm:{farm.id}"
    return f"{farm.latitude:.2f},{farm.longitude:.2f}"


def _from_record(r: WeatherRecord) -> WeatherDay:
    d = dict(r.data)
    d["day"] = date.fromisoformat(d["day"])
    return WeatherDay(**d)


def store(session: Session, key: str, source: str, days: list[WeatherDay]) -> int:
    existing = {
        r.day: r
        for r in session.scalars(
            select(WeatherRecord).where(
                WeatherRecord.location_key == key,
                WeatherRecord.source == source,
                WeatherRecord.day.in_([d.day for d in days]),
            )
        )
    }
    now = datetime.now(UTC)
    for d in days:
        row = existing.get(d.day)
        if row is None:
            session.add(
                WeatherRecord(
                    location_key=key, day=d.day, source=source, forecast=d.forecast, data=d.to_dict(), fetched_at=now
                )
            )
        else:
            row.data, row.forecast, row.fetched_at = d.to_dict(), d.forecast, now
    session.flush()
    return len(days)


def _fetch_open_meteo(lat: float, lon: float, start: date, end: date, today: date) -> list[WeatherDay]:
    """One or two requests: archive for older dates, forecast API for the last 60 days and ahead."""
    split = today - timedelta(days=60)
    ranges = [(start, end)]
    if start < split <= end:
        ranges = [(start, split - timedelta(days=1)), (split, end)]
    days: list[WeatherDay] = []
    for a, b in ranges:
        url = open_meteo_url(lat, lon, a, b, today=today)
        try:
            resp = httpx.get(url, timeout=25.0)
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WeatherUnavailable(
                f"Couldn't reach Open-Meteo ({exc.__class__.__name__}). Check the internet "
                "connection, or use synthetic weather or an imported CSV."
            ) from exc
        try:
            days += parse_open_meteo(payload, today=today)
        except (ValueError, KeyError) as exc:
            raise WeatherUnavailable(str(exc)) from exc
    return days


def get_weather(
    session: Session, farm: Farm, start: date, end: date, source: Source, *, today: date | None = None, seed: int = 1
) -> list[WeatherDay]:
    today = today or date.today()
    if source == "synthetic":
        return synthetic_weather(farm.latitude, start, end, seed=seed)
    key = location_key(farm, source)
    rows = {
        r.day: r
        for r in session.scalars(
            select(WeatherRecord).where(
                WeatherRecord.location_key == key,
                WeatherRecord.source == source,
                WeatherRecord.day >= start,
                WeatherRecord.day <= end,
            )
        )
    }
    if source == "open_meteo":
        end = min(end, today + timedelta(days=15))
        now = datetime.now(UTC)

        def stale(d: date) -> bool:
            r = rows.get(d)
            if r is None:
                return True
            fetched = r.fetched_at if r.fetched_at.tzinfo else r.fetched_at.replace(tzinfo=UTC)
            return d >= today - timedelta(days=5) and now - fetched > FORECAST_MAX_AGE

        need = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        missing = [d for d in need if stale(d)]
        if missing:
            fetched = _fetch_open_meteo(farm.latitude, farm.longitude, min(missing), max(missing), today)
            store(session, key, source, fetched)
            session.commit()
            for d in fetched:
                rows[d.day] = WeatherRecord(day=d.day, data=d.to_dict())
    return [_from_record(rows[d]) for d in sorted(rows) if start <= d <= end]
