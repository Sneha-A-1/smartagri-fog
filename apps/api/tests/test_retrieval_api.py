from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient


def test_run_on_a_scenario(client: TestClient) -> None:
    body = {"source": "scenario", "scenario": {"fields": 3, "days": 6, "seed": 4}}
    r = client.post("/api/retrieval/run", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["data_origin"] == "synthetic" and len(out["streams"]) == 4 and out["evaluation"]["recall"] is not None
    soil = out["streams"][0]
    assert soil["metric"] == "soil_moisture_m3m3" and soil["threshold"] and soil["truth"]
    assert len(soil["status"]) == len(soil["raw"]) == 6 * 96
    assert out["summary"]["reduction"] > 0.5 and any(t["task_class"] == "low" for t in out["tasks"])
    cloud = client.post("/api/retrieval/run", json=body | {"architecture": "cloud_raw"}).json()
    assert cloud["summary"]["transmitted"] > out["summary"]["transmitted"]
    off = client.post("/api/retrieval/run", json=body | {"settings": {"send_on_delta": False}}).json()
    assert off["summary"]["reduction"] < 0.1


def test_run_on_device_readings(client: TestClient) -> None:
    farm = client.post("/api/farms", json={"name": "F", "latitude": 28.63, "longitude": 77.15}).json()
    assert client.post("/api/retrieval/run", json={"source": "devices", "farm_id": farm["id"]}).status_code == 422
    field = client.post(
        f"/api/farms/{farm['id']}/fields",
        json={"name": "A", "crop": "wheat", "sowing_date": (date.today() - timedelta(days=15)).isoformat()},
    ).json()
    syn = {"weather_source": "synthetic"}
    for kind, fid in (("soil_moisture", field["id"]), ("weather_station", None)):
        client.post(
            f"/api/farms/{farm['id']}/devices",
            json={"name": kind, "kind": kind, "field_id": fid, "latitude": 28.63, "longitude": 77.15, "config": syn},
        )
    out = client.post("/api/retrieval/run", json={"source": "devices", "farm_id": farm["id"], "days": 5}).json()
    metrics = {s["metric"] for s in out["streams"]}
    assert metrics == {"soil_moisture_m3m3", "air_temperature_c"} and out["evaluation"] is None
    soil = next(s for s in out["streams"] if s["metric"] == "soil_moisture_m3m3")
    assert soil["threshold"] is not None and soil["group"] == "A" and soil["truth"] is None
