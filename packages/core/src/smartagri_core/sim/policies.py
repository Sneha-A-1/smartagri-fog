"""Scheduling policies, split into the two decisions every fog scheduler makes:

* **Placement**: which node runs a task (online, per arrival; or batch, per window).
* **Queue discipline**: in which order a node runs the tasks waiting for it.

Any placement can be combined with any discipline, so baselines are compared on equal terms. Policies
see the system only through :class:`ClusterView`, never the simulator internals.
"""

from __future__ import annotations

import bisect
from typing import TYPE_CHECKING, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from smartagri_core.registry import EmptyParams, PluginKind, register
from smartagri_core.sim.topology import Layer, NodeSpec
from smartagri_core.sim.workload import PRIORITY_RANK, Task
from smartagri_core.status import CapabilityStatus

if TYPE_CHECKING:
    from smartagri_core.sim.engine import Simulator

IMPL = CapabilityStatus.IMPLEMENTED
ALL_LAYERS = ["edge", "fog", "cloud"]


class ClusterView:
    """Read-only view of the system offered to policies."""

    def __init__(self, sim: Simulator) -> None:
        self._sim = sim

    @property
    def now(self) -> float:
        return self._sim.now

    @property
    def nodes(self) -> list[NodeSpec]:
        return [ns.spec for ns in self._sim.nodes.values() if ns.spec.can_compute]

    def is_up(self, node_id: str) -> bool:
        return self._sim.nodes[node_id].up

    def eligible(self, task: Task) -> list[NodeSpec]:
        """Nodes that are up, can compute, have enough RAM and are reachable from the task's source."""
        router = self._sim.router
        return [
            ns.spec
            for ns in self._sim.nodes.values()
            if ns.up
            and ns.spec.can_compute
            and ns.spec.ram_mb >= task.ram_mb
            and router.reachable(task.source, ns.spec.id)
        ]

    def signals_until_now(self) -> list:
        """Early warnings issued so far (never future ones). Ground truth is in the objects but must not be used."""
        sig = self._sim.trace.signals
        if not sig:
            return []
        if getattr(self, "_signal_times", None) is None:
            self._signal_times = [x.time_s for x in sig]
        return list(sig[: bisect.bisect_right(self._signal_times, self.now)])

    def training_context(self):
        """(topology, workload spec or None, settings) of the running simulation, for policies that learn."""
        return self._sim.topology, self._sim.trace.spec, self._sim.settings

    def backlog_s(self, node_id: str) -> float:
        """Committed work (queued, running and in transit) divided by the node's total capacity."""
        ns = self._sim.nodes[node_id]
        return max(ns.committed_mi, 0.0) / (ns.spec.mips * ns.spec.cores)

    def free_cores(self, node_id: str) -> int:
        ns = self._sim.nodes[node_id]
        return ns.spec.cores - ns.busy if ns.up else 0

    def transfer_time(self, src: str, dst: str, size_bytes: float) -> float:
        return self._sim.router.transfer_time(src, dst, size_bytes)

    def path_latency(self, src: str, dst: str) -> float:
        route = self._sim.router.route(src, dst)
        return float("inf") if route is None else route.latency_s

    def path_nodes(self, src: str, dst: str) -> list[str]:
        """Node ids along the minimum-latency route, from src to dst inclusive."""
        route = self._sim.router.route(src, dst)
        if route is None:
            return []
        out, cur = [src], src
        for hop in route.hops:
            cur = hop.b if hop.a == cur else hop.a
            out.append(cur)
        return out

    def estimate_finish(self, task: Task, node_id: str, extra_backlog_mi: float = 0.0) -> float:
        """Estimated delivery time: upload + backlog wait (fluid approximation) + execution + return."""
        spec = self._sim.topology.node[node_id]
        wait = (max(self._sim.nodes[node_id].committed_mi, 0.0) + extra_backlog_mi) / (spec.mips * spec.cores)
        tx_in = self.transfer_time(task.source, node_id, task.input_bytes)
        tx_out = self.transfer_time(node_id, task.source, task.output_bytes) if task.result_to_source else 0.0
        return self.now + tx_in + wait + task.length_mi / spec.mips + tx_out


# --- queue disciplines ------------------------------------------------------------------------------


class Discipline:
    def key(self, task: Task, enqueued_s: float) -> tuple:
        raise NotImplementedError


@register(
    kind=PluginKind.QUEUE_DISCIPLINE,
    key="fcfs",
    name="First-Come, First-Served",
    version="1.0.0",
    status=IMPL,
    summary="Each node runs waiting tasks in the order they arrived at the node.",
    layers=ALL_LAYERS,
    tags=["baseline"],
)
class FCFS(Discipline):
    def __init__(self, params: EmptyParams | None = None) -> None:
        pass

    def key(self, task: Task, enqueued_s: float) -> tuple:
        return (enqueued_s,)


@register(
    kind=PluginKind.QUEUE_DISCIPLINE,
    key="edf",
    name="Earliest Deadline First",
    version="1.0.0",
    status=IMPL,
    summary="Each node runs the waiting task with the nearest absolute deadline first.",
    layers=ALL_LAYERS,
    tags=["baseline"],
)
class EDF(Discipline):
    def __init__(self, params: EmptyParams | None = None) -> None:
        pass

    def key(self, task: Task, enqueued_s: float) -> tuple:
        return (task.abs_deadline, enqueued_s)


@register(
    kind=PluginKind.QUEUE_DISCIPLINE,
    key="priority",
    name="Priority scheduling",
    version="1.0.0",
    status=IMPL,
    summary="Critical tasks first, then high, medium and low; arrival order within a class.",
    layers=ALL_LAYERS,
    tags=["baseline"],
)
class PriorityDiscipline(Discipline):
    def __init__(self, params: EmptyParams | None = None) -> None:
        pass

    def key(self, task: Task, enqueued_s: float) -> tuple:
        return (PRIORITY_RANK[task.priority], enqueued_s)


@register(
    kind=PluginKind.QUEUE_DISCIPLINE,
    key="sjf",
    name="Shortest Job First",
    version="1.0.0",
    status=IMPL,
    summary="Each node runs the waiting task with the smallest processing length first.",
    layers=ALL_LAYERS,
    tags=["baseline"],
)
class SJF(Discipline):
    def __init__(self, params: EmptyParams | None = None) -> None:
        pass

    def key(self, task: Task, enqueued_s: float) -> tuple:
        return (task.length_mi, enqueued_s)


# --- placement policies -----------------------------------------------------------------------------


class Placement:
    batch: bool = False

    def reset(self, view: ClusterView, rng: np.random.Generator) -> None:
        self.rng = rng

    def place(self, task: Task, view: ClusterView) -> str | None:
        raise NotImplementedError

    def place_batch(self, tasks: list[Task], view: ClusterView) -> dict[int, str | None]:
        return {t.id: self.place(t, view) for t in tasks}


@register(
    kind=PluginKind.PLACEMENT,
    key="random",
    name="Random placement",
    version="1.0.0",
    status=IMPL,
    summary="Sends each task to a uniformly random eligible node. A sanity-check lower bound.",
    layers=ALL_LAYERS,
    tags=["baseline"],
)
class RandomPlacement(Placement):
    def __init__(self, params: EmptyParams | None = None) -> None:
        pass

    def place(self, task: Task, view: ClusterView) -> str | None:
        nodes = view.eligible(task)
        return nodes[int(self.rng.integers(len(nodes)))].id if nodes else None


@register(
    kind=PluginKind.PLACEMENT,
    key="round_robin",
    name="Round Robin",
    version="1.0.0",
    status=IMPL,
    summary="Assigns successive tasks to eligible nodes in cyclic order.",
    layers=ALL_LAYERS,
    tags=["baseline"],
)
class RoundRobin(Placement):
    def __init__(self, params: EmptyParams | None = None) -> None:
        self._i = 0

    def place(self, task: Task, view: ClusterView) -> str | None:
        nodes = view.eligible(task)
        if not nodes:
            return None
        node = nodes[self._i % len(nodes)]
        self._i += 1
        return node.id


@register(
    kind=PluginKind.PLACEMENT,
    key="least_loaded",
    name="Least Loaded",
    version="1.0.0",
    status=IMPL,
    summary="Places each task on the eligible node with the smallest backlog relative to its capacity.",
    layers=ALL_LAYERS,
    tags=["baseline"],
)
class LeastLoaded(Placement):
    def __init__(self, params: EmptyParams | None = None) -> None:
        pass

    def place(self, task: Task, view: ClusterView) -> str | None:
        nodes = view.eligible(task)
        return min(nodes, key=lambda n: (view.backlog_s(n.id), n.id)).id if nodes else None


@register(
    kind=PluginKind.PLACEMENT,
    key="mct",
    name="Minimum Completion Time",
    version="1.0.0",
    status=IMPL,
    summary="Places each task where its estimated delivery time (transfer, wait, run, return) is earliest.",
    layers=ALL_LAYERS,
    tags=["baseline"],
)
class MinimumCompletionTime(Placement):
    def __init__(self, params: EmptyParams | None = None) -> None:
        pass

    def place(self, task: Task, view: ClusterView) -> str | None:
        nodes = view.eligible(task)
        return min(nodes, key=lambda n: (view.estimate_finish(task, n.id), n.id)).id if nodes else None


@register(
    kind=PluginKind.PLACEMENT,
    key="cloud_only",
    name="Cloud-only",
    version="1.0.0",
    status=IMPL,
    summary="iFogSim baseline: every task runs in the cloud (the least-loaded cloud node).",
    references=["Gupta et al., iFogSim, Software: Practice and Experience, 2017 (arXiv:1606.02007)"],
    layers=["cloud"],
    tags=["baseline", "ifogsim"],
)
class CloudOnly(Placement):
    def __init__(self, params: EmptyParams | None = None) -> None:
        pass

    def place(self, task: Task, view: ClusterView) -> str | None:
        clouds = [n for n in view.eligible(task) if n.layer == Layer.CLOUD]
        return min(clouds, key=lambda n: (view.backlog_s(n.id), n.id)).id if clouds else None


class EdgeWardParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_backlog_s: float = Field(
        1.0,
        ge=0,
        description="Move one level up when a node's backlog exceeds this.",
        json_schema_extra={"x-unit": "s"},
    )


@register(
    kind=PluginKind.PLACEMENT,
    key="edge_ward",
    name="Edge-ward",
    version="1.0.0",
    status=IMPL,
    summary="iFogSim baseline adapted per task: the first node on the path to the cloud with spare capacity.",
    description=(
        "iFogSim's edge-ward strategy places application modules on the lowest device that can host "
        "them, moving toward the cloud otherwise. Here the same rule is applied to each task, using "
        "backlog in seconds as the capacity test."
    ),
    references=["Gupta et al., iFogSim, Software: Practice and Experience, 2017 (arXiv:1606.02007)"],
    params=EdgeWardParams,
    layers=ALL_LAYERS,
    tags=["baseline", "ifogsim"],
)
class EdgeWard(Placement):
    def __init__(self, params: EdgeWardParams) -> None:
        self.p = params

    def place(self, task: Task, view: ClusterView) -> str | None:
        eligible = {n.id: n for n in view.eligible(task)}
        if not eligible:
            return None
        clouds = [n for n in eligible.values() if n.layer == Layer.CLOUD]
        target = min(clouds, key=lambda n: view.path_latency(task.source, n.id)) if clouds else None
        path = view.path_nodes(task.source, target.id) if target else []
        for nid in path:
            if nid in eligible and view.backlog_s(nid) <= self.p.max_backlog_s:
                return nid
        if target:
            return target.id
        return min(eligible.values(), key=lambda n: (view.backlog_s(n.id), n.id)).id


class BatchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _MinMaxBase(Placement):
    batch = True
    pick_max = False

    def __init__(self, params: BatchParams | None = None) -> None:
        pass

    def place_batch(self, tasks: list[Task], view: ClusterView) -> dict[int, str | None]:
        extra: dict[str, float] = {}
        result: dict[int, str | None] = {}
        remaining = {t.id: t for t in tasks}
        candidates = {t.id: [n.id for n in view.eligible(t)] for t in tasks}
        for tid, nodes in candidates.items():
            if not nodes:
                result[tid] = None
                remaining.pop(tid)
        while remaining:
            best: dict[int, tuple[float, str]] = {}
            for tid, task in remaining.items():
                best[tid] = min((view.estimate_finish(task, nid, extra.get(nid, 0.0)), nid) for nid in candidates[tid])
            chooser = max if self.pick_max else min
            tid = chooser(best, key=lambda k: (best[k][0], k))
            nid = best[tid][1]
            result[tid] = nid
            extra[nid] = extra.get(nid, 0.0) + remaining.pop(tid).length_mi
        return result


@register(
    kind=PluginKind.PLACEMENT,
    key="min_min",
    name="Min-Min",
    version="1.0.0",
    status=IMPL,
    summary="Batch mapper: each window, repeatedly assigns the task whose best completion time is smallest.",
    layers=ALL_LAYERS,
    tags=["baseline", "batch"],
)
class MinMin(_MinMaxBase):
    pass


@register(
    kind=PluginKind.PLACEMENT,
    key="max_min",
    name="Max-Min",
    version="1.0.0",
    status=IMPL,
    summary="Batch mapper: each window, repeatedly assigns the task whose best completion time is largest.",
    layers=ALL_LAYERS,
    tags=["baseline", "batch"],
)
class MaxMin(_MinMaxBase):
    pick_max = True


PLACEMENT_KEYS = Literal[
    "random",
    "round_robin",
    "least_loaded",
    "mct",
    "cloud_only",
    "edge_ward",
    "min_min",
    "max_min",
    "ga",
    "pso",
    "aco",
    "gwo",
    "woa",
    "nsga2",
    "random_search",
    "dqn",
]
DISCIPLINE_KEYS = Literal["fcfs", "edf", "priority", "sjf"]
