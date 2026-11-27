"""The data retrieval framework: each stage, task emission, scenarios and the evaluation."""

from __future__ import annotations

import math

import pytest
from smartagri_core.registry import get_registry
from smartagri_core.retrieval.evaluate import ARCHITECTURES, ArchitectureSettings, evaluate, run_architecture
from smartagri_core.retrieval.framework import RetrievalConfig, Rule, Stream, make_tasks, process_stream
from smartagri_core.retrieval.scenario import ScenarioParams, generate

SOIL = "soil_moisture_m3m3"
TEMP = "air_temperature_c"
RAW = RetrievalConfig(smooth_min={}, predict=False)  # stage-by-stage tests use raw values


def _stream(metric: str = SOIL, **refs: float) -> Stream:
    return Stream(f"s:{metric}", "s", metric, "g", refs)


def test_spikes_are_rejected_but_level_changes_are_accepted() -> None:
    values = [0.20 + 0.001 * (i % 3) for i in range(20)]
    values[8] = 0.45  # an isolated spike
    values += [0.28 + 0.001 * (i % 3) for i in range(20)]  # irrigation raises the level for good
    res = process_stream(_stream(), [(i * 15.0, v) for i, v in enumerate(values)], RAW)
    assert res.status[8] == "spike"
    # the step is accepted once it holds the window's median: 4 readings with a window of 7 (regression test:
    # the filter used to compare only with accepted readings and rejected everything after a step)
    assert res.status.count("spike") == 1 + 4
    assert all(s == "ok" for s in res.status[-10:])


def test_stuck_and_out_of_range_raise_one_fault_each() -> None:
    samples = [(i * 15.0, 0.25 + 0.002 * (i % 2)) for i in range(10)]
    samples += [(150 + i * 15.0, 0.231) for i in range(20)]  # frozen for 5 hours
    samples += [(450 + i * 15.0, 9.99) for i in range(3)]  # impossible value
    res = process_stream(_stream(), samples, RAW)
    kinds = [(e.kind, e.name) for e in res.events]
    assert kinds.count(("fault", "stuck")) == 1 and kinds.count(("fault", "range")) == 1
    assert res.status.count("stuck") == 20 - 12  # flagged once 180 minutes have passed without change


def test_persistence_and_hysteresis_stop_alert_chatter() -> None:
    wobble = [(i * 15.0, 1.5 + (1.0 if i % 2 else -1.0)) for i in range(40)]  # 0.5 / 2.5 around 2.0
    naive = RAW.model_copy(
        update={
            "persistence": 1,
            "validate_spikes": False,
            "rules": [Rule(name="frost", metric=TEMP, op="<=", threshold=2.0)],
        }
    )
    many = process_stream(_stream(TEMP), wobble, naive)
    guarded_cfg = naive.model_copy(
        update={"rules": [Rule(name="frost", metric=TEMP, op="<=", threshold=2.0, hysteresis=1.0)]}
    )
    few = process_stream(_stream(TEMP), wobble, guarded_cfg)
    assert len([e for e in many.events if e.kind == "threshold"]) == 20
    assert len([e for e in few.events if e.kind == "threshold"]) == 1


def test_trend_prediction_warns_before_the_crossing() -> None:
    drying = [(i * 15.0, 0.30 - 0.0005 * i) for i in range(200)]  # crosses 0.22 at i = 160 (t = 2400 min)
    res = process_stream(_stream(stress_theta=0.22), drying, RetrievalConfig(smooth_min={}))
    warn = next(e for e in res.events if e.kind == "predicted")
    alert = next(e for e in res.events if e.kind == "threshold")
    assert warn.t < alert.t and warn.t + warn.eta_min == pytest.approx(2400, abs=20)
    assert 2400 - warn.t <= 360 + 15  # raised within the horizon


def test_send_on_delta_and_tasks() -> None:
    flat = [(i * 15.0, 0.25) for i in range(48)] + [(720 + i * 15.0, 0.30) for i in range(8)]
    cfg = RAW.model_copy(update={"validate_stuck": False, "validate_spikes": False})
    res = process_stream(_stream(stress_theta=0.1), flat, cfg)
    sent_times = [t for t, _ in res.transmitted]
    assert sent_times[:3] == [0.0, 120.0, 240.0] and 720.0 in sent_times  # heartbeat, then the step
    alert_res = process_stream(_stream(stress_theta=0.27), [(i * 15.0, 0.25) for i in range(4)], cfg)
    tasks = make_tasks([alert_res], cfg, horizon=60)
    urgent = [t for t in tasks if t.urgent]
    assert len(urgent) == 1 and urgent[0].task_type == "irrigation_decision" and urgent[0].task_class == "high"
    assert urgent[0].data_time == 15.0 and urgent[0].deadline == 15.0 + cfg.profiles["high"].deadline_min
    assert any(t.task_class == "low" and t.task_type == "aggregation" for t in tasks)


def test_scenarios_are_seeded_and_a_clean_scenario_is_detected_perfectly() -> None:
    p = ScenarioParams(fields=4, days=12, seed=5)
    a, b = generate(p), generate(p)
    assert a.samples == b.samples and generate(p.model_copy(update={"seed": 6})).samples != a.samples
    clean = generate(ScenarioParams(seed=5, soil_noise=0, temp_noise=0, spike_prob=0, stuck_episodes=0, dropout=0))
    assert {e.name for e in clean.events} >= {"soil_stress", "frost"}
    settings = ArchitectureSettings()
    res, tasks = run_architecture(clean, "edge_drf", RetrievalConfig(), settings)
    m = evaluate(clean, res, tasks, settings)
    assert m["precision"] == 1.0 and m["recall"] == 1.0 and m["false_alarms_per_day"] == 0
    assert m["transmitted_share"] < 0.5 and m["urgent_aoi_min"] == pytest.approx(0.02)


def test_architectures_differ_as_designed() -> None:
    scn = generate(ScenarioParams(fields=6, days=12, seed=2))
    s = ArchitectureSettings()
    m = {a: evaluate(scn, *run_architecture(scn, a, RetrievalConfig(), s), s) for a in ARCHITECTURES}
    assert m["cloud_raw"]["transmitted_share"] > 0.9 and m["edge_drf"]["transmitted_share"] < 0.3
    assert m["cloud_raw"]["urgent_aoi_min"] > 10 > m["edge_drf"]["urgent_aoi_min"]
    assert m["edge_sod"]["fault_recall"] == 0 and m["edge_drf"]["fault_recall"] == 1
    assert m["edge_sod"]["false_alarms_per_day"] > m["edge_drf"]["false_alarms_per_day"]
    if not math.isnan(m["edge_drf"]["time_to_detect_min"]):
        assert m["cloud_raw"]["time_to_detect_min"] > m["edge_drf"]["time_to_detect_min"]


def test_evaluation_plugin() -> None:
    reg = get_registry()
    reg.ensure_loaded()
    out = reg.create("simulation:retrieval_evaluation", {"replications": 3, "fields": 4, "days": 8}).run()
    assert out["kind"] == "simulation.strategy_comparison" and set(out["labels"]) == set(ARCHITECTURES)
    assert out["tests"]["transmitted_share"]["omnibus"]["test"] == "friedman"
