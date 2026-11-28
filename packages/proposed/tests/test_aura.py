"""AURA: value function, tiers, replication, reservation, reproducibility and the evaluation plugin."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from smartagri_core import get_registry
from smartagri_core.sim.engine import simulate
from smartagri_core.sim.metrics import compute_metrics
from smartagri_core.sim.policies import DEFER
from smartagri_core.sim.runner import ScenarioParams
from smartagri_core.sim.workload import Task, generate_trace
from smartagri_proposed.aura import Aura, AuraParams, value
from smartagri_proposed.evaluation import AuraEvaluation, AuraEvaluationParams, parse


def _task(**kw) -> Task:
    base = {
        "id": 0,
        "cls": "x",
        "category": "x",
        "priority": "critical",
        "source": "g",
        "arrival_s": 0.0,
        "length_mi": 300.0,
        "input_bytes": 512.0,
        "output_bytes": 100.0,
        "ram_mb": 32.0,
        "deadline_s": 2.0,
        "result_to_source": True,
    }
    return Task(**(base | kw))


def _run(
    placement: str,
    stress: str = "normal",
    seed: int = 1,
    duration: float = 300,
    intensity: float = 60,
    params=None,
    discipline: str = "aura",
):
    reg = get_registry()
    topo, spec, settings = ScenarioParams(stress=stress, duration_s=duration, intensity=intensity).build()
    trace = generate_trace(spec, topo, seed)
    pl = reg.create(f"placement:{placement}", params or {})
    sim = simulate(topo, trace, pl, reg.create(f"queue_discipline:{discipline}"), settings, seed=seed)
    return sim, pl, trace


def test_value_is_full_until_the_effective_deadline_then_decays():
    t = _task()
    assert value(t, 1.9, 2.0) == 4.0
    assert value(t, 4.0, 2.0) == pytest.approx(2.0)
    assert value(t, 8.1, 2.0) == 0.0


def test_aoi_switch_changes_the_deadline_aura_plans_for():
    stale = _task(data_time_s=-29.5, freshness_s=30.0)  # data stale at t = 0.5 s
    assert Aura(AuraParams())._deadline(stale) == pytest.approx(0.5)
    assert Aura(AuraParams(use_aoi=False))._deadline(stale) == pytest.approx(2.0)


def test_urgent_tasks_go_online_and_strategic_tasks_wait_for_a_window():
    sim, pl, _ = _run("aura")
    urgent = [r for r in sim.records.values() if r.replica_of is None and r.task.urgent and r.dispatched_s is not None]
    strategic = [r for r in sim.records.values() if not r.task.urgent and r.dispatched_s is not None]
    assert all(r.dispatched_s == pytest.approx(r.task.arrival_s) or r.attempts > 1 for r in urgent)
    assert strategic and sum(r.dispatched_s > r.task.arrival_s for r in strategic) / len(strategic) > 0.9
    assert pl.log["tier1"] > 0 and pl.log["tier2"] > 0
    single, pl1, _ = _run("aura_singletier")
    assert pl1.log["tier2"] == 0


def test_runs_are_reproducible():
    a = compute_metrics(_run("aura", stress="monsoon_burst")[0])
    b = compute_metrics(_run("aura", stress="monsoon_burst")[0])
    a.pop("scheduling_overhead_us")
    b.pop("scheduling_overhead_us")
    assert a == b


def test_replication_counts_each_task_once_and_leaks_no_capacity():
    sim, pl, trace = _run("aura", params={"p_min": 1.0})  # replicate every critical task
    m = compute_metrics(sim)
    assert pl.log["replicated"] > 0 and m["replicated_tasks"] == pl.log["replicated"]
    assert m["tasks_total"] == len(trace.tasks)
    originals = [r for r in sim.records.values() if r.replica_of is None]
    assert sum(r.status == "completed" for r in originals) == round(m["completion_rate"] / 100 * len(originals))
    for ns in sim.nodes.values():
        assert abs(ns.committed_mi) < 1e-6 and abs(ns.committed_urgent_mi) < 1e-6
        assert not ns.queue and not ns.running


def test_anticipatory_reservation_reacts_to_warnings():
    _, pl, trace = _run("aura", stress="monsoon_burst", duration=1200)
    assert trace.signals
    log = pl.log["reservation"]
    assert log and max(e["warned_gateways"] for e in log) > 0
    _, st, _ = _run("aura_staticreserve", stress="monsoon_burst", duration=1200)
    assert not st.log["reservation"] and set(st.reserved.values()) == {AuraParams().static_share}
    _, none, _ = _run("aura_noreserve", stress="monsoon_burst", duration=1200)
    assert not none.reserved


def test_strategic_tasks_without_a_reachable_node_are_deferred_while_their_deadline_allows():
    aura = Aura(AuraParams())
    aura.reserved, aura.last_update = {}, 0.0
    aura.log = {"deferred": 0, "tier2": 0, "reservation": []}
    aura.count, aura.mean_len, aura.region_of = {}, 1000.0, {}
    view = SimpleNamespace(
        now=10.0, eligible=lambda t: [], nodes=[], _sim=SimpleNamespace(settings=SimpleNamespace(window_s=5.0))
    )
    soon = _task(id=1, priority="low", arrival_s=0.0, deadline_s=12.0)  # 10 + 5 > 12: give up
    later = _task(id=2, priority="low", arrival_s=0.0, deadline_s=600.0)
    out = aura.place_batch([soon, later], view)
    assert out == {1: None, 2: DEFER} and aura.log["deferred"] == 1


def test_evaluation_plugin_reports_tests_and_hypotheses():
    params = AuraEvaluationParams(
        scenarios=["normal", "cloud_disconnection"],
        replications=2,
        duration_s=300,
        intensity=40,
        algorithms=["aura", "aura_singletier", "mct", "edge_ward@aura"],
    )
    out = AuraEvaluation(params).run()
    assert out["kind"] == "simulation.aura_evaluation"
    assert set(out["table"]) == {"normal", "cloud_disconnection"}
    rows = out["tests"]["normal"]["urgent_deadline_success_rate"]["rows"]
    assert {r["other"] for r in rows} == {"AURA single tier", "MCT", "Edge-ward + AURA queue"}
    assert [h["id"] for h in out["hypotheses"]] == ["H1", "H2", "H3", "H4"]
    assert all(
        h["verdict"] in {"supported", "partly supported", "inconclusive", "not supported", "mixed", "not tested"}
        for h in out["hypotheses"]
    )
    assert "cloud_disconnection" in out["aura_logs"]
    assert parse("mct@aura") == ("mct", "aura") and parse("aura_noaoi") == ("aura_noaoi", "urgent_edf")
    with pytest.raises(ValueError, match="must be included"):
        AuraEvaluationParams(algorithms=["mct", "edge_ward"])
    with pytest.raises(ValueError, match="Unknown"):
        AuraEvaluationParams(algorithms=["aura", "nonsense"])
    assert not math.isnan(out["table"]["normal"]["aura"]["decision_value_pct"]["mean"])
