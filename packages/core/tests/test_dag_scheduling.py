"""HEFT and CPOP against the published example of Topcuoglu, Hariri and Wu (2002)."""

from __future__ import annotations

import pytest
from smartagri_core.registry import get_registry
from smartagri_core.sched.dag import (
    Platform,
    Workflow,
    check_schedule,
    cpop,
    heft,
    random_schedule,
    random_workflow,
    schedule_metrics,
    topcuoglu_example,
    upward_ranks,
)

PLAT = Platform(("P1", "P2", "P3"))


def test_upward_ranks_match_the_paper() -> None:
    ranks = upward_ranks(topcuoglu_example(), PLAT)
    assert ranks == pytest.approx([108.0, 77.0, 80.0, 80.0, 69.0, 63.333, 42.667, 35.667, 44.333, 14.667], abs=1e-3)


def test_heft_reproduces_the_published_schedule() -> None:
    wf = topcuoglu_example()
    s = heft(wf, PLAT)
    check_schedule(wf, PLAT, s)
    assert s.makespan == 80
    placed = {wf.name_of(i): (slot.processor + 1, slot.start, slot.finish) for i, slot in s.slots.items()}
    assert placed["n1"] == (3, 0, 9) and placed["n4"] == (2, 18, 26) and placed["n10"] == (2, 73, 80)
    assert [wf.name_of(i) for i in s.order][:4] == ["n1", "n3", "n4", "n2"]


def test_cpop_reproduces_the_published_length() -> None:
    wf = topcuoglu_example()
    s = cpop(wf, PLAT)
    check_schedule(wf, PLAT, s)
    assert s.makespan == 86


def test_random_graphs_are_valid_seeded_and_heft_beats_random() -> None:
    a = random_workflow(60, 4, ccr=1.0, seed=5)
    assert a == random_workflow(60, 4, ccr=1.0, seed=5) and a != random_workflow(60, 4, ccr=1.0, seed=6)
    a.validate()
    plat = Platform(tuple(f"P{k}" for k in range(4)))
    wins = 0
    for seed in range(20):
        wf = random_workflow(40, 4, seed=seed)
        h, r = heft(wf, plat), random_schedule(wf, plat, seed)
        check_schedule(wf, plat, h)
        check_schedule(wf, plat, r)
        wins += schedule_metrics(wf, h)["slr"] < schedule_metrics(wf, r)["slr"]
        assert schedule_metrics(wf, h)["slr"] >= 1.0 - 1e-9  # SLR can never beat the critical path
    assert wins >= 19


def test_cycles_are_rejected() -> None:
    wf = Workflow("cyclic", ((1.0,), (1.0,)), {(0, 1): 1.0, (1, 0): 1.0})
    with pytest.raises(ValueError, match="cycle"):
        heft(wf)


def test_plugins_run() -> None:
    reg = get_registry()
    reg.ensure_loaded()
    out = reg.create("scheduler:heft", {}).run()
    assert out["schedule"]["metrics"]["makespan"] == 80 and out["for_comparison"]["cpop"]["makespan"] == 86
    cmp = reg.create("simulation:dag_comparison", {"graphs": 8, "tasks": 30}).run()
    assert cmp["tests"]["slr"]["omnibus"]["test"] == "friedman"
    assert cmp["summary"]["slr"]["heft"]["mean"] < cmp["summary"]["slr"]["random"]["mean"]


def test_cli_runs_a_plugin(tmp_path) -> None:
    import json

    from smartagri_core.cli import main

    assert main(["plugins", "run", "scheduler:cpop", "--set", 'workflow="paper_example"', "--out", str(tmp_path)]) == 0
    assert json.loads((tmp_path / "result.json").read_text())["schedule"]["metrics"]["makespan"] == 86
    assert main(["plugins", "run", "optimizer:ga", "--out", str(tmp_path)]) == 2  # planned plugins never run
