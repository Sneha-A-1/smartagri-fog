"""Metaheuristic batch placements: GA, PSO, ACO, GWO, WOA, NSGA-II and random search inside the simulator.

Each batch window the simulator hands the waiting tasks to ``place_batch``. The policy freezes the current
cluster state into a :class:`~smartagri_core.sched.batchopt.BatchProblem`, runs the chosen solver for a fixed
number of objective evaluations, and returns the best mapping found. The policy's random generator comes
from the simulation seed, so a run is reproducible.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from smartagri_core.registry import PluginKind, register
from smartagri_core.sched.batchopt import (
    PRIORITY_WEIGHT,
    SOLVER_NAMES,
    BatchProblem,
    OptResult,
    SolverSettings,
    Weights,
    solve,
)
from smartagri_core.sim.policies import ALL_LAYERS, ClusterView, Placement
from smartagri_core.sim.workload import Task
from smartagri_core.status import CapabilityStatus

IMPL = CapabilityStatus.IMPLEMENTED


def problem_from_view(
    tasks: Sequence[Task],
    view: ClusterView,
    weights: Weights | None = None,
    capacity_scale: dict[str, float] | None = None,
) -> BatchProblem | None:
    """Freeze one batch decision. Tasks with no eligible node are left out (the caller maps them to None).

    ``capacity_scale`` shrinks a node's usable capacity in the planner's model (AURA leaves the share it has
    reserved for urgent work out of the strategic tier's plan)."""
    specs = {n.id: n for n in view.nodes}
    node_ids = sorted(specs)
    index = {nid: j for j, nid in enumerate(node_ids)}
    rows = [(t, [n.id for n in view.eligible(t)]) for t in tasks]
    rows = [(t, sorted(c, key=index.__getitem__)) for t, c in rows if c]
    if not rows:
        return None
    n, kmax = len(rows), max(len(c) for _, c in rows)
    cand = np.full((n, kmax), -1, dtype=np.int64)
    tx_in, tx_out, exe, energy, cost = (np.zeros((n, kmax)) for _ in range(5))
    for i, (t, cands) in enumerate(rows):
        for k, nid in enumerate(cands):
            spec = specs[nid]
            cand[i, k] = index[nid]
            exe[i, k] = t.length_mi / spec.mips
            tx_in[i, k] = view.transfer_time(t.source, nid, t.input_bytes)
            tx_out[i, k] = view.transfer_time(nid, t.source, t.output_bytes) if t.result_to_source else 0.0
            energy[i, k] = (spec.p_max_w - spec.p_idle_w) / spec.cores * exe[i, k]
            cost[i, k] = spec.cost_per_core_s * exe[i, k]
    capacity = np.array([specs[nid].mips * specs[nid].cores for nid in node_ids], dtype=float)
    backlog = np.array([view.backlog_s(nid) for nid in node_ids]) * capacity
    if capacity_scale:
        capacity = capacity * np.array([max(capacity_scale.get(nid, 1.0), 1e-3) for nid in node_ids])
    ts = [t for t, _ in rows]
    return BatchProblem(
        task_ids=[t.id for t in ts],
        node_ids=node_ids,
        cand=cand,
        tx_in_s=tx_in,
        tx_out_s=tx_out,
        exec_s=exe,
        energy_j=energy,
        cost=cost,
        length_mi=np.array([t.length_mi for t in ts], dtype=float),
        slack_s=np.array([t.abs_deadline - view.now for t in ts], dtype=float),
        age_s=np.array([view.now - t.arrival_s for t in ts], dtype=float),
        priority_weight=np.array([PRIORITY_WEIGHT.get(t.priority, 1.0) for t in ts], dtype=float),
        backlog_mi=backlog,
        capacity_mips=capacity,
        weights=weights or Weights(),
    )


class SolverParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget: int = Field(
        400,
        title="Evaluation budget",
        ge=20,
        le=200_000,
        description="Objective evaluations per decision. Keep it equal across optimisers for a fair comparison.",
    )
    pop_size: int = Field(20, title="Population size", ge=4, le=500, description="Individuals, particles or ants.")
    seed_heuristics: bool = Field(
        True, description="Start from Min-Min and greedy MCT solutions as well as random ones."
    )


class WeightParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    w_deadline: float = Field(
        1.0, title="Weight: deadline misses", ge=0, description="Priority-weighted share of estimated misses."
    )
    w_response: float = Field(
        0.1,
        title="Weight: response time",
        ge=0,
        description="Mean response relative to its lower bound.",
        json_schema_extra={"x-advanced": True},
    )
    w_energy: float = Field(
        0.05,
        title="Weight: energy",
        ge=0,
        description="Dynamic energy, scaled between its batch minimum and maximum.",
        json_schema_extra={"x-advanced": True},
    )
    w_cost: float = Field(
        0.05,
        title="Weight: cloud cost",
        ge=0,
        description="Cloud cost, scaled between its batch minimum and maximum.",
        json_schema_extra={"x-advanced": True},
    )

    def weights(self) -> Weights:
        return Weights(self.w_deadline, self.w_response, self.w_energy, self.w_cost)


class MetaheuristicParams(SolverParams, WeightParams):
    pass


class MetaheuristicPlacement(Placement):
    """Batch placement that solves each window's assignment with one solver."""

    batch = True
    solver = "ga"

    def __init__(self, params: MetaheuristicParams | None = None) -> None:
        self.p = params or MetaheuristicParams()
        self.settings = SolverSettings(self.p.budget, self.p.pop_size)
        self.last: OptResult | None = None

    def place_batch(self, tasks: list[Task], view: ClusterView) -> dict[int, str | None]:
        result: dict[int, str | None] = {t.id: None for t in tasks}
        problem = problem_from_view(tasks, view, self.p.weights())
        if problem is None:
            return result
        self.last = solve(self.solver, problem, self.rng, self.settings, self.p.seed_heuristics)
        result.update(problem.mapping(self.last.genes))
        return result


_REFS = {
    "ga": "Holland, Adaptation in Natural and Artificial Systems, 1975; Goldberg, 1989",
    "pso": "Kennedy and Eberhart, Particle swarm optimization, Proc. ICNN, 1995",
    "aco": "Stützle and Hoos, MAX-MIN Ant System, Future Generation Computer Systems 16(8), 2000",
    "gwo": "Mirjalili, Mirjalili and Lewis, Grey Wolf Optimizer, Advances in Engineering Software 69, 2014",
    "woa": "Mirjalili and Lewis, The Whale Optimization Algorithm, Advances in Engineering Software 95, 2016",
    "nsga2": "Deb, Pratap, Agarwal and Meyarivan, NSGA-II, IEEE Trans. Evolutionary Computation 6(2), 2002",
    "random_search": "Bergstra and Bengio, Random search for hyper-parameter optimization, JMLR 13, 2012",
}
_SUMMARIES = {
    "ga": "Evolves task-to-node mappings by tournament selection, uniform crossover, mutation and elitism.",
    "pso": "Particles move over random keys toward their own and the swarm's best mapping.",
    "aco": "Ants build mappings from pheromone and a speed heuristic; the best mappings reinforce the trail.",
    "gwo": "Candidate mappings move toward the three best (alpha, beta, delta) as exploration shrinks.",
    "woa": "Candidate mappings encircle the best, search randomly or follow a spiral toward it.",
    "nsga2": "Keeps a Pareto front over misses, response, energy and cost; uses its lowest-fitness member.",
    "random_search": "Samples random mappings with the same budget. A lower bound for the other optimisers.",
}


def _make_solver_plugin(key: str) -> None:
    class SolverPlugin:
        """The optimiser itself, usable on any frozen BatchProblem."""

        def __init__(self, params: SolverParams | None = None) -> None:
            self.p = params or SolverParams()

        def solve(self, problem: BatchProblem, rng: np.random.Generator) -> OptResult:
            return solve(key, problem, rng, SolverSettings(self.p.budget, self.p.pop_size), self.p.seed_heuristics)

    SolverPlugin.__name__ = f"Solver_{key}"
    register(
        kind=PluginKind.OPTIMIZER,
        key=key,
        name=SOLVER_NAMES[key],
        version="1.0.0",
        status=IMPL,
        summary=_SUMMARIES[key],
        description=(
            "Solves the batch task-to-node assignment problem under a fixed evaluation budget. Used by the "
            f"placement:{key} policy and the optimiser benchmark."
        ),
        references=[_REFS[key]],
        params=SolverParams,
        layers=["fog", "cloud"],
        tags=["baseline", "metaheuristic"] + (["multi-objective"] if key == "nsga2" else []),
        phase=4,
    )(SolverPlugin)

    placement_cls = type(f"Placement_{key}", (MetaheuristicPlacement,), {"solver": key})
    register(
        kind=PluginKind.PLACEMENT,
        key=key,
        name=f"{SOLVER_NAMES[key]} (batch)",
        version="1.0.0",
        status=IMPL,
        summary=f"Batch mapper: each window, {SOLVER_NAMES[key]} searches for the best task-to-node assignment.",
        references=[_REFS[key]],
        params=MetaheuristicParams,
        layers=ALL_LAYERS,
        tags=["baseline", "batch", "metaheuristic"],
        phase=4,
    )(placement_cls)


for _key in ("ga", "pso", "aco", "gwo", "woa", "nsga2", "random_search"):
    _make_solver_plugin(_key)
