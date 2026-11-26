"""Place search and elevation lookup for placing farms (proxied so the browser needs no third-party calls)."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from smartagri_api.deps import require
from smartagri_api.models import User

router = APIRouter(tags=["geo"])

# Nominatim usage policy: identify the application, at most one request per second, no bulk geocoding.
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "SmartAgri-Fog/0.1 (research platform; local installation)"
ELEVATION = "https://api.open-meteo.com/v1/elevation"


class Place(BaseModel):
    name: str
    latitude: float
    longitude: float
    kind: str


class Elevation(BaseModel):
    elevation_m: float
    source: str


@router.get("/geo/search", response_model=list[Place])
def search_places(
    q: str = Query(min_length=2, max_length=200), _: User = Depends(require("project:read"))
) -> list[dict[str, Any]]:
    try:
        resp = httpx.get(
            NOMINATIM,
            params={"q": q, "format": "jsonv2", "limit": 6, "addressdetails": 0},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            timeout=15.0,
        )
        rows = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            502, "Place search needs an internet connection. You can click the map or type coordinates instead."
        ) from exc
    if not isinstance(rows, list):
        raise HTTPException(502, "The place search service did not answer as expected. Try again in a moment.")
    return [
        {
            "name": r["display_name"],
            "latitude": float(r["lat"]),
            "longitude": float(r["lon"]),
            "kind": r.get("addresstype") or r.get("type", ""),
        }
        for r in rows
    ]


@router.get("/geo/elevation", response_model=Elevation)
def elevation(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    _: User = Depends(require("project:read")),
) -> dict[str, Any]:
    try:
        data = httpx.get(ELEVATION, params={"latitude": latitude, "longitude": longitude}, timeout=15.0).json()
        value = float(data["elevation"][0])
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(502, "Couldn't look up the elevation; type an estimate instead.") from exc
    return {"elevation_m": round(value), "source": "Open-Meteo elevation API (Copernicus DEM, 90 m)"}
