"""Batch task placement as an optimisation problem, and the metaheuristics that solve it.

Every batch window, a batch scheduler must assign each waiting task to one node. This module turns one such
decision into a frozen numerical problem (:class:`BatchProblem`) and provides seven solvers that all spend
the same number of objective evaluations, so they can be compared fairly:

* random search (sanity lower bound),
* a Genetic Algorithm (GA), Particle Swarm Optimisation (PSO), Ant Colony Optimisation (ACO),
  the Grey Wolf Optimizer (GWO) and the Whale Optimization Algorithm (WOA), which minimise one weighted
  fitness, and
* NSGA-II, which keeps a Pareto front over four objectives and reports the front member with the lowest
  weighted fitness, so that its answer is comparable with the others.

The objective is the planner's *estimate*, computed with the same fluid queue model that
:meth:`smartagri_core.sim.policies.ClusterView.estimate_finish` uses: a task waits for the work already
committed to its node plus the work of tasks placed earlier in the same batch, divided by the node's total
capacity. It is not the simulated outcome; the simulator measures that separately when an optimiser is used
as a placement policy.

Encoding: gene ``g[i]`` is an index into task i's list of eligible nodes, so every solution is feasible.
Continuous algorithms (PSO, GWO, WOA) search keys in [0, 1) and decode them as ``floor(x * n_candidates)``.

Everything is pure numpy and deterministic for a given ``numpy.random.Generator``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

PRIORITY_WEIGHT: dict[str, float] = {"critical": 4.0, "high": 2.0, "medium": 1.0, "low": 0.5}
OBJECTIVES = ["weighted_miss", "mean_response_s", "energy_j", "cost"]
OBJECTIVE_INFO: dict[str, tuple[str, str]] = {
    "weighted_miss": ("Priority-weighted deadline misses", "share"),
    "mean_response_s": ("Mean estimated response time", "s"),
    "energy_j": ("Dynamic energy", "J"),
    "cost": ("Cloud cost", "$"),
}
_KEY_MAX = 1.0 - 1e-9


@dataclass(frozen=True)
class Weights:
    """Weights of the scalar fitness. Each term is normalised to roughly [0, 1] first."""

    deadline: float = 1.0
    response: float = 0.1
    energy: float = 0.05
    cost: float = 0.05


@dataclass
class BatchProblem:
    """One frozen batch decision. Arrays are indexed [task, candidate]; padding has candidate index -1."""

    task_ids: list[int]
    node_ids: list[str]
    cand: np.ndarray  # (n, K) node indices, -1 = padding
    tx_in_s: np.ndarray  # (n, K)
    tx_out_s: np.ndarray  # (n, K)
    exec_s: np.ndarray  # (n, K)
    energy_j: np.ndarray  # (n, K)
    cost: np.ndarray  # (n, K)
    length_mi: np.ndarray  # (n,)
    slack_s: np.ndarray  # (n,) time left until the absolute deadline
    age_s: np.ndarray  # (n,) time already spent since arrival
    priority_weight: np.ndarray  # (n,)
    backlog_mi: np.ndarray  # (m,) work already committed to each node
    capacity_mips: np.ndarray  # (m,) mips * cores
    weights: Weights = field(default_factory=Weights)

    def __post_init__(self) -> None:
        self.n_cand = (self.cand >= 0).sum(axis=1)
        if self.n_tasks and self.n_cand.min() < 1:
            raise ValueError("Every task in a BatchProblem needs at least one eligible node")
        valid = self.cand >= 0
        big = np.where(valid, 0.0, np.inf)
        # Lower bound on each task's response: its best node with nothing else queued in the batch.
        own = self.tx_in_s + self.exec_s + self.tx_out_s
        cand0 = np.where(valid, self.cand, 0)
        standalone = own + self.backlog_mi[cand0] / self.capacity_mips[cand0]
        self.standalone_s = np.where(valid, standalone, np.inf)
        self._resp_ref = float(np.mean(self.age_s + (self.standalone_s + big).min(axis=1))) if self.n_tasks else 1.0
        self._e_min = float((self.energy_j + big).min(axis=1).sum())
        self._e_max = float(np.where(valid, self.energy_j, -np.inf).max(axis=1).sum())
        self._c_min = float((self.cost + big).min(axis=1).sum())
        self._c_max = float(np.where(valid, self.cost, -np.inf).max(axis=1).sum())
        self._wsum = float(self.priority_weight.sum()) or 1.0

    @property
    def n_tasks(self) -> int:
        return len(self.task_ids)

    # --- encoding ---------------------------------------------------------------------------------------

    def random_genes(self, rng: np.random.Generator, count: int) -> np.ndarray:
        return np.floor(rng.random((count, self.n_tasks)) * self.n_cand).astype(np.int64)

    def keys_to_genes(self, keys: np.ndarray) -> np.ndarray:
        return np.minimum(np.floor(keys * self.n_cand).astype(np.int64), self.n_cand - 1)

    def genes_to_keys(self, genes: np.ndarray) -> np.ndarray:
        return (genes + 0.5) / self.n_cand

    def nodes_of(self, genes: np.ndarray) -> np.ndarray:
        return self.cand[np.arange(self.n_tasks), genes]

    def mapping(self, genes: np.ndarray) -> dict[int, str]:
        nodes = self.nodes_of(np.asarray(genes))
        return {tid: self.node_ids[int(j)] for tid, j in zip(self.task_ids, nodes, strict=True)}

    # --- evaluation -------------------------------------------------------------------------------------

    def finish_times(self, genes: np.ndarray) -> np.ndarray:
        """Estimated time from now until each task's result is delivered, shape (P, n)."""
        genes = np.atleast_2d(genes)
        p, n = genes.shape
        rows = np.arange(n)
        nodes = self.cand[rows, genes]  # (P, n)
        m = len(self.node_ids)
        onehot = np.zeros((p, n, m))
        onehot[np.arange(p)[:, None], rows[None, :], nodes] = self.length_mi[None, :]
        before = np.cumsum(onehot, axis=1)[np.arange(p)[:, None], rows[None, :], nodes] - self.length_mi[None, :]
        wait = (self.backlog_mi[nodes] + before) / self.capacity_mips[nodes]
        return self.tx_in_s[rows, genes] + wait + self.exec_s[rows, genes] + self.tx_out_s[rows, genes]

    def objectives(self, genes: np.ndarray) -> np.ndarray:
        """The four objectives (all minimised), shape (P, 4), in the order of :data:`OBJECTIVES`."""
        genes = np.atleast_2d(genes)
        rows = np.arange(self.n_tasks)
        finish = self.finish_times(genes)
        miss = (finish > self.slack_s[None, :]).astype(float)
        out = np.empty((genes.shape[0], 4))
        out[:, 0] = (miss * self.priority_weight[None, :]).sum(axis=1) / self._wsum
        out[:, 1] = (finish + self.age_s[None, :]).mean(axis=1)
        out[:, 2] = self.energy_j[rows, genes].sum(axis=1)
        out[:, 3] = self.cost[rows, genes].sum(axis=1)
        return out

    def scalarize(self, obj: np.ndarray) -> np.ndarray:
        w = self.weights
        resp = obj[:, 1] / self._resp_ref - 1.0 if self._resp_ref > 0 else obj[:, 1]
        e = (obj[:, 2] - self._e_min) / (self._e_max - self._e_min) if self._e_max > self._e_min else 0.0 * obj[:, 2]
        c = (obj[:, 3] - self._c_min) / (self._c_max - self._c_min) if self._c_max > self._c_min else 0.0 * obj[:, 3]
        return w.deadline * obj[:, 0] + w.response * resp + w.energy * e + w.cost * c

    def fitness(self, genes: np.ndarray) -> np.ndarray:
        return self.scalarize(self.objectives(genes))

    def unavoidable_miss(self) -> float:
        """Priority-weighted share of tasks that would miss their deadline even alone on their best node."""
        late = self.standalone_s.min(axis=1) > self.slack_s
        return float((late * self.priority_weight).sum() / self._wsum)

    # --- constructive heuristics (also used as seeds) ---------------------------------------------------

    def greedy_mct(self) -> np.ndarray:
        """Minimum completion time in batch order, accounting for tasks already placed in this batch."""
        extra = np.zeros(len(self.node_ids))
        genes = np.zeros(self.n_tasks, dtype=np.int64)
        for i in range(self.n_tasks):
            k = int(self.n_cand[i])
            nodes = self.cand[i, :k]
            est = self.standalone_s[i, :k] + extra[nodes] / self.capacity_mips[nodes]
            genes[i] = int(np.argmin(est))
            extra[nodes[genes[i]]] += self.length_mi[i]
        return genes

    def min_min(self, pick_max: bool = False) -> np.ndarray:
        """Min-Min (or Max-Min): repeatedly fix the task whose best estimated completion is smallest (largest)."""
        extra = np.zeros(len(self.node_ids))
        genes = np.zeros(self.n_tasks, dtype=np.int64)
        left = list(range(self.n_tasks))
        while left:
            best: list[tuple[float, int, int]] = []
            for i in left:
                k = int(self.n_cand[i])
                nodes = self.cand[i, :k]
                est = self.standalone_s[i, :k] + extra[nodes] / self.capacity_mips[nodes]
                g = int(np.argmin(est))
                best.append((float(est[g]), i, g))
            _, i, g = max(best) if pick_max else min(best)
            genes[i] = g
            extra[self.cand[i, g]] += self.length_mi[i]
            left.remove(i)
        return genes


# --- budget accounting ----------------------------------------------------------------------------------


class _Tracker:
    """Counts evaluations against the budget and records the best-so-far curve."""

    def __init__(self, problem: BatchProblem, budget: int) -> None:
        self.problem, self.budget, self.used = problem, budget, 0
        self.best_fit, self.best_genes, self.best_obj = np.inf, None, None
        self.history: list[tuple[int, float]] = []

    @property
    def exhausted(self) -> bool:
        return self.used >= self.budget

    def __call__(self, genes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Evaluate as many rows as the budget allows; rows beyond it get infinite fitness."""
        genes = np.atleast_2d(genes)
        take = max(0, min(len(genes), self.budget - self.used))
        fit = np.full(len(genes), np.inf)
        obj = np.full((len(genes), 4), np.inf)
        if take:
            obj[:take] = self.problem.objectives(genes[:take])
            fit[:take] = self.problem.scalarize(obj[:take])
            self.used += take
            i = int(np.argmin(fit[:take]))
            if fit[i] < self.best_fit:
                self.best_fit, self.best_genes, self.best_obj = float(fit[i]), genes[i].copy(), obj[i].copy()
            self.history.append((self.used, self.best_fit))
        return fit, obj


@dataclass
class OptResult:
    algorithm: str
    genes: np.ndarray
    fitness: float
    objectives: np.ndarray
    evaluations: int
    history: list[tuple[int, float]]
    front: np.ndarray | None = None  # NSGA-II only: objectives of the final non-dominated set
    front_genes: np.ndarray | None = None


def _result(name: str, tr: _Tracker, front: np.ndarray | None = None, front_genes: np.ndarray | None = None):
    return OptResult(name, tr.best_genes, tr.best_fit, tr.best_obj, tr.used, tr.history, front, front_genes)


def _initial(problem: BatchProblem, rng: np.random.Generator, size: int, seeds: Sequence[np.ndarray]) -> np.ndarray:
    pop = problem.random_genes(rng, size)
    for i, s in enumerate(seeds[:size]):
        pop[i] = s
    return pop


# --- the solvers ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SolverSettings:
    budget: int = 1000
    pop_size: int = 20


def random_search(problem: BatchProblem, rng: np.random.Generator, s: SolverSettings, seeds=()) -> OptResult:
    tr = _Tracker(problem, s.budget)
    if len(seeds):
        tr(np.array(seeds))
    while not tr.exhausted:
        tr(problem.random_genes(rng, s.pop_size))
    return _result("random_search", tr)


def _tournament(rng: np.random.Generator, better: Callable[[np.ndarray, np.ndarray], np.ndarray], n: int, size: int):
    a = rng.integers(n, size=size)
    b = rng.integers(n, size=size)
    return np.where(better(a, b), a, b)


def _vary(problem: BatchProblem, rng: np.random.Generator, pa: np.ndarray, pb: np.ndarray, pc: float, pm: float):
    """Uniform crossover with probability pc, then per-gene random reassignment with probability pm."""
    cross = rng.random(len(pa)) < pc
    mask = (rng.random(pa.shape) < 0.5) & cross[:, None]
    child = np.where(mask, pb, pa)
    mut = rng.random(child.shape) < pm
    return np.where(mut, problem.random_genes(rng, len(child)), child)


def genetic_algorithm(problem: BatchProblem, rng: np.random.Generator, s: SolverSettings, seeds=()) -> OptResult:
    """Generational GA: binary tournament, uniform crossover (0.9), mutation 1/n per gene, two elites."""
    tr = _Tracker(problem, s.budget)
    pop = _initial(problem, rng, s.pop_size, seeds)
    fit, _ = tr(pop)
    n_elite = min(2, s.pop_size)
    pm = 1.0 / max(problem.n_tasks, 1)
    while not tr.exhausted:
        order = np.argsort(fit, kind="stable")
        elite = pop[order[:n_elite]]
        k = s.pop_size - n_elite

        def better(a, b, fit=fit):
            return fit[a] <= fit[b]

        pa = _tournament(rng, better, len(pop), k)
        pb = _tournament(rng, better, len(pop), k)
        children = _vary(problem, rng, pop[pa], pop[pb], 0.9, pm)
        cfit, _ = tr(children)
        pop = np.vstack([elite, children])
        fit = np.concatenate([fit[order[:n_elite]], cfit])
    return _result("ga", tr)


def particle_swarm(problem: BatchProblem, rng: np.random.Generator, s: SolverSettings, seeds=()) -> OptResult:
    """Global-best PSO on random keys: inertia falls from 0.9 to 0.4 (Shi and Eberhart), c1 = c2 = 2,
    velocity limited to 0.5, particles that leave [0, 1) are put back on the edge with damped velocity."""
    tr = _Tracker(problem, s.budget)
    x = rng.random((s.pop_size, problem.n_tasks))
    for i, sd in enumerate(seeds[: s.pop_size]):
        x[i] = problem.genes_to_keys(sd)
    v = rng.uniform(-0.1, 0.1, x.shape)
    fit, _ = tr(problem.keys_to_genes(x))
    pbest, pfit = x.copy(), fit.copy()
    while not tr.exhausted:
        w = 0.9 - 0.5 * tr.used / tr.budget
        g = pbest[int(np.argmin(pfit))]
        r1, r2 = rng.random(x.shape), rng.random(x.shape)
        v = np.clip(w * v + 2.0 * r1 * (pbest - x) + 2.0 * r2 * (g - x), -0.5, 0.5)
        x = x + v
        out = (x < 0.0) | (x > _KEY_MAX)
        v[out] *= -0.5
        x = np.clip(x, 0.0, _KEY_MAX)
        fit, _ = tr(problem.keys_to_genes(x))
        better = fit < pfit
        pbest[better], pfit[better] = x[better], fit[better]
    return _result("pso", tr)


def ant_colony(problem: BatchProblem, rng: np.random.Generator, s: SolverSettings, seeds=()) -> OptResult:
    """MAX-MIN Ant System: pheromone per (task, node), heuristic 1/standalone time, alpha 1, beta 2, rho 0.1."""
    tr = _Tracker(problem, s.budget)
    n, kmax = problem.cand.shape
    valid = problem.cand >= 0
    eta = np.where(valid, 1.0 / (problem.standalone_s + 1e-9), 0.0)
    eta = eta / eta.max(axis=1, keepdims=True)
    tau = np.where(valid, 1.0, 0.0)
    tau_min, tau_max, rho = 0.05, 1.0, 0.1
    rows = np.arange(n)
    if len(seeds):
        tr(np.array(seeds))
    while not tr.exhausted:
        weight = tau * eta**2
        cdf = np.cumsum(weight / weight.sum(axis=1, keepdims=True), axis=1)
        u = rng.random((s.pop_size, n, 1))
        ants = np.minimum((u > cdf[None, :, :]).sum(axis=2), problem.n_cand - 1)
        fit, _ = tr(ants)
        tau = (1.0 - rho) * tau
        it_best = ants[int(np.argmin(fit))]
        tau[rows, it_best] += rho * tau_max
        if tr.best_genes is not None:
            tau[rows, tr.best_genes] += rho * tau_max
        tau = np.where(valid, np.clip(tau, tau_min, tau_max), 0.0)
    return _result("aco", tr)


def grey_wolf(problem: BatchProblem, rng: np.random.Generator, s: SolverSettings, seeds=()) -> OptResult:
    """Grey Wolf Optimizer on random keys; a falls linearly from 2 to 0 over the evaluation budget."""
    tr = _Tracker(problem, s.budget)
    x = rng.random((s.pop_size, problem.n_tasks))
    for i, sd in enumerate(seeds[: s.pop_size]):
        x[i] = problem.genes_to_keys(sd)
    fit, _ = tr(problem.keys_to_genes(x))
    lead_x, lead_f = x.copy(), fit.copy()
    while not tr.exhausted:
        order = np.argsort(lead_f, kind="stable")[:3]
        leaders = lead_x[order]
        a = 2.0 * (1.0 - tr.used / tr.budget)
        new = np.zeros_like(x)
        for lx in leaders:
            big_a = a * (2.0 * rng.random(x.shape) - 1.0)
            c = 2.0 * rng.random(x.shape)
            new += lx - big_a * np.abs(c * lx - x)
        x = np.clip(new / len(leaders), 0.0, _KEY_MAX)
        fit, _ = tr(problem.keys_to_genes(x))
        pool_x, pool_f = np.vstack([leaders, x]), np.concatenate([lead_f[order], fit])
        keep = np.argsort(pool_f, kind="stable")[:3]
        lead_x, lead_f = pool_x[keep], pool_f[keep]
    return _result("gwo", tr)


def whale(problem: BatchProblem, rng: np.random.Generator, s: SolverSettings, seeds=()) -> OptResult:
    """Whale Optimization Algorithm on random keys: encircling, random search and spiral moves (b = 1)."""
    tr = _Tracker(problem, s.budget)
    x = rng.random((s.pop_size, problem.n_tasks))
    for i, sd in enumerate(seeds[: s.pop_size]):
        x[i] = problem.genes_to_keys(sd)
    fit, _ = tr(problem.keys_to_genes(x))
    best_x, best_f = x[int(np.argmin(fit))].copy(), float(fit.min())
    while not tr.exhausted:
        a = 2.0 * (1.0 - tr.used / tr.budget)
        new = np.empty_like(x)
        for i in range(len(x)):
            big_a = a * (2.0 * rng.random() - 1.0)
            c = 2.0 * rng.random(x.shape[1])
            if rng.random() < 0.5:
                ref = best_x if abs(big_a) < 1.0 else x[int(rng.integers(len(x)))]
                new[i] = ref - big_a * np.abs(c * ref - x[i])
            else:
                ell = rng.uniform(-1.0, 1.0)
                new[i] = np.abs(best_x - x[i]) * np.exp(ell) * np.cos(2.0 * np.pi * ell) + best_x
        x = np.clip(new, 0.0, _KEY_MAX)
        fit, _ = tr(problem.keys_to_genes(x))
        i = int(np.argmin(fit))
        if fit[i] < best_f:
            best_x, best_f = x[i].copy(), float(fit[i])
    return _result("woa", tr)


def non_dominated_sort(obj: np.ndarray) -> np.ndarray:
    """Pareto rank of each row (0 = first front), all objectives minimised."""
    le = (obj[:, None, :] <= obj[None, :, :]).all(axis=2)
    lt = (obj[:, None, :] < obj[None, :, :]).any(axis=2)
    dominates = le & lt  # dominates[i, j]: i dominates j
    count = dominates.sum(axis=0)
    rank = np.full(len(obj), -1)
    level = 0
    current = np.flatnonzero(count == 0)
    while current.size:
        rank[current] = level
        count = count - dominates[current].sum(axis=0)
        count[rank >= 0] = -1
        current = np.flatnonzero(count == 0)
        level += 1
    return rank


def crowding_distance(obj: np.ndarray) -> np.ndarray:
    n = len(obj)
    dist = np.zeros(n)
    if n <= 2:
        return np.full(n, np.inf)
    for k in range(obj.shape[1]):
        order = np.argsort(obj[:, k], kind="stable")
        span = obj[order[-1], k] - obj[order[0], k]
        dist[order[0]] = dist[order[-1]] = np.inf
        if span > 0:
            dist[order[1:-1]] += (obj[order[2:], k] - obj[order[:-2], k]) / span
    return dist


def nsga2(problem: BatchProblem, rng: np.random.Generator, s: SolverSettings, seeds=()) -> OptResult:
    """NSGA-II (Deb et al., 2002) over the four objectives, with the GA's variation operators.

    The reported front is an external archive of every non-dominated mapping evaluated (at most
    max(50, 2 x population), thinned by crowding distance)."""
    tr = _Tracker(problem, s.budget)
    pop = _initial(problem, rng, s.pop_size, seeds)
    _, obj = tr(pop)
    pm = 1.0 / max(problem.n_tasks, 1)

    def rank_crowd(o: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        r = non_dominated_sort(o)
        cd = np.zeros(len(o))
        for lv in np.unique(r):
            idx = np.flatnonzero(r == lv)
            cd[idx] = crowding_distance(o[idx])
        return r, cd

    # External archive: every non-dominated mapping evaluated so far (bounded by crowding), so that a good
    # solution dropped from the population by truncation still appears in the reported front.
    arch_g, arch_o = pop.copy(), obj.copy()

    def update_archive(g: np.ndarray, o: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        allg, allo = np.vstack([arch_g, g]), np.vstack([arch_o, o])
        _, uniq = np.unique(allo, axis=0, return_index=True)
        allg, allo = allg[np.sort(uniq)], allo[np.sort(uniq)]
        keep = non_dominated_sort(allo) == 0
        allg, allo = allg[keep], allo[keep]
        if len(allo) > archive_size:
            order = np.argsort(-crowding_distance(allo), kind="stable")[:archive_size]
            allg, allo = allg[np.sort(order)], allo[np.sort(order)]
        return allg, allo

    archive_size = max(50, 2 * s.pop_size)
    arch_g, arch_o = update_archive(pop[:0], obj[:0])
    rank, crowd = rank_crowd(obj)
    while not tr.exhausted:

        def better(a, b, rank=rank, crowd=crowd):
            return (rank[a] < rank[b]) | ((rank[a] == rank[b]) & (crowd[a] >= crowd[b]))

        pa = _tournament(rng, better, len(pop), s.pop_size)
        pb = _tournament(rng, better, len(pop), s.pop_size)
        children = _vary(problem, rng, pop[pa], pop[pb], 0.9, pm)
        _, cobj = tr(children)
        ok = np.isfinite(cobj[:, 0])
        arch_g, arch_o = update_archive(children[ok], cobj[ok])
        allp, allo = np.vstack([pop, children[ok]]), np.vstack([obj, cobj[ok]])
        r, cd = rank_crowd(allo)
        order = np.lexsort((-cd, r))[: s.pop_size]
        pop, obj = allp[order], allo[order]
        rank, crowd = rank_crowd(obj)
    return _result("nsga2", tr, arch_o, arch_g)


Solver = Callable[..., OptResult]
SOLVERS: dict[str, Solver] = {
    "random_search": random_search,
    "ga": genetic_algorithm,
    "pso": particle_swarm,
    "aco": ant_colony,
    "gwo": grey_wolf,
    "woa": whale,
    "nsga2": nsga2,
}
SolverKey = Literal["random_search", "ga", "pso", "aco", "gwo", "woa", "nsga2"]
SOLVER_NAMES: dict[str, str] = {
    "random_search": "Random search",
    "ga": "Genetic Algorithm",
    "pso": "Particle Swarm Optimisation",
    "aco": "Ant Colony Optimisation",
    "gwo": "Grey Wolf Optimizer",
    "woa": "Whale Optimization Algorithm",
    "nsga2": "NSGA-II",
    "min_min": "Min-Min",
    "max_min": "Max-Min",
    "greedy_mct": "Greedy MCT",
}


def solve(
    key: str,
    problem: BatchProblem,
    rng: np.random.Generator,
    settings: SolverSettings,
    seed_heuristics: bool = True,
) -> OptResult:
    """Run one solver. With ``seed_heuristics`` the initial population contains Min-Min and greedy MCT."""
    seeds = [problem.min_min(), problem.greedy_mct()] if seed_heuristics else []
    return SOLVERS[key](problem, rng, settings, seeds)


def brute_force(problem: BatchProblem) -> tuple[np.ndarray, float]:
    """Exact optimum by enumeration, for tests on tiny problems only."""
    grids = np.meshgrid(*[np.arange(k) for k in problem.n_cand], indexing="ij")
    allg = np.stack([g.ravel() for g in grids], axis=1)
    fit = problem.fitness(allg)
    i = int(np.argmin(fit))
    return allg[i], float(fit[i])
