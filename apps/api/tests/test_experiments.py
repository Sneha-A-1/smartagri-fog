from __future__ import annotations

from conftest import wait_for_job
from fastapi.testclient import TestClient

SPEC = {
    "name": "Rural baseline",
    "objective": "Does edge-ward beat cloud-only on a slow link?",
    "scenario": {"duration_s": 300, "farms": 2, "wan_bandwidth_mbps": 5, "wan_latency_ms": 250},
    "algorithms": [
        {"placement": "cloud_only", "discipline": "edf"},
        {"placement": "edge_ward", "discipline": "edf"},
        {"placement": "mct", "discipline": "edf"},
    ],
    "replications": 3,
}


def test_schema_endpoint(client: TestClient) -> None:
    s = client.get("/api/experiments/schema").json()
    assert "wan_latency_ms" in s["scenario_schema"]["properties"]
    assert {p["key"] for p in s["placements"]} >= {"cloud_only", "edge_ward", "mct", "min_min"}
    assert {d["key"] for d in s["disciplines"]} == {"fcfs", "edf", "priority", "sjf", "aura", "urgent_edf"}
    assert len(s["default_spec"]["algorithms"]) == 3


def test_experiment_lifecycle(client: TestClient) -> None:
    exp = client.post("/api/experiments", json={"spec": SPEC}).json()
    assert exp["status"] == "draft" and exp["total_runs"] == 9 and exp["name"] == "Rural baseline"

    edited = client.put(f"/api/experiments/{exp['id']}", json={"spec": {**SPEC, "replications": 4}}).json()
    assert edited["total_runs"] == 12 and edited["spec_sha256"] != exp["spec_sha256"]

    started = client.post(f"/api/experiments/{exp['id']}/run").json()
    assert started["job_id"]
    job = wait_for_job(client, started["job_id"], timeout=180)
    assert job["status"] == "succeeded", job["error"]

    done = client.get(f"/api/experiments/{exp['id']}").json()
    assert done["status"] == "succeeded" and done["has_result"]
    result = client.get(f"/api/experiments/{exp['id']}/result").json()
    assert result["kind"] == "experiment" and result["data_origin"] == "synthetic"
    assert result["analysis"]["mean_response_s"]["omnibus"]["test"] == "friedman"

    # frozen after running
    assert client.put(f"/api/experiments/{exp['id']}", json={"spec": SPEC}).status_code == 409

    csv_resp = client.get(f"/api/experiments/{exp['id']}/export/csv")
    assert csv_resp.status_code == 200 and csv_resp.text.count("\n") == 13
    assert "attachment" in csv_resp.headers["content-disposition"]
    assert r"\toprule" in client.get(f"/api/experiments/{exp['id']}/export/tex").text
    assert "replications: 4" in client.get(f"/api/experiments/{exp['id']}/export/yaml").text
    assert client.get(f"/api/experiments/{exp['id']}/export/docx").status_code == 404

    copy = client.post(f"/api/experiments/{exp['id']}/duplicate").json()
    assert copy["status"] == "draft" and copy["name"].startswith("Copy of")
    assert client.delete(f"/api/experiments/{copy['id']}").status_code == 204
    assert len(client.get("/api/experiments").json()) == 1


def test_invalid_spec_rejected(client: TestClient) -> None:
    bad = {**SPEC, "algorithms": [{"placement": "mct"}]}
    assert client.post("/api/experiments", json={"spec": bad}).status_code == 422
    assert (
        client.post(
            "/api/experiments", json={"spec": {**SPEC, "algorithms": [{"placement": "teleport"}] * 2}}
        ).status_code
        == 422
    )


def test_export_before_run_is_404(client: TestClient) -> None:
    exp = client.post("/api/experiments", json={"spec": SPEC}).json()
    assert client.get(f"/api/experiments/{exp['id']}/export/csv").status_code == 404
    assert client.get(f"/api/experiments/{exp['id']}/export/yaml").status_code == 200
