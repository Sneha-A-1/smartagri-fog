"""Tests for the module-based (iFogSim-style) simulator and the EEG case-study reproduction."""

from __future__ import annotations

import pytest
from smartagri_core.sim.dataflow import (
    ActuatorSpec,
    AppEdge,
    Application,
    DataflowSettings,
    FogDevice,
    FogNetwork,
    SensorSpec,
    TupleMapping,
    simulate_dataflow,
)
from smartagri_core.sim.ifogsim_eeg import (
    LOOP,
    EEGCaseStudy,
    EEGCaseStudyParams,
    eeg_application,
    eeg_network,
    eeg_placement,
)

LOOP_KEY = " -> ".join(LOOP)


def _single_queue(rho: float, distribution: str) -> dict:
    """One device, Poisson arrivals, deterministic 1 ms service: an M/D/1 processor-sharing queue."""
    net = FogNetwork(
        {"cloud": FogDevice("cloud", 1000, 1e9, 1e9)},
        [SensorSpec("s", "cloud", "X", 1.0 / rho, 0.0, distribution)],  # mean interval in ms
        [ActuatorSpec("a", "cloud", "ACT", 0.0)],
    )
    app = Application(
        "q",
        ("m",),
        (AppEdge("X", "m", "X", 1000, 0, kind="sensor"), AppEdge("m", "ACT", "Y", 0, 0, kind="actuator")),
        (TupleMapping("m", "X", "Y"),),
        (("X", "m", "ACT"),),
    )
    return simulate_dataflow(app, net, {"m": frozenset({"cloud"})}, DataflowSettings(200_000, 1_000, seed=3))


def test_processor_sharing_matches_queueing_theory() -> None:
    # Processor sharing is insensitive to the service distribution: mean sojourn = S / (1 - rho).
    r = _single_queue(0.5, "exponential")
    loop = r["loops"]["X -> m -> ACT"]
    assert loop["count"] > 90_000
    assert loop["mean"] == pytest.approx(2.0, rel=0.04)
    assert r["devices"]["cloud"]["cpu_utilization"] == pytest.approx(0.5, abs=0.01)
    # deterministic arrivals never overlap, so each tuple takes exactly its service time
    assert _single_queue(0.5, "deterministic")["loops"]["X -> m -> ACT"]["max"] == pytest.approx(1.0)


def test_cloud_only_network_usage_matches_closed_form() -> None:
    app, net = eeg_application("B"), eeg_network(1, "B")
    r = simulate_dataflow(app, net, eeg_placement(app, net, "cloud_only"), DataflowSettings(20_000, 1_000, seed=1))
    # per phone: _SENSOR up and CONCENTRATION down (0.9 x 0.2 per ms, 500 B, 2+4+100 ms latency each way)
    # plus GLOBAL_GAME_STATE down every 100 ms (1000 B over the same 106 ms of latency)
    per_phone = 0.9 * 0.2 * 500 * 106 * 2 + 0.01 * 1000 * 106
    assert r["network_usage_kb"] == pytest.approx(4 * per_phone / 1000, rel=0.02)


def test_cloud_only_delay_is_latency_bound_plus_processing() -> None:
    app, net = eeg_application("A"), eeg_network(2, "A")
    r = simulate_dataflow(app, net, eeg_placement(app, net, "cloud_only"), DataflowSettings(5_000, 500, seed=1))
    latency_floor = 6 + 2 + 4 + 100 + 100 + 4 + 2 + 1  # Table VI, both directions, plus the display link
    processing = 2000 / 1000 + 3500 / 44800 + 14 / 1000
    assert latency_floor + processing <= r["loops"][LOOP_KEY]["mean"] < latency_floor + processing + 3


def test_placements_follow_ifogsim_rules() -> None:
    app = eeg_application("B")
    net = eeg_network(2, "B")
    cloud = eeg_placement(app, net, "cloud_only")
    assert cloud["concentration_calculator"] == {"cloud"} and len(cloud["client"]) == 8
    edge = eeg_placement(app, net, "edge_ward")
    # headset B: client (~512 MI/ms) leaves too little of a 1000-MIPS phone for the calculator (630 MI/ms),
    # so it moves up one level; four phones' load (2520) fits on a 2800-MIPS gateway
    assert edge["concentration_calculator"] == {"d-0", "d-1"} and edge["connector"] == {"cloud"}
    # headset A has half the rate, so the calculator fits on the phone itself
    app_a, net_a = eeg_application("A"), eeg_network(1, "A")
    assert len(eeg_placement(app_a, net_a, "edge_ward")["concentration_calculator"]) == 4


def test_same_seed_same_result_and_tree_validation() -> None:
    app, net = eeg_application("B"), eeg_network(1, "B")
    pl = eeg_placement(app, net, "edge_ward")
    a = simulate_dataflow(app, net, pl, DataflowSettings(3_000, 300, seed=7))
    b = simulate_dataflow(app, net, pl, DataflowSettings(3_000, 300, seed=7))
    c = simulate_dataflow(app, net, pl, DataflowSettings(3_000, 300, seed=8))
    assert a == b and a["loops"][LOOP_KEY]["count"] != c["loops"][LOOP_KEY]["count"]
    assert net.next_hop("m-0-0", "cloud") == "d-0" and net.next_hop("cloud", "m-0-1") == "proxy-server"
    with pytest.raises(ValueError, match="exactly one root"):
        FogNetwork({"a": FogDevice("a", 1, 1, 1), "b": FogDevice("b", 1, 1, 1)}, [], [])


def test_case_study_plugin_reports_agreement_honestly() -> None:
    params = EEGCaseStudyParams(configs=[1, 3, 5], replications=2, duration_s=3, warmup_s=0.5)
    r = EEGCaseStudy(params).run()
    assert len(r["rows"]) == 12 and r["data_origin"] == "synthetic"
    checks = {c["claim"]: c["holds"] for c in r["checks"]}
    assert checks["Edge-ward has lower control-loop delay than cloud-only in every configuration"]
    assert checks["Cloud-only delay within 10% of the paper for Configs 1-3"]
    assert checks["Cloud-only network usage within 20% of the paper in every configuration"]
    assert checks["Edge-ward network usage within 20% of the paper in every configuration"] is False
    # the paper's sharp rise at large configurations is not produced by this model, and must be reported as such
    assert checks["Cloud-only delay rises sharply at Configs 4-5 (paper: 4 to 20 times Config 3)"] is False
    row = next(x for x in r["rows"] if (x["headset"], x["placement"], x["config"]) == ("B", "cloud_only", 5))
    assert row["paper_network_usage_kb"] == 1278
    assert row["network_usage_kb"]["mean"] == pytest.approx(1278, rel=0.05)
