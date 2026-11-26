from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

SQUARE = [[77.15, 28.63], [77.152, 28.63], [77.152, 28.632], [77.15, 28.632]]


def _setup(client: TestClient) -> tuple[dict, dict]:
    farm = client.post(
        "/api/farms", json={"name": "F", "latitude": 28.631, "longitude": 77.151, "elevation_m": 220}
    ).json()
    sowing = (date.today() - timedelta(days=20)).isoformat()
    field = client.post(
        f"/api/farms/{farm['id']}/fields",
        json={"name": "A", "boundary": SQUARE, "crop": "wheat", "sowing_date": sowing},
    ).json()
    return farm, field


def test_simulated_soil_sensor_and_sensor_corrected_balance(client: TestClient) -> None:
    farm, field = _setup(client)
    body = {
        "name": "Probe 1",
        "kind": "soil_moisture",
        "field_id": field["id"],
        "latitude": 28.631,
        "longitude": 77.151,
        "interval_min": 60,
        "config": {"weather_source": "synthetic", "et_multiplier": 1.3, "noise_sd": 0.0},
    }
    d = client.post(f"/api/farms/{farm['id']}/devices", json=body)
    assert d.status_code == 201, d.text
    dev = d.json()
    assert dev["token"] is None and dev["online"] and "soil_moisture_m3m3" in dev["latest"]
    assert dev["latest"]["soil_moisture_m3m3"]["origin"] == "synthetic"
    r = client.get(
        f"/api/devices/{dev['id']}/readings", params={"metric": "soil_moisture_m3m3", "max_points": 50}
    ).json()
    assert r["total"] >= 14 * 24 * 0.9 and len(r["points"]) <= 50 and r["unit"] == "m³/m³"
    # topping up again adds nothing new within the same minute
    assert (
        client.get(f"/api/devices/{dev['id']}/readings", params={"metric": "soil_moisture_m3m3"}).json()["total"]
        == r["total"]
    )

    plain = client.get(f"/api/fields/{field['id']}/water-balance", params={"source": "synthetic"}).json()
    fused = client.get(
        f"/api/fields/{field['id']}/water-balance", params={"source": "synthetic", "use_sensors": True}
    ).json()
    assert plain["sensors_used"] == 0 and fused["sensors_used"] == 1 and fused["summary"]["sensor_days"] >= 18
    # the true field uses 30% more water, so the sensor shows a drier soil than the model
    assert fused["summary"]["sensor_correction_mm"] > 0

    changed = client.patch(
        f"/api/devices/{dev['id']}",
        json={"config": {"weather_source": "synthetic", "et_multiplier": 1.0, "noise_sd": 0.0}},
    ).json()
    assert changed["latest"]["soil_moisture_m3m3"]["value"] != dev["latest"]["soil_moisture_m3m3"]["value"]

    twin = client.get("/api/twin", params={"source": "synthetic"}).json()
    tf = twin["farms"][0]["fields"][0]
    assert tf["sensors"] == 1 and 0 <= tf["available_fraction"] <= 1 and tf["action"] in {"irrigate", "wait"}
    assert len(twin["farms"][0]["devices"]) == 1

    assert client.post(f"/api/farms/{farm['id']}/devices", json=body | {"field_id": None}).status_code == 422
    assert client.delete(f"/api/devices/{dev['id']}").status_code == 204


def test_real_device_ingestion(client: TestClient) -> None:
    farm, field = _setup(client)
    d = client.post(
        f"/api/farms/{farm['id']}/devices",
        json={
            "name": "ESP32 probe",
            "kind": "soil_moisture",
            "field_id": field["id"],
            "latitude": 28.631,
            "longitude": 77.151,
            "simulated": False,
        },
    ).json()
    token = d["token"]
    assert token and not d["online"] and d["config"] == {}
    ts = datetime.now(UTC).replace(microsecond=0)
    payload = {
        "device_id": d["id"],
        "readings": [{"metric": "soil_moisture_m3m3", "value": 0.21, "ts": ts.isoformat()}],
    }
    assert client.post("/api/ingest", json=payload, headers={"X-Device-Token": "wrong"}).status_code == 401
    ok = client.post("/api/ingest", json=payload, headers={"X-Device-Token": token}).json()
    assert ok == {"stored": 1, "duplicates": 0}
    assert client.post("/api/ingest", json=payload, headers={"X-Device-Token": token}).json()["duplicates"] == 1
    bad = payload | {"readings": [{"metric": "valve_open", "value": 1}]}
    assert client.post("/api/ingest", json=bad, headers={"X-Device-Token": token}).status_code == 422
    listed = client.get("/api/devices").json()[0]
    assert listed["online"] and listed["latest"]["soil_moisture_m3m3"]["origin"] == "real"
    new = client.post(f"/api/devices/{d['id']}/token").json()["token"]
    assert new != token
    assert client.post("/api/ingest", json=payload, headers={"X-Device-Token": token}).status_code == 401


def test_weather_station_and_valve(client: TestClient) -> None:
    farm, field = _setup(client)
    ws = client.post(
        f"/api/farms/{farm['id']}/devices",
        json={
            "name": "Station",
            "kind": "weather_station",
            "latitude": 28.631,
            "longitude": 77.151,
            "interval_min": 60,
            "config": {"weather_source": "synthetic"},
        },
    ).json()
    assert set(ws["latest"]) >= {"air_temperature_c", "relative_humidity_pct"}
    valve = client.post(
        f"/api/farms/{farm['id']}/devices",
        json={
            "name": "Valve",
            "kind": "valve",
            "field_id": field["id"],
            "latitude": 28.631,
            "longitude": 77.151,
            "config": {"weather_source": "synthetic"},
        },
    ).json()
    assert valve["latest"]["valve_open"]["value"] in (0.0, 1.0)
    kinds = client.get("/api/devices/kinds").json()
    assert kinds["kinds"]["gateway"]["metrics"] == []
