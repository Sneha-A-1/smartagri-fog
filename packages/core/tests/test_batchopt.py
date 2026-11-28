"""Batch-placement optimisers: correctness against brute force, budgets, determinism and simulator use."""

from __future__ import annotations

import numpy as np
import pytest
import smartagri_core.plugins  # noqa: F401
from smartagri_core.registry import get_registry
from smartagri_core.sched.batchopt import (
    SOLVERS,
    BatchProblem,
    SolverSettings,
    brute_force,
    crowding_distance,
    non_dominated_sort,
    solve,
)
from smartagri_core.sim.engine import simulate
from smartagri_core.sim.metrics import compute_metrics
from smartagri_core.sim.opt_benchmark import OptimizerBenchmark, OptimizerBenchmarkParams
from smartagri_core.sim.opt_placement import problem_from_view
from smartagri_core.sim.policies import MinMin
from smartagri_core.sim.runner import ScenarioParams
from smartagri_core.sim.workload import generate_trace


def tiny(seed: int, n: int = 7, m: int = 4) -> BatchProblem:
    r = np.random.default_rng(seed)
    exe = r.uniform(0.2, 3, (n, 1)) * r.uniform(0.3, 2, (1, m))
    return BatchProblem(
        task_ids=list(range(n)),
        node_ids=[f"n{j}" for j in range(m)],
        cand=np.tile(np.arange(m), (n, 1)),
        tx_in_s=r.uniform(0, 0.5, (n, m)),
        tx_out_s=r.uniform(0, 0.2, (n, m)),
        exec_s=exe,
        energy_j=exe * r.uniform(1, 20, (1, m)),
        cost=exe * np.array([0.0] * (m - 1) + [0.01]),
        length_mi=r.uniform(500, 3000, n),
        slack_s=r.uniform(1, 6, n),
        age_s=r.uniform(0, 2, n),
        priority_weight=r.choice([4.0, 2.0, 1.0, 0.5], n),
        backlog_mi=r.uniform(0, 3000, m),
        capacity_mips=r.uniform(1000, 8000, m),
    )


@pytest.mark.parametrize("key", list(SOLVERS))
def test_same_seed_same_answer_and_exact_budget(key):
    p = tiny(3)
    a = solve(key, p, np.random.default_rng(7), SolverSettings(300, 12))
    b = solve(key, p, np.random.default_rng(7), SolverSettings(300, 12))
    assert np.array_equal(a.genes, b.genes) and a.fitness == b.fitness
    assert a.evaluations == 300
    best = [h[1] for h in a.history]
    assert all(x >= y for x, y in zip(best, best[1:], strict=False)), "best-so-far must never get worse"
    assert a.history[-1][0] == 300


@pytest.mark.parametrize("key", list(SOLVERS))
def test_seeded_solvers_never_worse_than_the_heuristics(key):
    for s in range(4):
        p = tiny(s, n=12)
        res = solve(key, p, np.random.default_rng(s), SolverSettings(200, 10), seed_heuristics=True)
        heur = p.fitness(np.vstack([p.min_min(), p.greedy_mct()])).min()
        assert res.fitness <= heur + 1e-12


def test_ga_and_aco_usually_find_the_exact_optimum_and_beat_random_search():
    found = {"ga": 0, "aco": 0}
    gap = {"ga": [], "aco": [], "random_search": []}
    for s in range(10):
        p = tiny(s)
        _, opt = brute_force(p)
        for key in gap:
            f = solve(key, p, np.random.default_rng(s), SolverSettings(500, 20), seed_heuristics=False).fitness
            assert f >= opt - 1e-12, "nothing can beat the exact optimum"
            gap[key].append(f - opt)
            if key in found and f - opt < 1e-12:
                found[key] += 1
    assert found["ga"] >= 6 and found["aco"] >= 6
    assert np.mean(gap["ga"]) < np.mean(gap["random_search"])
    assert np.mean(gap["aco"]) < np.mean(gap["random_search"])


def test_queue_model_counts_earlier_tasks_on_the_same_node():
    p = tiny(1, n=3, m=2)
    both0 = np.array([[0, 0, 0]])
    f = p.finish_times(both0)[0]
    wait2 = (p.backlog_mi[0] + p.length_mi[0] + p.length_mi[1]) / p.capacity_mips[0]
    assert f[2] == pytest.approx(p.tx_in_s[2, 0] + wait2 + p.exec_s[2, 0] + p.tx_out_s[2, 0])


def test_non_dominated_sort_and_crowding():
    obj = np.array([[1, 5], [2, 3], [4, 1], [3, 4], [5, 5]], dtype=float)
    assert non_dominated_sort(obj).tolist() == [0, 0, 0, 1, 2]
    cd = crowding_distance(obj[:3])
    assert np.isinf(cd[0]) and np.isinf(cd[2]) and np.isfinite(cd[1])


def test_nsga2_front_is_mutually_non_dominated():
    p = tiny(5, n=10)
    res = solve("nsga2", p, np.random.default_rng(0), SolverSettings(400, 16))
    assert res.front is not None and len(res.front) >= 1
    assert (non_dominated_sort(res.front) == 0).all()


def _captured_problems(duration_s: float = 120.0):
    sp = ScenarioParams(duration_s=duration_s)
    topo, spec, settings = sp.build()
    trace = generate_trace(spec, topo, 1)
    seen = []

    class Capture(MinMin):
        def place_batch(self, tasks, view):
            prob = problem_from_view(tasks, view)
            if prob is not None and not seen:
                t0 = next(t for t in tasks if t.id == prob.task_ids[0])
                node = prob.node_ids[prob.cand[0, 0]]
                seen.append((prob, view.estimate_finish(t0, node) - view.now))
            return super().place_batch(tasks, view)

    simulate(topo, trace, Capture(), get_registry().create("queue_discipline:fcfs"), settings, seed=1)
    return seen


def test_problem_from_view_matches_cluster_view_estimate():
    prob, expected = _captured_problems()[0]
    genes = np.zeros((1, prob.n_tasks), dtype=np.int64)
    assert prob.finish_times(genes)[0, 0] == pytest.approx(expected)


@pytest.mark.parametrize("key", ["ga", "nsga2"])
def test_metaheuristic_placement_is_reproducible_in_the_simulator(key):
    sp = ScenarioParams(duration_s=120)
    topo, spec, settings = sp.build()
    trace = generate_trace(spec, topo, 2)
    reg = get_registry()

    def run():
        placement = reg.create(f"placement:{key}", {"budget": 60, "pop_size": 10})
        sim = simulate(topo, trace, placement, reg.create("queue_discipline:fcfs"), settings, seed=2)
        return compute_metrics(sim), [r.node for r in sim.records.values()]

    m1, n1 = run()
    m2, n2 = run()
    assert n1 == n2
    assert m1["completion_rate"] == 100.0
    assert m1["deadline_success_rate"] == m2["deadline_success_rate"]


def test_registry_status_of_optimisers():
    reg = get_registry()
    for key in ["ga", "pso", "aco", "gwo", "woa", "nsga2", "random_search"]:
        assert reg.get(f"optimizer:{key}").runnable
        assert reg.get(f"placement:{key}").runnable
        assert not reg.get(f"placement:{key}").startable
    assert not reg.get("optimizer:dqn").runnable
    assert reg.get("simulation:optimizer_benchmark").startable


def test_benchmark_is_deterministic_and_complete():
    params = OptimizerBenchmarkParams(
        duration_s=120, instances=2, replications=2, budget=60, pop_size=10, algorithms=["ga", "aco", "nsga2"]
    )
    a = OptimizerBenchmark(params).run()
    b = OptimizerBenchmark(params).run()
    strip = [{k: v for k, v in r.items() if k != "runtime_ms"} for r in a["runs"]]
    assert strip == [{k: v for k, v in r.items() if k != "runtime_ms"} for r in b["runs"]]
    assert a["kind"] == "simulation.optimizer_benchmark"
    assert len(a["runs"]) == 2 * 2 * (3 + 2)
    assert set(a["table"]) == {"min_min", "greedy_mct", "ga", "aco", "nsga2"}
    assert a["pareto"] and a["pareto"]["front"] and "ga" in a["pareto"]["points"]
    assert len(a["convergence"]["evaluations"]) == len(a["convergence"]["mean"]["ga"])
    assert a["stats"]["fitness"]["verdict"]
    for inst in a["instances"]:
        assert 0 <= inst["unavoidable_weighted_miss"] <= 1
