"""Simulator validation: queueing theory, invariants, determinism, failures and policy behaviour."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from smartagri_core import get_registry
from smartagri_core.sim import (
    LinkSpec,
    NodeSpec,
    SimSettings,
    TaskClass,
    Topology,
    WorkloadSpec,
    farm_topology,
    generate_trace,
    simulate,
)
from smartagri_core.sim.metrics import compute_metrics
from smartagri_core.sim.runner import Comparison, ComparisonParams, SingleRun, SingleRunParams
from smartagri_core.sim.topology import FarmTopologyParams, Layer, Router
from smartagri_core.sim.workload import agri_workload

PLACEMENTS = ["random", "round_robin", "least_loaded", "mct", "cloud_only", "edge_ward", "min_min", "max_min"]
DISCIPLINES = ["fcfs", "edf", "priority", "sjf"]


def policies(placement: str, discipline: str = "fcfs"):
    reg = get_registry()
    return reg.create(f"placement:{placement}"), reg.create(f"queue_discipline:{discipline}")


def single_server(mips: float = 1000.0) -> Topology:
    return Topology(
        nodes=(
            NodeSpec(id="gw", layer=Layer.IOT, cores=0, mips=0, ram_mb=0),
            NodeSpec(id="n0", layer=Layer.CLOUD, cores=1, mips=mips, ram_mb=1e6),
        ),
        links=(LinkSpec(a="gw", b="n0", bandwidth_mbps=1e6, latency_ms=0.0),),
    )


# --- 1. Queueing theory --------------------------------------------------------------------------


def test_mm1_mean_response_matches_theory() -> None:
    """M/M/1, lambda=0.6/s, mu=1/s: E[T] = 1/(mu-lambda) = 2.5 s and E[Wq] = rho/(mu-lambda) = 1.5 s.

    Long runs are needed: at this load consecutive response times are strongly correlated, so short runs are
    noisy (a 10-run check at lambda=0.7 gave 3.358 s +/- 0.020 s against the theoretical 3.333 s).
    """
    lam, mu = 0.6, 1.0
    topo = single_server()
    spec = WorkloadSpec(
        duration_s=100_000,
        classes=(
            TaskClass(
                name="mm1",
                rate_per_source_per_h=lam * 3600,
                length_mi=1000 / mu,
                length_dist="exponential",
                input_kb=0,
                output_kb=0,
                ram_mb=0,
                deadline_s=1e9,
            ),
        ),
    )
    responses, waits = [], []
    for seed in range(1, 5):
        sim = simulate(topo, generate_trace(spec, topo, seed), *policies("cloud_only"), SimSettings(failures=False))
        recs = sorted(sim.records.values(), key=lambda r: r.task.arrival_s)[1000:]  # drop warm-up
        responses.append(sum(r.response_s for r in recs) / len(recs))
        waits.append(sum(r.start_s - r.at_node_s for r in recs) / len(recs))
    assert sum(responses) / 4 == pytest.approx(1 / (mu - lam), rel=0.04)
    assert sum(waits) / 4 == pytest.approx((lam / mu) / (mu - lam), rel=0.06)


def test_transfer_time_formula() -> None:
    topo = Topology(
        nodes=(
            NodeSpec(id="a", layer=Layer.IOT, cores=0, mips=0),
            NodeSpec(id="b", layer=Layer.EDGE),
            NodeSpec(id="c", layer=Layer.CLOUD),
        ),
        links=(
            LinkSpec(a="a", b="b", bandwidth_mbps=8, latency_ms=10),
            LinkSpec(a="b", b="c", bandwidth_mbps=80, latency_ms=100),
        ),
    )
    # 1 MB = 8e6 bits: 1 s on the 8 Mbit/s hop + 0.1 s on the 80 Mbit/s hop + 0.11 s latency
    assert Router(topo).transfer_time("a", "c", 1e6) == pytest.approx(1.0 + 0.1 + 0.11)
    assert Router(topo).transfer_time("c", "c", 1e6) == 0.0


# --- 2. Invariants, for every policy combination --------------------------------------------------


@settings(max_examples=25, deadline=None)
@given(
    placement=st.sampled_from(PLACEMENTS),
    discipline=st.sampled_from(DISCIPLINES),
    seed=st.integers(0, 10_000),
    intensity=st.floats(1, 40),
    mtbf=st.sampled_from([0.0, 600.0]),
)
def test_invariants(placement: str, discipline: str, seed: int, intensity: float, mtbf: float) -> None:
    topo = farm_topology(FarmTopologyParams(farms=2, mtbf_edge_s=mtbf, mtbf_fog_s=mtbf, mttr_s=60))
    trace = generate_trace(agri_workload(600, intensity), topo, seed)
    sim = simulate(topo, trace, *policies(placement, discipline), SimSettings(), seed=seed)
    for rec in sim.records.values():
        assert rec.status in {"completed", "failed"}
        if rec.status == "completed":
            assert rec.task.arrival_s <= rec.at_node_s <= rec.start_s <= rec.finish_s <= rec.delivered_s
            assert rec.finish_s - rec.start_s == pytest.approx(rec.task.length_mi / topo.node[rec.node].mips)
    for ns in sim.nodes.values():
        assert ns.busy == 0 and not ns.running and ns.idle_j >= 0 and ns.dynamic_j >= -1e-9
        assert ns.busy_core_s <= ns.spec.cores * sim.now + 1e-6
    m = compute_metrics(sim)
    assert 0 <= m["deadline_success_rate"] <= m["completion_rate"] <= 100


# --- 3. Reproducibility and common random numbers -------------------------------------------------


def _deterministic(metrics: dict) -> dict:
    return {k: v for k, v in metrics.items() if k != "scheduling_overhead_us"}  # wall-clock, not simulated


def test_same_seed_same_results() -> None:
    a = SingleRun(SingleRunParams(placement="mct", seed=3, duration_s=900)).run()
    b = SingleRun(SingleRunParams(placement="mct", seed=3, duration_s=900)).run()
    assert _deterministic(a["metrics"]) == _deterministic(b["metrics"])
    assert a["provenance"]["trace_sha256"] == b["provenance"]["trace_sha256"]
    c = SingleRun(SingleRunParams(placement="mct", seed=4, duration_s=900)).run()
    assert a["provenance"]["trace_sha256"] != c["provenance"]["trace_sha256"]


def test_trace_does_not_depend_on_policy() -> None:
    topo = farm_topology()
    spec = agri_workload(600, 10)
    assert generate_trace(spec, topo, 9).sha256 == generate_trace(spec, topo, 9).sha256


def test_comparison_uses_common_random_numbers_and_reports_cis() -> None:
    p = ComparisonParams(placements=["cloud_only", "mct"], replications=3, duration_s=600)
    out = Comparison(p).run()
    assert out["data_origin"] == "synthetic"
    assert len(out["provenance"]["trace_sha256"]) == 3  # one trace per replication, shared by both policies
    by_rep = {}
    for run in out["runs"]:
        by_rep.setdefault(run["replication"], set()).add(run["metrics"]["tasks_total"])
    assert all(len(v) == 1 for v in by_rep.values())
    s = out["comparison"]["mct"]["mean_response_s"]
    assert s["n"] == 3 and s["ci_low"] <= s["mean"] <= s["ci_high"]


# --- 4. Policy behaviour --------------------------------------------------------------------------


def test_cloud_only_runs_everything_in_the_cloud() -> None:
    m = SingleRun(SingleRunParams(placement="cloud_only", duration_s=600)).run()["metrics"]
    assert m["share_cloud"] == 100 and m["share_edge"] == 0


def test_edge_ward_prefers_the_edge_under_light_load() -> None:
    m = SingleRun(SingleRunParams(placement="edge_ward", duration_s=600, intensity=1)).run()["metrics"]
    assert m["share_edge"] > m["share_cloud"]


def test_edf_beats_fcfs_on_deadlines_for_an_overloaded_node() -> None:
    topo = single_server(mips=1000)
    spec = WorkloadSpec(
        duration_s=2000,
        classes=(
            TaskClass(
                name="urgent",
                priority="critical",
                rate_per_source_per_h=1800,
                length_mi=500,
                input_kb=0,
                output_kb=0,
                ram_mb=0,
                deadline_s=3,
            ),
            TaskClass(
                name="bulk",
                priority="low",
                rate_per_source_per_h=600,
                length_mi=2500,
                input_kb=0,
                output_kb=0,
                ram_mb=0,
                deadline_s=300,
            ),
        ),
    )
    trace = generate_trace(spec, topo, 1)
    fcfs = compute_metrics(simulate(topo, trace, *policies("cloud_only", "fcfs")))
    edf = compute_metrics(simulate(topo, trace, *policies("cloud_only", "edf")))
    assert edf["urgent_deadline_success_rate"] > fcfs["urgent_deadline_success_rate"]


def test_failures_trigger_retries_or_failures() -> None:
    topo = farm_topology(FarmTopologyParams(farms=2, mtbf_edge_s=120, mtbf_fog_s=120, mttr_s=60))
    trace = generate_trace(agri_workload(1800, 10), topo, 2)
    with_retry = simulate(topo, trace, *policies("edge_ward"), SimSettings(retry_on_failure=True), seed=2)
    no_retry = simulate(topo, trace, *policies("edge_ward"), SimSettings(retry_on_failure=False), seed=2)
    assert compute_metrics(with_retry)["node_failures"] > 0
    lost = sum(r.status == "failed" for r in no_retry.records.values())
    retried = sum(r.attempts > 1 for r in with_retry.records.values())
    assert lost > 0 and retried > 0
    assert compute_metrics(with_retry)["completion_rate"] >= compute_metrics(no_retry)["completion_rate"]


def test_invalid_topology_rejected() -> None:
    topo = Topology(nodes=(NodeSpec(id="n0", layer=Layer.FOG),), links=())
    with pytest.raises(ValueError, match="IoT gateway"):
        simulate(
            topo,
            generate_trace(WorkloadSpec(classes=(TaskClass(name="x"),), sources=("n0",)), topo, 1),
            *policies("mct"),
        )


def test_metrics_have_no_nans_in_headline_for_normal_run() -> None:
    m = SingleRun(SingleRunParams(duration_s=600)).run()["metrics"]
    assert all(
        m[k] is not None and not (isinstance(m[k], float) and math.isnan(m[k]))
        for k in ["deadline_success_rate", "mean_response_s", "energy_dynamic_j"]
    )
