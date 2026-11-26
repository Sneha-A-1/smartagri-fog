"""Task-graph (DAG) scheduling: HEFT and CPOP (Topcuoglu, Hariri and Wu, 2002), plus a random baseline.

H. Topcuoglu, S. Hariri, M.-Y. Wu. "Performance-effective and low-complexity task scheduling for
heterogeneous computing." IEEE Transactions on Parallel and Distributed Systems 13(3):260-274, 2002.

Model (as in the paper): ``costs[i][p]`` is the execution time of task i on processor p; an edge
(i, j) carries ``data`` that takes ``data / bandwidth[p][q] + latency[p][q]`` to move between distinct
processors and nothing on the same processor. With unit bandwidth and zero latency, ``data`` is the
paper's average communication cost directly.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class Workflow:
    name: str
    costs: tuple[tuple[float, ...], ...]  # costs[task][processor]
    edges: dict[tuple[int, int], float]  # (i, j) -> data volume
    task_names: tuple[str, ...] = ()

    @property
    def n(self) -> int:
        return len(self.costs)

    @property
    def p(self) -> int:
        return len(self.costs[0]) if self.costs else 0

    def succ(self, i: int) -> list[int]:
        return [j for (a, j) in self.edges if a == i]

    def pred(self, j: int) -> list[int]:
        return [i for (i, b) in self.edges if b == j]

    def name_of(self, i: int) -> str:
        return self.task_names[i] if self.task_names else f"n{i + 1}"

    def validate(self) -> None:
        if self.n == 0 or self.p == 0 or any(len(row) != self.p for row in self.costs):
            raise ValueError("costs must be a non-empty task x processor matrix")
        for i, j in self.edges:
            if not (0 <= i < self.n and 0 <= j < self.n) or i == j:
                raise ValueError(f"Bad edge {(i, j)}")
        topological_order(self)  # raises on cycles


@dataclass(frozen=True)
class Platform:
    """Communication between processors. Defaults: unit bandwidth, zero latency (the paper's model)."""

    names: tuple[str, ...]
    bandwidth: tuple[tuple[float, ...], ...] | None = None
    latency: tuple[tuple[float, ...], ...] | None = None

    def comm(self, data: float, p: int, q: int) -> float:
        if p == q:
            return 0.0
        bw = self.bandwidth[p][q] if self.bandwidth else 1.0
        lat = self.latency[p][q] if self.latency else 0.0
        return data / bw + lat

    def mean_comm(self, data: float) -> float:
        k = len(self.names)
        if k < 2:
            return 0.0
        return sum(self.comm(data, p, q) for p in range(k) for q in range(k) if p != q) / (k * (k - 1))


@dataclass
class Slot:
    task: int
    processor: int
    start: float
    finish: float


@dataclass
class Schedule:
    algorithm: str
    slots: dict[int, Slot] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)

    @property
    def makespan(self) -> float:
        return max((s.finish for s in self.slots.values()), default=0.0)


def topological_order(wf: Workflow) -> list[int]:
    indeg = [0] * wf.n
    for _, j in wf.edges:
        indeg[j] += 1
    ready = [i for i in range(wf.n) if indeg[i] == 0]
    out = []
    while ready:
        i = ready.pop(0)
        out.append(i)
        for j in sorted(wf.succ(i)):
            indeg[j] -= 1
            if indeg[j] == 0:
                ready.append(j)
    if len(out) != wf.n:
        raise ValueError("The task graph has a cycle")
    return out


def upward_ranks(wf: Workflow, plat: Platform) -> list[float]:
    """rank_u(i) = mean cost(i) + max over successors j of (mean comm(i, j) + rank_u(j))."""
    rank = [0.0] * wf.n
    for i in reversed(topological_order(wf)):
        w = sum(wf.costs[i]) / wf.p
        rank[i] = w + max((plat.mean_comm(wf.edges[(i, j)]) + rank[j] for j in wf.succ(i)), default=0.0)
    return rank


def downward_ranks(wf: Workflow, plat: Platform) -> list[float]:
    """rank_d(i) = max over predecessors j of (rank_d(j) + mean cost(j) + mean comm(j, i))."""
    rank = [0.0] * wf.n
    for i in topological_order(wf):
        rank[i] = max(
            (rank[j] + sum(wf.costs[j]) / wf.p + plat.mean_comm(wf.edges[(j, i)]) for j in wf.pred(i)), default=0.0
        )
    return rank


def _ready_time(wf: Workflow, plat: Platform, sched: Schedule, i: int, p: int) -> float:
    return max(
        (sched.slots[j].finish + plat.comm(wf.edges[(j, i)], sched.slots[j].processor, p) for j in wf.pred(i)),
        default=0.0,
    )


def _earliest_start(sched: Schedule, p: int, ready: float, duration: float, insertion: bool = True) -> float:
    """Earliest start on processor p at or after ``ready``; with insertion, idle gaps may be used."""
    busy = sorted((s.start, s.finish) for s in sched.slots.values() if s.processor == p)
    if not insertion:
        return max(ready, busy[-1][1] if busy else 0.0)
    t = ready
    for start, finish in busy:
        if t + duration <= start + 1e-12:
            return t
        t = max(t, finish)
    return t


def _assign(sched: Schedule, i: int, p: int, start: float, duration: float) -> None:
    sched.slots[i] = Slot(i, p, start, start + duration)
    sched.order.append(i)


def heft(wf: Workflow, plat: Platform | None = None, insertion: bool = True) -> Schedule:
    plat = plat or Platform(tuple(f"P{k + 1}" for k in range(wf.p)))
    wf.validate()
    rank = upward_ranks(wf, plat)
    order = sorted(range(wf.n), key=lambda i: (-round(rank[i], 9), i))
    sched = Schedule("heft")
    for i in order:
        best = None
        for p in range(wf.p):
            dur = wf.costs[i][p]
            est = _earliest_start(sched, p, _ready_time(wf, plat, sched, i, p), dur, insertion)
            if best is None or est + dur < best[0] - 1e-12:
                best = (est + dur, p, est)
        _assign(sched, i, best[1], best[2], wf.costs[i][best[1]])
    return sched


def cpop(wf: Workflow, plat: Platform | None = None) -> Schedule:
    plat = plat or Platform(tuple(f"P{k + 1}" for k in range(wf.p)))
    wf.validate()
    up, down = upward_ranks(wf, plat), downward_ranks(wf, plat)
    prio = [u + d for u, d in zip(up, down, strict=True)]
    entry = [i for i in range(wf.n) if not wf.pred(i)]
    cp_len = max(prio[i] for i in entry)
    critical, cur = set(), max(entry, key=lambda i: prio[i])
    while cur is not None:
        critical.add(cur)
        nxt = [j for j in wf.succ(cur) if abs(prio[j] - cp_len) < 1e-6]
        cur = nxt[0] if nxt else None
    cp_proc = min(range(wf.p), key=lambda p: sum(wf.costs[i][p] for i in critical))
    sched = Schedule("cpop")
    remaining_preds = {i: len(wf.pred(i)) for i in range(wf.n)}
    ready = set(entry)
    while ready:
        i = max(ready, key=lambda t: (round(prio[t], 9), -t))
        ready.remove(i)
        candidates = [cp_proc] if i in critical else range(wf.p)
        best = None
        for p in candidates:
            dur = wf.costs[i][p]
            est = _earliest_start(sched, p, _ready_time(wf, plat, sched, i, p), dur)
            if best is None or est + dur < best[0] - 1e-12:
                best = (est + dur, p, est)
        _assign(sched, i, best[1], best[2], wf.costs[i][best[1]])
        for j in wf.succ(i):
            remaining_preds[j] -= 1
            if remaining_preds[j] == 0:
                ready.add(j)
    return sched


def random_schedule(wf: Workflow, plat: Platform | None = None, seed: int = 0) -> Schedule:
    """Baseline: tasks in topological order, each on a processor chosen uniformly at random."""
    plat = plat or Platform(tuple(f"P{k + 1}" for k in range(wf.p)))
    rng = random.Random(seed)
    sched = Schedule("random")
    for i in topological_order(wf):
        p = rng.randrange(wf.p)
        dur = wf.costs[i][p]
        _assign(sched, i, p, _earliest_start(sched, p, _ready_time(wf, plat, sched, i, p), dur, False), dur)
    return sched


ALGORITHMS = {"heft": heft, "cpop": cpop}


def schedule_metrics(wf: Workflow, sched: Schedule) -> dict[str, float]:
    """Schedule length, SLR, speedup and efficiency as defined by Topcuoglu et al. (2002)."""
    order = topological_order(wf)
    longest = [0.0] * wf.n  # critical path on minimum computation costs, ignoring communication
    for i in reversed(order):
        longest[i] = min(wf.costs[i]) + max((longest[j] for j in wf.succ(i)), default=0.0)
    cp_min = max(longest)
    sequential = min(sum(wf.costs[i][p] for i in range(wf.n)) for p in range(wf.p))
    m = sched.makespan
    speedup = sequential / m if m > 0 else math.nan
    return {"makespan": m, "slr": m / cp_min, "speedup": speedup, "efficiency": speedup / wf.p}


def check_schedule(wf: Workflow, plat: Platform, sched: Schedule) -> None:
    """Raises if a slot overlaps another on its processor or starts before its inputs arrive."""
    if set(sched.slots) != set(range(wf.n)):
        raise AssertionError("Not every task is scheduled")
    for i, s in sched.slots.items():
        if abs(s.finish - s.start - wf.costs[i][s.processor]) > 1e-9:
            raise AssertionError(f"Task {i} has the wrong duration")
        if s.start + 1e-9 < _ready_time(wf, plat, sched, i, s.processor):
            raise AssertionError(f"Task {i} starts before its inputs arrive")
    for p in range(wf.p):
        busy = sorted((s.start, s.finish) for s in sched.slots.values() if s.processor == p)
        for (_, f1), (s2, _) in zip(busy, busy[1:], strict=False):
            if s2 + 1e-9 < f1:
                raise AssertionError(f"Overlap on processor {p}")


# --- workflows --------------------------------------------------------------------------------------


def topcuoglu_example() -> Workflow:
    """The 10-task, 3-processor example of Topcuoglu et al. (2002), Figure 2."""
    costs = (
        (14, 16, 9), (13, 19, 18), (11, 13, 19), (13, 8, 17), (12, 13, 10),
        (13, 16, 9), (7, 15, 11), (5, 11, 14), (18, 12, 20), (21, 7, 16),
    )  # fmt: skip
    edges = {
        (0, 1): 18, (0, 2): 12, (0, 3): 9, (0, 4): 11, (0, 5): 14, (1, 7): 19, (1, 8): 16, (2, 6): 23,
        (3, 7): 27, (3, 8): 23, (4, 8): 13, (5, 7): 15, (6, 9): 17, (7, 9): 11, (8, 9): 13,
    }  # fmt: skip
    return Workflow(
        "Topcuoglu et al. (2002) example",
        tuple(tuple(float(c) for c in r) for r in costs),
        {k: float(v) for k, v in edges.items()},
    )


def random_workflow(
    v: int,
    processors: int,
    *,
    alpha: float = 1.0,
    out_degree: int = 3,
    ccr: float = 1.0,
    beta: float = 0.5,
    mean_cost: float = 50.0,
    seed: int = 0,
) -> Workflow:
    """Random task graph following the generator of Topcuoglu et al. (2002), Section 5.1.

    ``alpha`` shapes the graph (height ~ sqrt(v)/alpha levels); ``ccr`` is the ratio of mean communication to
    mean computation cost; ``beta`` sets processor heterogeneity (costs spread +-beta/2 around each task's mean).
    """
    rng = random.Random(seed)
    height = max(1, round(math.sqrt(v) / alpha))
    levels: list[list[int]] = [[] for _ in range(height)]
    for i in range(v):
        levels[0 if i == 0 else (rng.randrange(height) if height > 1 else 0)].append(i)
    levels = [lvl for lvl in levels if lvl]
    renum, k = {}, 0
    for lvl in levels:
        for i in lvl:
            renum[i] = k
            k += 1
    levels = [[renum[i] for i in lvl] for lvl in levels]
    edges: dict[tuple[int, int], float] = {}
    mean_comm = ccr * mean_cost
    for li, lvl in enumerate(levels[:-1]):
        later = [j for lv in levels[li + 1 :] for j in lv]
        for i in lvl:
            for j in rng.sample(later, min(out_degree, len(later))):
                edges[(i, j)] = rng.uniform(0, 2 * mean_comm)
    for li, lvl in enumerate(levels[1:], start=1):
        for j in lvl:
            if not any(b == j for (_, b) in edges):
                i = rng.choice(levels[li - 1])
                edges[(i, j)] = rng.uniform(0, 2 * mean_comm)
    costs = []
    for _ in range(v):
        w = rng.uniform(0, 2 * mean_cost)
        costs.append(tuple(rng.uniform(w * (1 - beta / 2), w * (1 + beta / 2)) for _ in range(processors)))
    return Workflow(f"random v={v} ccr={ccr} beta={beta} seed={seed}", tuple(costs), edges)


def schedule_to_dict(wf: Workflow, plat: Platform, sched: Schedule) -> dict[str, Any]:
    return {
        "algorithm": sched.algorithm,
        "metrics": schedule_metrics(wf, sched),
        "slots": [
            {"task": wf.name_of(s.task), "processor": plat.names[s.processor], "start": s.start, "finish": s.finish}
            for s in sorted(sched.slots.values(), key=lambda s: (s.start, s.processor))
        ],
        "order": [wf.name_of(i) for i in sched.order],
    }


Algorithm = Literal["heft", "cpop", "random"]
