from __future__ import annotations

from pathlib import Path

from conftest import make_settings, wait_for_job
from fastapi.testclient import TestClient
from smartagri_api.db import session_scope
from smartagri_api.main import create_app
from smartagri_api.models import Role, User
from smartagri_api.security import hash_password

DEMO = "data_generator:soil_moisture_demo"


def test_health_and_local_user(client: TestClient) -> None:
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["local_mode"] is True
    me = client.get("/api/auth/me").json()
    assert "admin" in me["roles"] and "job:run" in me["permissions"]


def test_plugin_catalogue_and_schema(client: TestClient) -> None:
    plugins = client.get("/api/plugins").json()
    ids = {p["id"]: p for p in plugins}
    assert ids[DEMO]["status"] == "simulated" and ids[DEMO]["runnable"]
    assert ids["scheduler:aura"]["status"] == "implemented"
    assert ids["optimizer:ppo"]["status"] == "planned"
    planned = client.get("/api/plugins", params={"status": "planned"}).json()
    assert planned and all(p["status"] == "planned" for p in planned)
    detail = client.get(f"/api/plugins/{DEMO}").json()
    assert detail["params_schema"]["properties"]["days"]["x-unit"] == "days"
    assert detail["default_params"]["seed"] == 42
    assert client.get("/api/plugins/scheduler:nope").status_code == 404


def test_validate_params(client: TestClient) -> None:
    bad = client.post(f"/api/plugins/{DEMO}/validate", json={"params": {"days": 0}}).json()
    assert bad["valid"] is False and bad["errors"][0]["loc"] == ["days"]
    good = client.post(f"/api/plugins/{DEMO}/validate", json={"params": {"days": 3}}).json()
    assert good["valid"] and good["params"]["days"] == 3


def test_planned_plugin_cannot_be_run(client: TestClient) -> None:
    resp = client.post("/api/jobs", json={"plugin_id": "optimizer:ppo", "params": {}})
    assert resp.status_code == 409 and "Phase 4" in resp.json()["detail"]


def test_building_block_plugin_is_not_a_job(client: TestClient) -> None:
    resp = client.post("/api/jobs", json={"plugin_id": "placement:ga", "params": {}})
    assert resp.status_code == 409 and "building block" in resp.json()["detail"]
    plugin = client.get("/api/plugins/placement:ga").json()
    assert plugin["runnable"] and not plugin["startable"]


def test_job_runs_and_streams_progress(client: TestClient) -> None:
    with client.websocket_connect("/api/ws/jobs") as ws:
        job = client.post("/api/jobs", json={"plugin_id": DEMO, "params": {"days": 4, "demo_delay_ms": 0}}).json()
        events = []
        while True:
            event = ws.receive_json()
            if event.get("job_id", event.get("job", {}).get("id")) != job["id"]:
                continue
            events.append(event)
            if event["type"] == "job.finished":
                break
    assert any(e["type"] == "job.progress" for e in events)
    finished = events[-1]["job"]
    assert finished["status"] == "succeeded" and finished["data_origin"] == "synthetic"
    result = client.get(f"/api/jobs/{job['id']}/result").json()
    assert result["summary"]["n_readings"] == 4 * 24
    assert any(j["id"] == job["id"] for j in client.get("/api/jobs").json())


def test_job_can_be_cancelled(client: TestClient) -> None:
    job = client.post("/api/jobs", json={"plugin_id": DEMO, "params": {"days": 365, "demo_delay_ms": 100}}).json()
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
    assert wait_for_job(client, job["id"])["status"] == "cancelled"


def test_invalid_job_params_rejected(client: TestClient) -> None:
    resp = client.post("/api/jobs", json={"plugin_id": DEMO, "params": {"wilting_point": 0.5}})
    assert resp.status_code == 422


def test_projects_crud_and_audit(client: TestClient) -> None:
    created = client.post("/api/projects", json={"name": "Kharif paddy", "description": "50 fields"}).json()
    pid = created["id"]
    assert client.patch(f"/api/projects/{pid}", json={"default_seed": 7}).json()["default_seed"] == 7
    assert [p["name"] for p in client.get("/api/projects").json()] == ["Kharif paddy"]
    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/projects/{pid}").status_code == 404
    actions = [e["action"] for e in client.get("/api/audit").json()]
    assert {"project.create", "project.update", "project.delete"} <= set(actions)


def test_user_settings_persist(client: TestClient) -> None:
    client.put("/api/settings/me", json={"values": {"theme": "dark", "language": "hi"}})
    assert client.get("/api/settings/me").json()["values"] == {"theme": "dark", "language": "hi"}


def test_restart_keeps_data_and_migrations_are_idempotent(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as c:
        c.post("/api/projects", json={"name": "Persisted"})
    with TestClient(create_app(settings)) as c:
        assert [p["name"] for p in c.get("/api/projects").json()] == ["Persisted"]


def test_multi_user_mode_requires_login_and_enforces_roles(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, local_mode=False, secret_key="test-secret-key-for-tests-only-0123456789")
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/auth/me").status_code == 401
        with session_scope() as s:
            researcher = s.query(Role).filter_by(name="researcher").one()
            s.add(
                User(
                    email="r@uni.edu", display_name="R", password_hash=hash_password("password123"), roles=[researcher]
                )
            )
            s.commit()
        assert c.post("/api/auth/login", data={"username": "r@uni.edu", "password": "wrong"}).status_code == 401
        token = c.post("/api/auth/login", data={"username": "r@uni.edu", "password": "password123"}).json()
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        assert c.get("/api/auth/me", headers=headers).json()["roles"] == ["researcher"]
        assert c.get("/api/plugins", headers=headers).status_code == 200
        assert c.get("/api/users", headers=headers).status_code == 403


def test_simulation_comparison_job(client: TestClient) -> None:
    params = {"placements": ["cloud_only", "mct"], "replications": 2, "duration_s": 300, "farms": 2}
    job = client.post("/api/jobs", json={"plugin_id": "simulation:comparison", "params": params}).json()
    done = wait_for_job(client, job["id"], timeout=120)
    assert done["status"] == "succeeded", done["error"]
    result = client.get(f"/api/jobs/{job['id']}/result").json()
    assert result["kind"] == "simulation.comparison" and result["data_origin"] == "synthetic"
    assert set(result["comparison"]) == {"cloud_only", "mct"}
    assert result["comparison"]["mct"]["deadline_success_rate"]["n"] == 2


def test_new_plugin_kinds_listed(client: TestClient) -> None:
    kinds = {p["kind"] for p in client.get("/api/plugins").json()}
    assert {"placement", "queue_discipline", "simulation"} <= kinds


def test_reports_for_a_finished_job(client: TestClient) -> None:
    params = {"placements": ["cloud_only", "mct"], "replications": 2, "duration_s": 120, "farms": 1}
    job = client.post("/api/jobs", json={"plugin_id": "simulation:comparison", "params": params}).json()
    assert wait_for_job(client, job["id"], timeout=120)["status"] == "succeeded"
    listing = client.get("/api/reports").json()
    item = next(x for x in listing if x["job_id"] == job["id"])
    assert item["kind"] == "simulation.comparison" and item["dedicated_layout"]
    preview = client.get(f"/api/reports/{job['id']}/preview").json()
    assert preview["tables"][0]["rows"] and preview["figures"]
    svg = client.get(f"/api/reports/{job['id']}/figure/{preview['figures'][0]['key']}.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    pdf = client.get(f"/api/reports/{job['id']}/export/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert "attachment" in pdf.headers["content-disposition"]
    bundle = client.get(f"/api/reports/{job['id']}/export/bundle")
    import io
    import zipfile

    files = zipfile.ZipFile(io.BytesIO(bundle.content))
    assert "simulation:comparison" in files.read("reproduce.ps1").decode()
    assert client.get(f"/api/reports/{job['id']}/export/docx").status_code == 404
    assert client.get(f"/api/reports/{job['id']}/figure/nope.svg").status_code == 404
