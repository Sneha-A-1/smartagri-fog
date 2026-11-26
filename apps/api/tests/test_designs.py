from __future__ import annotations

from conftest import wait_for_job
from fastapi.testclient import TestClient


def _generated(client: TestClient, **params) -> dict:
    return client.post("/api/topologies/generate", json={"farms": 2, **params}).json()


def test_presets_and_generator(client: TestClient) -> None:
    presets = client.get("/api/topologies/presets").json()
    assert {"edge", "fog", "cloud", "iot"} <= set(presets["devices"]) and "lorawan" in presets["link_kinds"]
    gen = _generated(client)
    assert gen["summary"]["layers"]["iot"]["nodes"] == 4
    assert set(gen["layout"]) == {n["id"] for n in gen["topology"]["nodes"]}


def test_validate_reports_problems_without_raising(client: TestClient) -> None:
    ok = client.post("/api/topologies/validate", json={"topology": _generated(client)["topology"]}).json()
    assert ok["valid"] and not ok["problems"]
    broken = {"nodes": [{"id": "a", "layer": "fog"}], "links": [{"a": "a", "b": "ghost"}]}
    bad = client.post("/api/topologies/validate", json={"topology": broken}).json()
    assert not bad["valid"] and "unknown node" in bad["problems"][0]
    isolated = {
        "nodes": [{"id": "gw", "layer": "iot", "cores": 0, "mips": 0}, {"id": "f", "layer": "fog"}],
        "links": [],
    }
    res = client.post("/api/topologies/validate", json={"topology": isolated}).json()
    assert not res["valid"] and any("cannot reach" in p for p in res["problems"])


def test_topology_crud(client: TestClient) -> None:
    gen = _generated(client)
    row = client.post(
        "/api/topologies", json={"name": "Two farms", "topology": gen["topology"], "layout": gen["layout"]}
    ).json()
    assert row["nodes"] == len(gen["topology"]["nodes"]) and not row["problems"]
    topo = row["topology"]
    topo["nodes"][0]["cores"] = 64
    updated = client.put(
        f"/api/topologies/{row['id']}", json={"name": "Two farms v2", "topology": topo, "layout": row["layout"]}
    ).json()
    assert updated["name"] == "Two farms v2" and updated["sha256"] != row["sha256"]
    copy = client.post(f"/api/topologies/{row['id']}/duplicate").json()
    assert copy["name"].startswith("Copy of")
    assert client.delete(f"/api/topologies/{copy['id']}").status_code == 204
    assert [t["name"] for t in client.get("/api/topologies").json()] == ["Two farms v2"]
    assert (
        client.post(
            "/api/topologies", json={"name": "x", "topology": {"nodes": [], "links": [{"a": "q", "b": "r"}]}}
        ).status_code
        == 422
    )


def test_workload_template_preview_and_crud(client: TestClient) -> None:
    tpl = client.get("/api/workloads/template").json()
    assert len(tpl["spec"]["classes"]) == 5 and "deadline_s" in tpl["task_class_schema"]["properties"]
    topo = _generated(client)["topology"]
    prev = client.post("/api/workloads/preview", json={"spec": tpl["spec"], "topology": topo}).json()
    assert prev["sources"] == 4 and prev["capacity_mips"] > 0 and 0 < prev["load_ratio"] < 1
    row = client.post("/api/workloads", json={"name": "Agri mix", "spec": tpl["spec"]}).json()
    assert row["classes"] == 5 and row["spec"]["name"] == "Agri mix"
    spec = row["spec"]
    spec["intensity"] = 3
    assert (
        client.put(f"/api/workloads/{row['id']}", json={"name": "Agri mix x3", "spec": spec}).json()["intensity"] == 3
    )
    bad = {**spec, "classes": [{"name": "x", "deadline_s": -1}]}
    assert client.post("/api/workloads", json={"name": "bad", "spec": bad}).status_code == 422


def test_simulation_from_saved_designs(client: TestClient) -> None:
    gen = _generated(client)
    topo = client.post(
        "/api/topologies", json={"name": "T", "topology": gen["topology"], "layout": gen["layout"]}
    ).json()
    spec = {**client.get("/api/workloads/template").json()["spec"], "duration_s": 300}
    wl = client.post("/api/workloads", json={"name": "W", "spec": spec}).json()
    job = client.post(
        "/api/simulations", json={"topology_id": topo["id"], "workload_id": wl["id"], "placement": "edge_ward"}
    ).json()
    done = wait_for_job(client, job["id"], timeout=120)
    assert done["status"] == "succeeded", done["error"]
    result = client.get(f"/api/jobs/{job['id']}/result").json()
    assert result["params"]["topology"] == "T" and result["nodes"] and result["data_origin"] == "synthetic"
