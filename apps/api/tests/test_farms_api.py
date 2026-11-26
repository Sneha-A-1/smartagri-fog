from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from smartagri_api import weather_service
from smartagri_api.routers.agro import polygon_area_ha

# a 100 m x 100 m square near the equator (1 ha): 100 m is about 0.000898 degrees
SQUARE = [[0.0, 0.0], [0.000898, 0.0], [0.000898, 0.000898], [0.0, 0.000898]]


def _farm(client: TestClient, **kw) -> dict:
    body = {"name": "Test farm", "latitude": 28.61, "longitude": 77.21, "elevation_m": 216} | kw
    r = client.post("/api/farms", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_polygon_area() -> None:
    assert polygon_area_ha(SQUARE) == pytest.approx(1.0, rel=0.01)
    assert polygon_area_ha(SQUARE[:2]) == 0.0


def test_farm_and_field_crud(client: TestClient) -> None:
    farm = _farm(client)
    f = client.post(
        f"/api/farms/{farm['id']}/fields",
        json={"name": "North", "boundary": SQUARE, "crop": "maize", "irrigation_method": "drip"},
    ).json()
    assert f["area_ha"] == pytest.approx(1.0, rel=0.01) and f["efficiency"] == 0.9
    assert client.post(f"/api/farms/{farm['id']}/fields", json={"name": "x", "crop": "banana"}).status_code == 422
    assert client.post(f"/api/farms/{farm['id']}/fields", json={"name": "x", "boundary": [[0, 0]]}).status_code == 422
    f2 = client.patch(
        f"/api/fields/{f['id']}", json={"irrigation_method": "sprinkler", "sowing_date": "2025-11-15"}
    ).json()
    assert f2["efficiency"] == 0.75 and f2["sowing_date"] == "2025-11-15"
    listed = client.get("/api/farms").json()
    assert listed[0]["total_area_ha"] == pytest.approx(1.0, rel=0.01) and len(listed[0]["fields"]) == 1
    assert client.delete(f"/api/fields/{f['id']}").status_code == 204
    assert client.delete(f"/api/farms/{farm['id']}").status_code == 204
    assert client.get(f"/api/farms/{farm['id']}").status_code == 404
    presets = client.get("/api/agro/presets").json()
    assert {c["key"] for c in presets["crops"]} >= {"wheat", "rice"} and presets["soils"][0]["taw_per_m"] > 0


def test_synthetic_weather_and_water_balance(client: TestClient) -> None:
    farm = _farm(client)
    sowing = date.today() - timedelta(days=40)
    f = client.post(
        f"/api/farms/{farm['id']}/fields",
        json={"name": "Wheat", "crop": "wheat", "sowing_date": sowing.isoformat(), "soil": "sandy_loam"},
    ).json()
    w = client.get(f"/api/farms/{farm['id']}/weather", params={"source": "synthetic"}).json()
    assert w["data_origin"] == "synthetic" and len(w["days"]) == 61 and all(d["et0"] >= 0 for d in w["days"])
    assert any(d["forecast"] for d in w["days"])
    wb = client.get(f"/api/fields/{f['id']}/water-balance", params={"source": "synthetic"}).json()
    assert wb["data_origin"] == "synthetic" and wb["days"][0]["day"] == sowing.isoformat()
    assert wb["summary"]["days"] == 41 and wb["recommendation"]["action"] in {"irrigate", "wait"}
    unset = client.post(f"/api/farms/{farm['id']}/fields", json={"name": "No date"}).json()
    assert client.get(f"/api/fields/{unset['id']}/water-balance", params={"source": "synthetic"}).status_code == 422


def test_csv_weather_import(client: TestClient) -> None:
    farm = _farm(client)
    start = date(2025, 1, 1)
    rows = "\n".join(
        f"{start + timedelta(days=i)},{24 + i % 3},{9 + i % 2},{5 if i % 10 == 0 else 0},55,2.0" for i in range(30)
    )
    text = "date,tmax,tmin,rain,rh_mean,wind_2m\n" + rows + "\nbad,row\n"
    r = client.post(f"/api/farms/{farm['id']}/weather/csv", files={"file": ("station.csv", text.encode(), "text/csv")})
    assert r.json()["imported"] == 30 and len(r.json()["errors"]) == 1
    w = client.get(
        f"/api/farms/{farm['id']}/weather", params={"source": "csv", "start": "2025-01-01", "end": "2025-01-30"}
    ).json()
    assert w["data_origin"] == "real" and len(w["days"]) == 30 and w["days"][0]["radiation_estimated"]


def test_open_meteo_is_cached_and_errors_are_clear(client: TestClient, monkeypatch) -> None:
    farm = _farm(client)
    calls = []
    today = date.today()

    class Resp:
        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    def fake_get(url, timeout):
        calls.append(url)
        q = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
        a, b = date.fromisoformat(q["start_date"]), date.fromisoformat(q["end_date"])
        days = [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
        return Resp(
            {  # shaped like an Open-Meteo response; values invented for the test
                "daily": {
                    "time": days,
                    "temperature_2m_max": [30.0] * len(days),
                    "temperature_2m_min": [15.0] * len(days),
                    "precipitation_sum": [0.0] * len(days),
                    "shortwave_radiation_sum": [20.0] * len(days),
                    "et0_fao_evapotranspiration": [5.0] * len(days),
                },
                "hourly": {
                    "time": [f"{d}T{h:02d}:00" for d in days for h in range(24)],
                    "relative_humidity_2m": [50.0] * 24 * len(days),
                    "wind_speed_10m": [2.0] * 24 * len(days),
                },
            }
        )

    monkeypatch.setattr(weather_service.httpx, "get", fake_get)
    start, end = (today - timedelta(days=100)).isoformat(), (today - timedelta(days=70)).isoformat()
    w = client.get(f"/api/farms/{farm['id']}/weather", params={"start": start, "end": end}).json()
    assert w["data_origin"] == "real" and len(w["days"]) == 31 and len(calls) == 1 and "archive-api" in calls[0]
    assert w["et0_mean_abs_difference"] is not None
    client.get(f"/api/farms/{farm['id']}/weather", params={"start": start, "end": end})
    assert len(calls) == 1  # served from the cache

    def offline(url, timeout):
        raise weather_service.httpx.ConnectError("no network")

    monkeypatch.setattr(weather_service.httpx, "get", offline)
    r = client.get(f"/api/farms/{farm['id']}/weather", params={"start": "2020-01-01", "end": "2020-01-10"})
    assert r.status_code == 502 and "synthetic weather" in r.json()["detail"]
