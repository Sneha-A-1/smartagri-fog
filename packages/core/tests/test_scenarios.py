"""Stress scenarios: data age, surges, early warnings, scheduled outages and the new metrics."""

from __future__ import annotations

import math

import pytest
import smartagri_core.plugins  # noqa: F401
from smartagri_core.registry import get_registry
from smartagri_core.sim.engine import Outage, simulate
from smartagri_core.sim.metrics import compute_metrics, decision_value
from smartagri_core.sim.runner import ScenarioParams
from smartagri_core.sim.scenarios import FRESHNESS
from smartagri_core.sim.workload import Task, generate_trace


def _build(stress: str, duration_s: float = 1200.0, intensity: float = 20.0):
    return ScenarioParams(stress=stress, duration_s=duration_s, intensity=intensity).build()


def test_original_workload_is_unchanged():
    topo, spec, settings = ScenarioParams().build()
    trace = generate_trace(spec, topo, 1)
    # Hash of the default trace before scenarios existed (Phase 4b); any change would break reproducibility.
    assert trace.sha256 == "864537c2f8ee6ffd62f77c1e0b52fc2ea5f7c48eab4e79c120e23507c0d1aa87"
    assert not trace.signals and not settings.outages
    assert all(math.isinf(t.freshness_s) and t.data_time_s is None for t in trace.tasks)


def test_normal_scenario_adds_data_age_but_keeps_arrivals():
    topo, spec, _ = _build("normal")
    _, base_spec, _ = _build("none")
    fresh = generate_trace(spec, topo, 3)
    base = generate_trace(base_spec, topo, 3)
    assert [(t.arrival_s, t.source, t.cls) for t in fresh.tasks] == [(t.arrival_s, t.source, t.cls) for t in base.tasks]
    for t in fresh.tasks:
        age, bound = FRESHNESS[t.cls]
        assert t.arrival_s - age - 1e-9 <= t.data_time <= t.arrival_s
        assert t.freshness_s == (bound if bound is not None else math.inf)
        assert t.effective_deadline == min(t.abs_deadline, t.data_time + t.freshness_s)


def test_surge_adds_urgent_tasks_only_inside_its_window_and_keeps_the_base_trace():
    topo, spec, _ = _build("monsoon_burst")
    _, base_spec, _ = _build("normal")
    surge = spec.surges[0]
    with_surge = generate_trace(spec, topo, 4)
    base = generate_trace(base_spec, topo, 4)
    key = {(t.arrival_s, t.source, t.cls) for t in base.tasks}
    extra = [t for t in with_surge.tasks if (t.arrival_s, t.source, t.cls) not in key]
    assert len(with_surge.tasks) == len(base.tasks) + len(extra)
    assert extra and all(t.urgent for t in extra)
    assert all(surge.start_s <= t.arrival_s <= surge.start_s + surge.duration_s for t in extra)
    gateways = {n.id for n in topo.nodes if str(n.layer) == "iot"}
    assert len({t.source for t in extra}) == round(surge.source_share * len(gateways))
    # Roughly factor - 1 = 5 extra urgent arrivals for every normal one on affected gateways during the surge.
    affected = {t.source for t in extra}
    normal_in_window = [
        t
        for t in base.tasks
        if t.urgent and t.source in affected and surge.start_s <= t.arrival_s <= surge.start_s + surge.duration_s
    ]
    assert 3.5 < len(extra) / len(normal_in_window) < 6.5


def test_warnings_follow_the_model_and_are_never_seen_early():
    topo, spec, settings = _build("heat_wave", duration_s=3600)
    trace = generate_trace(spec, topo, 5)
    true = [s for s in trace.signals if s.true]
    assert true and all(s.time_s <= spec.surges[0].start_s for s in true)
    precision = len(true) / len(trace.signals)
    assert abs(precision - spec.warnings.precision) < 0.1
    seen = []

    from smartagri_core.sim.policies import MinimumCompletionTime as MCT

    class Watch(MCT):
        def place(self, task, view):
            seen.append((view.now, max((s.time_s for s in view.signals_until_now()), default=-1.0)))
            return super().place(task, view)

    simulate(topo, trace, Watch(), get_registry().create("queue_discipline:fcfs"), settings, seed=5)
    assert all(latest <= now for now, latest in seen)


def test_cloud_outage_stops_cloud_work_and_is_reproducible():
    topo, spec, settings = _build("cloud_disconnection")
    outage = settings.outages[0]
    trace = generate_trace(spec, topo, 6)
    reg = get_registry()

    def run():
        sim = simulate(
            topo, trace, reg.create("placement:cloud_only"), reg.create("queue_discipline:fcfs"), settings, seed=6
        )
        return sim, compute_metrics(sim)

    sim, m = run()
    cloud = {n.id for n in topo.nodes if str(n.layer) == "cloud"}
    for r in sim.records.values():
        if r.node in cloud and r.start_s is not None and r.status == "completed":
            assert not (outage.start_s < r.start_s < outage.start_s + outage.duration_s)
    assert m["deadline_success_rate"] < 80, "cloud-only cannot serve tasks while the cloud is unreachable"
    assert m["autonomy_ratio"] == 0.0
    _, m2 = run()
    m.pop("scheduling_overhead_us")
    m2.pop("scheduling_overhead_us")
    assert m == m2


def test_outage_targets_must_exist_and_random_failures_keep_one_chain():
    topo, spec, settings = _build("none", duration_s=600)
    trace = generate_trace(spec, topo, 7)
    reg = get_registry()
    bad = settings.model_copy(update={"outages": (Outage(target="nowhere", start_s=10, duration_s=10),)})
    with pytest.raises(ValueError, match="matches no computing node"):
        simulate(topo, trace, reg.create("placement:mct"), reg.create("queue_discipline:fcfs"), bad, seed=1)
    # Frequent random fog failures plus a scheduled fog outage: the run finishes and stays reproducible.
    p = ScenarioParams(stress="fog_failure", duration_s=600, mtbf_fog_s=120, mttr_s=30)
    topo2, spec2, settings2 = p.build()
    trace2 = generate_trace(spec2, topo2, 8)
    a = compute_metrics(
        simulate(topo2, trace2, reg.create("placement:mct"), reg.create("queue_discipline:fcfs"), settings2, seed=8)
    )
    b = compute_metrics(
        simulate(topo2, trace2, reg.create("placement:mct"), reg.create("queue_discipline:fcfs"), settings2, seed=8)
    )
    a.pop("scheduling_overhead_us")
    b.pop("scheduling_overhead_us")  # wall-clock decision time varies
    assert a == b and a["node_failures"] >= 2


def _task(**kw) -> Task:
    base = {
        "id": 0,
        "cls": "x",
        "category": "x",
        "priority": "critical",
        "source": "g",
        "arrival_s": 0.0,
        "length_mi": 1.0,
        "input_bytes": 0.0,
        "output_bytes": 0.0,
        "ram_mb": 0.0,
        "deadline_s": 2.0,
        "result_to_source": False,
    }
    return Task(**(base | kw))


def test_decision_value_uses_the_effective_deadline():
    t = _task(data_time_s=-29.0, freshness_s=30.0)  # stale at t = 1 s, before the 2 s deadline
    assert t.effective_deadline == pytest.approx(1.0)
    assert decision_value(t, 0.5) == 4.0
    assert decision_value(t, 3.0) == pytest.approx(4.0 * 0.5)  # one deadline (2 s) late: half the value
    assert decision_value(t, 1.0 + 6.1) == 0.0  # more than three deadlines late
    assert decision_value(t, None) == 0.0


def test_comparison_reports_scenario_events_and_stress_metrics():
    out = (
        get_registry()
        .create(
            "simulation:comparison",
            {"stress": "fog_failure", "duration_s": 300, "replications": 2, "placements": ["mct", "edge_ward"]},
        )
        .run()
    )
    assert out["scenario_events"][0]["kind"] == "outage"
    assert "aoi_violation_rate" in out["headline_metrics"]
    assert out["comparison"]["mct"]["decision_value_pct"]["mean"] is not None
