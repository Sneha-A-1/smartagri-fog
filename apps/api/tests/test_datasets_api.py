from __future__ import annotations

import io
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from openpyxl import Workbook


def _csv() -> bytes:
    rows = ["timestamp,sensor_id,soil_moisture,air_temp"]
    t0 = datetime(2026, 2, 1)
    for i in range(96 * 3):
        t = (t0 + timedelta(minutes=15 * i)).strftime("%Y-%m-%d %H:%M")
        theta = 0.26 - 0.0004 * i  # dries steadily, crossing 0.18 near the end
        rows.append(f"{t},P1,{theta:.4f},{12 + (i % 96) / 8:.1f}")
    return ("\n".join(rows) + "\n").encode()


def test_upload_map_validate_and_retrieve(client: TestClient) -> None:
    r = client.post(
        "/api/datasets",
        files={"file": ("probe.csv", _csv(), "text/csv")},
        data={"origin": "real", "source_note": "Test station"},
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["rows"] == 288 and d["format"] == "csv" and d["origin"] == "real" and len(d["sha256"]) == 64
    assert d["mapping"]["time_column"] == "timestamp" and d["mapping"]["source_column"] == "sensor_id"
    assert d["mapping"]["metrics"] == {"soil_moisture": "soil_moisture_m3m3", "air_temp": "air_temperature_c"}
    types = {c["name"]: c["type"] for c in d["columns"]}
    assert types == {"timestamp": "datetime", "sensor_id": "text", "soil_moisture": "number", "air_temp": "number"}

    prev = client.get(f"/api/datasets/{d['id']}/preview", params={"limit": 5}).json()
    assert prev["total"] == 288 and len(prev["rows"]) == 5
    mapping = d["mapping"] | {"soil_stress_theta": 0.18}
    assert client.patch(f"/api/datasets/{d['id']}", json={"mapping": mapping}).status_code == 200
    bad = mapping | {"time_column": "nope"}
    assert client.patch(f"/api/datasets/{d['id']}", json={"mapping": bad}).status_code == 422
    v = client.get(f"/api/datasets/{d['id']}/validation").json()
    assert v["ok"] and {s["metric"] for s in v["series"]} == {"soil_moisture_m3m3", "air_temperature_c"}
    assert v["series"][0]["interval_min"] == 15
    tidy = client.get(f"/api/datasets/{d['id']}/tidy.csv").text.splitlines()
    assert tidy[0] == "time,source,metric,value" and len(tidy) == 1 + 288 * 2
    assert client.get(f"/api/datasets/{d['id']}/download").content == _csv()

    run = client.post("/api/retrieval/run", json={"source": "dataset", "dataset_id": d["id"]}).json()
    assert run["data_origin"] == "real" and len(run["streams"]) == 2
    soil = next(s for s in run["streams"] if s["metric"] == "soil_moisture_m3m3")
    assert soil["threshold"] == 0.18
    assert any(e["kind"] == "threshold" and e["name"] == "soil_stress" for e in run["events"])
    assert any(e["kind"] == "predicted" for e in run["events"])

    assert client.delete(f"/api/datasets/{d['id']}").status_code == 204
    assert client.get(f"/api/datasets/{d['id']}").status_code == 404


def test_excel_sheets_and_bad_files(client: TestClient) -> None:
    wb = Workbook()
    wb.active.title = "summary"
    wb.active.append(["note"])
    ws = wb.create_sheet("hourly")
    ws.append(["time", "rh"])
    for i in range(24):
        ws.append([datetime(2026, 1, 1) + timedelta(hours=i), 70])
    buf = io.BytesIO()
    wb.save(buf)
    d = client.post(
        "/api/datasets",
        files={"file": ("w.xlsx", buf.getvalue(), "application/octet-stream")},
        data={"origin": "synthetic"},
    ).json()
    assert d["sheet"] == "summary" and d["sheets"] == ["summary", "hourly"] and d["rows"] == 0
    d2 = client.patch(f"/api/datasets/{d['id']}", json={"sheet": "hourly"}).json()
    assert d2["rows"] == 24 and d2["mapping"]["time_column"] == "time"
    assert d2["mapping"]["metrics"] == {"rh": "relative_humidity_pct"}
    r = client.post(
        "/api/datasets", files={"file": ("x.json", b"{broken", "application/json")}, data={"origin": "real"}
    )
    assert r.status_code == 422 and "JSON" in r.json()["detail"]
    assert client.post("/api/datasets", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")}).status_code == 422
