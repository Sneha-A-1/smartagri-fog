"""Optimiser benchmark: every solver on the same frozen batch decisions, with the same evaluation budget.

1. One simulation of the scenario runs under Min-Min. At every batch window the decision the scheduler faced
   (tasks, eligible nodes, queues, links) is frozen as a :class:`BatchProblem`.
2. A number of these windows, evenly spaced through the run, become the benchmark instances.
3. Each solver runs on each instance once per replication, with a replication-specific seed and the same
   evaluation budget. Min-Min and greedy MCT are evaluated once per instance (they are deterministic).
4. Final fitness is compared with the Friedman test, Holm-corrected Wilcoxon tests and Vargha-Delaney A12,
   blocking on (instance, replication).

All fitness values are the planner's model estimates for that window, not simulated outcomes. To see what
the optimisers change end to end, compare the batch placements in Experiments or the policy comparison.
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
from pydantic import Field, model_validator

from smartagri_core.progress import ProgressReporter, null_progress
from smartagri_core.registry import PluginKind, get_registry, register
from smartagri_core.sched.batchopt import (
    OBJECTIVE_INFO,
    OBJECTIVES,
    SOLVER_NAMES,
    BatchProblem,
    SolverKey,
    SolverSettings,
    solve,
)
from smartagri_core.sim.engine import simulate
from smartagri_core.sim.opt_placement import WeightParams, problem_from_view
from smartagri_core.sim.policies import ClusterView, MinMin
from smartagri_core.sim.runner import ScenarioParams, _environment
from smartagri_core.sim.workload import Task, generate_trace
from smartagri_core.stats import compare, summarize
from smartagri_core.status import CapabilityStatus, DataOrigin

BASELINES = ["min_min", "greedy_mct"]


class OptimizerBenchmarkParams(ScenarioParams, WeightParams):
    algorithms: list[SolverKey] = Field(
        default_factory=lambda: ["random_search", "ga", "pso", "aco", "gwo", "woa", "nsga2"],
        min_length=1,
        description="Optimisers to compare. Min-Min and greedy MCT are always included as reference points.",
    )
    instances: int = Field(6, ge=1, le=50, description="Batch windows used as benchmark problems.")
    replications: int = Field(10, ge=2, le=100, description="Runs per optimiser and instance, each with its own seed.")
    budget: int = Field(1000, title="Evaluation budget", ge=20, le=200_000, description="Evaluations per run.")
    pop_size: int = Field(20, title="Population size", ge=4, le=500, description="Individuals, particles or ants.")
    seed_heuristics: bool = Field(
        True, description="Include Min-Min and greedy MCT in each optimiser's starting population."
    )
    min_tasks: int = Field(
        5,
        title="Smallest window",
        ge=2,
        le=500,
        description="Only windows with at least this many tasks become instances.",
        json_schema_extra={"x-advanced": True},
    )
    base_seed: int = Field(1, title="Seed", ge=0, description="Seeds the workload and every optimiser run.")

    @model_validator(mode="after")
    def _unique(self) -> OptimizerBenchmarkParams:
        if len(set(self.algorithms)) != len(self.algorithms):
            raise ValueError("Each optimiser may appear only once")
        if self.pop_size > self.budget:
            raise ValueError("The population cannot be larger than the evaluation budget")
        return self


class _Recorder(MinMin):
    """Min-Min that also freezes every decision it makes."""

    def __init__(self, weights) -> None:
        super().__init__()
        self.weights = weights
        self.problems: list[tuple[float, BatchProblem]] = []

    def place_batch(self, tasks: list[Task], view: ClusterView) -> dict[int, str | None]:
        problem = problem_from_view(tasks, view, self.weights)
        if problem is not None:
            self.problems.append((view.now, problem))
        return super().place_batch(tasks, view)


def capture_problems(p: OptimizerBenchmarkParams) -> tuple[list[tuple[float, BatchProblem]], dict[str, Any]]:
    topo, spec, settings = p.build()
    trace = generate_trace(spec, topo, p.base_seed)
    rec = _Recorder(p.weights())
    simulate(topo, trace, rec, get_registry().create("queue_discipline:fcfs"), settings, seed=p.base_seed)
    usable = [(t, pr) for t, pr in rec.problems if pr.n_tasks >= p.min_tasks]
    if not usable:
        raise ValueError(
            f"No batch window had {p.min_tasks} or more tasks. Raise the workload intensity or the batch window."
        )
    idx = sorted({int(round(x)) for x in np.linspace(0, len(usable) - 1, min(p.instances, len(usable)))})
    provenance = {
        "topology_sha256": topo.sha256,
        "trace_sha256": trace.sha256,
        "windows": len(rec.problems),
        "eligible_windows": len(usable),
    }
    return [usable[i] for i in idx], provenance


def _curve(history: list[tuple[int, float]], grid: np.ndarray) -> list[float]:
    evals = np.array([h[0] for h in history])
    best = np.array([h[1] for h in history])
    pos = np.searchsorted(evals, grid, side="right") - 1
    return [float(best[i]) if i >= 0 else math.nan for i in pos]


def _clean(x: Any) -> Any:
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


@register(
    kind=PluginKind.SIMULATION,
    key="optimizer_benchmark",
    name="Optimiser benchmark (batch placement)",
    version="1.0.0",
    status=CapabilityStatus.IMPLEMENTED,
    summary="Compares GA, PSO, ACO, GWO, WOA, NSGA-II and random search on identical frozen scheduling windows.",
    description=(
        "Freezes real batch decisions from a simulated farm network, then gives every optimiser the same "
        "evaluation budget on the same problems. Reports convergence curves, an NSGA-II Pareto front, run "
        "times and Friedman/Wilcoxon statistics. Fitness values are the scheduler's estimates for a window."
    ),
    params=OptimizerBenchmarkParams,
    layers=["edge", "fog", "cloud"],
    outputs=["Convergence curves", "Pareto front", "Final fitness with statistics", "Run time per optimiser"],
    phase=4,
    tags=["simulation", "optimisation", "experiment"],
)
class OptimizerBenchmark:
    def __init__(self, params: OptimizerBenchmarkParams) -> None:
        self.p = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        p = self.p
        progress(0.02, "Simulating the scenario under Min-Min to capture scheduling windows")
        problems, provenance = capture_problems(p)
        settings = SolverSettings(p.budget, p.pop_size)
        algs = BASELINES + list(p.algorithms)
        grid = np.unique(np.round(np.linspace(p.pop_size, p.budget, 40)).astype(int))
        runs: list[dict[str, Any]] = []
        curves: dict[str, list[list[float]]] = {a: [] for a in p.algorithms}
        pareto: dict[str, Any] | None = None
        total = len(problems) * p.replications * len(p.algorithms)
        done = 0
        for ii, (_t, prob) in enumerate(problems):
            fixed = {"min_min": prob.min_min(), "greedy_mct": prob.greedy_mct()}
            fixed_obj = {k: prob.objectives(g[None])[0] for k, g in fixed.items()}
            for r in range(p.replications):
                for k in BASELINES:
                    obj = fixed_obj[k]
                    runs.append(self._row(ii, r, k, float(prob.scalarize(obj[None])[0]), obj, 0, 0.0))
                for ai, key in enumerate(p.algorithms):
                    rng = np.random.default_rng([p.base_seed, ii, r, ai])
                    t0 = time.perf_counter()
                    res = solve(key, prob, rng, settings, p.seed_heuristics)
                    ms = (time.perf_counter() - t0) * 1000
                    runs.append(self._row(ii, r, key, res.fitness, res.objectives, res.evaluations, ms))
                    curves[key].append(_curve(res.history, grid))
                    if key == "nsga2" and ii == 0 and r == 0 and res.front is not None:
                        pareto = {"front": [dict(zip(OBJECTIVES, map(float, f), strict=True)) for f in res.front]}
                    done += 1
                    progress(0.05 + 0.9 * done / total, f"Run {done} of {total}: {SOLVER_NAMES[key]}")

        if pareto is not None:
            pareto["points"] = {
                row["algorithm"]: row["objectives"] for row in runs if row["instance"] == 0 and row["replication"] == 0
            }

        def column(alg: str, field: str) -> list[float]:
            return [row[field] for row in runs if row["algorithm"] == alg]

        def obj_column(alg: str, obj: str) -> list[float]:
            return [row["objectives"][obj] for row in runs if row["algorithm"] == alg]

        mm = column("min_min", "fitness")
        table: dict[str, Any] = {}
        for a in algs:
            fit = column(a, "fitness")
            impr = [100.0 * (b - f) / b for f, b in zip(fit, mm, strict=True) if b > 0]
            table[a] = {
                "name": SOLVER_NAMES[a],
                "fitness": summarize(fit),
                "improvement_vs_min_min_pct": summarize(impr) if impr else None,
                "better_than_min_min_pct": 100.0 * float(np.mean([f < b - 1e-12 for f, b in zip(fit, mm, strict=True)]))
                if fit
                else math.nan,
                "runtime_ms": summarize(column(a, "runtime_ms")) if a not in BASELINES else None,
                "objectives": {o: summarize(obj_column(a, o)) for o in OBJECTIVES},
            }
        # Statistics are keyed by display name, so verdicts read "Genetic Algorithm is better", not "ga".
        stats = {"fitness": compare({SOLVER_NAMES[a]: column(a, "fitness") for a in algs}, higher_is_better=False)}
        for o in ("weighted_miss", "energy_j"):
            stats[o] = compare({SOLVER_NAMES[a]: obj_column(a, o) for a in algs}, higher_is_better=False)

        convergence = {
            "evaluations": grid.tolist(),
            "mean": {a: np.nanmean(np.array(c), axis=0).tolist() for a, c in curves.items()},
            "reference": {k: float(np.mean(column(k, "fitness"))) for k in BASELINES},
        }
        best = min(p.algorithms, key=lambda a: table[a]["fitness"]["mean"])
        return _clean(
            {
                "data_origin": str(DataOrigin.SYNTHETIC),
                "kind": "simulation.optimizer_benchmark",
                "params": p.model_dump(mode="json"),
                "provenance": {**provenance, **_environment()},
                "objective_info": {k: list(v) for k, v in OBJECTIVE_INFO.items()},
                "names": {a: SOLVER_NAMES[a] for a in algs},
                "instances": [
                    {
                        "index": i,
                        "time_s": round(t, 1),
                        "tasks": pr.n_tasks,
                        "nodes": len(pr.node_ids),
                        "log10_space": float(np.log10(pr.n_cand.astype(float)).sum()),
                        "min_min_fitness": float(pr.fitness(pr.min_min()[None])[0]),
                        "unavoidable_weighted_miss": pr.unavoidable_miss(),
                    }
                    for i, (t, pr) in enumerate(problems)
                ],
                "table": table,
                "stats": stats,
                "convergence": convergence,
                "pareto": pareto,
                "runs": runs,
                "summary": {
                    "instances": len(problems),
                    "replications": p.replications,
                    "runs": len(runs),
                    "budget": p.budget,
                    "best_mean_fitness": SOLVER_NAMES[best],
                    "verdict": stats["fitness"]["verdict"],
                },
            }
        )

    @staticmethod
    def _row(ii: int, r: int, alg: str, fitness: float, obj: np.ndarray, evals: int, ms: float) -> dict[str, Any]:
        return {
            "instance": ii,
            "replication": r,
            "algorithm": alg,
            "fitness": float(fitness),
            "objectives": dict(zip(OBJECTIVES, map(float, obj), strict=True)),
            "evaluations": evals,
            "runtime_ms": round(ms, 3),
        }
