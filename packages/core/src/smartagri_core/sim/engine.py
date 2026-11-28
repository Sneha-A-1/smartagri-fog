"""Discrete-event simulation engine.

Event-driven with a single priority queue ordered by (time, sequence number), so runs are deterministic.
Model summary (details and limitations in docs/simulation-model.md):

* Tasks arrive at IoT gateways (from a frozen trace) and are dispatched by a placement policy, either
  immediately (online) or in batch windows.
* Input data travels source -> node; the result travels node -> source when the task drives an actuator.
* Each node has ``cores`` identical cores (space-shared): a task occupies one core for length/MIPS seconds.
  Waiting tasks are ordered by the node's queue discipline (FCFS, EDF, priority, SJF).
* Energy per node integrates P(u) = P_idle + (P_max - P_idle) * busy/cores over time while the node is up.
* Optional node failures: exponential times to failure and repair; tasks on a failed node are retried or fail.
"""

from __future__ import annotations

import heapq
import itertools
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from smartagri_core.progress import ProgressReporter, null_progress
from smartagri_core.sim.policies import ClusterView, Discipline, Placement
from smartagri_core.sim.topology import Router, Topology
from smartagri_core.sim.workload import Task, Trace


class Outage(BaseModel):
    """A scheduled outage: a node, or every node of a layer, is unavailable for a while.

    A cloud outage stands in for losing the farm's internet link: work in progress there is lost and
    retried elsewhere, and nothing new can be sent until the link returns.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: str = Field(description="Node id, or a layer name (edge, fog, cloud) for every node of that layer")
    start_s: float = Field(ge=0)
    duration_s: float = Field(gt=0)
    label: str = ""


class SimSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window_s: float = Field(5.0, gt=0, description="Batch window for batch placement policies")
    failures: bool = Field(True, description="Apply node MTBF/MTTR values from the topology")
    retry_on_failure: bool = Field(True, description="Re-dispatch tasks lost to a node failure")
    max_attempts: int = Field(3, ge=1)
    inject_overhead: bool = Field(
        False,
        description="Add measured scheduler run time to simulated time "
        "(breaks bit-for-bit reproducibility; off by default)",
    )
    e_tx_j_per_mb: float = Field(0.0, ge=0, description="Transmission energy per MB per hop (0 = not modelled)")
    outages: tuple[Outage, ...] = Field((), description="Scheduled outages (cloud disconnection, fog failure)")


# event kinds
ARRIVE, WINDOW, AT_NODE, DONE, DELIVER, FAIL, REPAIR = range(7)


@dataclass
class TaskRecord:
    task: Task
    attempts: int = 0
    node: str | None = None
    dispatched_s: float | None = None
    at_node_s: float | None = None
    start_s: float | None = None
    finish_s: float | None = None
    delivered_s: float | None = None
    tx_in_s: float = 0.0
    tx_out_s: float = 0.0
    status: str = "pending"  # pending | completed | failed
    reason: str = ""

    @property
    def response_s(self) -> float | None:
        end = self.delivered_s if self.delivered_s is not None else None
        return None if end is None else end - self.task.arrival_s

    @property
    def deadline_met(self) -> bool:
        r = self.response_s
        return r is not None and r <= self.task.deadline_s + 1e-9


@dataclass
class NodeState:
    spec: Any
    up: bool = True
    busy: int = 0
    queue: list[tuple[tuple, int, int]] = field(default_factory=list)  # (key, seq, task id)
    running: dict[int, float] = field(default_factory=dict)  # task id -> finish time
    committed_mi: float = 0.0
    epoch: int = 0
    last_t: float = 0.0
    idle_j: float = 0.0
    dynamic_j: float = 0.0
    busy_core_s: float = 0.0
    up_s: float = 0.0
    tasks_done: int = 0
    failures: int = 0
    outage_until: float = -1.0  # end of a scheduled outage in progress
    fail_pending: bool = False  # a random (MTBF) failure event is waiting in the event queue

    def advance(self, t: float) -> None:
        dt = t - self.last_t
        if dt > 0 and self.up:
            cores = max(self.spec.cores, 1)
            self.idle_j += self.spec.p_idle_w * dt
            self.dynamic_j += (self.spec.p_max_w - self.spec.p_idle_w) * (self.busy / cores) * dt
            self.busy_core_s += self.busy * dt
            self.up_s += dt
        self.last_t = t


class Simulator:
    def __init__(
        self,
        topology: Topology,
        trace: Trace,
        placement: Placement,
        discipline: Discipline,
        settings: SimSettings | None = None,
        seed: int = 0,
    ) -> None:
        problems = topology.validation_report()
        if problems:
            raise ValueError("Topology cannot be simulated: " + " ".join(problems))
        self.topology = topology
        self.trace = trace
        self.placement = placement
        self.discipline = discipline
        self.settings = settings or SimSettings()
        self.router = Router(topology)
        streams = np.random.SeedSequence([seed, 0x51]).spawn(2)
        self.rng_failures = np.random.default_rng(streams[0])
        self.rng_policy = np.random.default_rng(streams[1])
        self.now = 0.0
        self._events: list[tuple[float, int, int, tuple]] = []
        self._seq = itertools.count()
        self.nodes = {n.id: NodeState(spec=n) for n in topology.nodes}
        self.records = {t.id: TaskRecord(task=t) for t in trace.tasks}
        self.pending_batch: list[int] = []
        self.overhead_ns: list[int] = []
        self.bytes_total = 0.0
        self.bytes_cloud = 0.0
        self.network_usage = 0.0  # iFogSim-style: sum over hops of latency_s * bytes
        self.tx_energy_j = 0.0
        self._arrivals_left = len(trace.tasks)
        self._window_scheduled = False
        self.view = ClusterView(self)

    # --- public -----------------------------------------------------------------------------------

    def run(self, progress: ProgressReporter = null_progress) -> Simulator:
        self.placement.reset(self.view, self.rng_policy)
        for task in self.trace.tasks:
            self._push(task.arrival_s, ARRIVE, (task.id,))
        if self.placement.batch and self.trace.tasks:
            self._schedule_window(self.trace.tasks[0].arrival_s + self.settings.window_s)
        if self.settings.failures:
            for ns in self.nodes.values():
                if ns.spec.mtbf_s > 0 and ns.spec.can_compute:
                    self._push(self.rng_failures.exponential(ns.spec.mtbf_s), FAIL, (ns.spec.id,))
                    ns.fail_pending = True
        for outage in self.settings.outages:
            targets = [
                nid
                for nid, ns in self.nodes.items()
                if ns.spec.can_compute and (nid == outage.target or str(ns.spec.layer) == outage.target)
            ]
            if not targets:
                raise ValueError(f"Outage target {outage.target!r} matches no computing node")
            for nid in targets:
                self._push(outage.start_s, FAIL, (nid, outage.start_s + outage.duration_s))
        total = max(len(self.records), 1)
        finished = 0
        last_report = 0.0
        while self._events:
            t, _, kind, payload = heapq.heappop(self._events)
            if kind in (FAIL, REPAIR) and self._all_settled():
                break  # only failure events left: the experiment is over
            self.now = t
            if kind == ARRIVE:
                self._on_arrive(payload[0])
            elif kind == WINDOW:
                self._on_window()
            elif kind == AT_NODE:
                self._on_at_node(*payload)
            elif kind == DONE:
                finished += self._on_done(*payload)
            elif kind == DELIVER:
                finished += self._on_deliver(payload[0])
            elif kind == FAIL:
                self._on_fail(*payload)
            elif kind == REPAIR:
                self._on_repair(*payload)
            if finished / total - last_report >= 0.02:
                last_report = finished / total
                progress(min(0.99, last_report), f"{finished} of {total} tasks finished")
        for rec in self.records.values():
            if rec.status == "pending":
                rec.status, rec.reason = "failed", "not finished"
        for ns in self.nodes.values():
            ns.advance(self.now)
        progress(1.0, "Simulation finished")
        return self

    # --- event handlers -----------------------------------------------------------------------------

    def _on_arrive(self, task_id: int) -> None:
        self._arrivals_left -= 1
        if self.placement.batch:
            self.pending_batch.append(task_id)
        else:
            self._dispatch_online(task_id)

    def _dispatch_online(self, task_id: int) -> None:
        task = self.records[task_id].task
        t0 = time.perf_counter_ns()
        node = self.placement.place(task, self.view)
        self._account_overhead(t0)
        self._send(task_id, node)

    def _on_window(self) -> None:
        self._window_scheduled = False
        if self.pending_batch:
            batch = [self.records[i].task for i in self.pending_batch]
            self.pending_batch = []
            t0 = time.perf_counter_ns()
            mapping = self.placement.place_batch(batch, self.view)
            self._account_overhead(t0)
            for task in batch:
                self._send(task.id, mapping.get(task.id))
        if self.pending_batch or self._arrivals_left > 0:
            self._schedule_window(self.now + self.settings.window_s)

    def _schedule_window(self, t: float) -> None:
        if not self._window_scheduled:
            self._window_scheduled = True
            self._push(t, WINDOW, ())

    def _send(self, task_id: int, node_id: str | None) -> None:
        rec = self.records[task_id]
        rec.attempts += 1
        if node_id is None or node_id not in self.nodes or not self.nodes[node_id].spec.can_compute:
            rec.status, rec.reason = "failed", "no eligible node"
            return
        delay = self.router.transfer_time(rec.task.source, node_id, rec.task.input_bytes)
        if delay == float("inf"):
            rec.status, rec.reason = "failed", "node unreachable"
            return
        self._account_transfer(rec.task.source, node_id, rec.task.input_bytes)
        rec.node, rec.dispatched_s, rec.tx_in_s = node_id, self.now + self._extra_delay(), delay
        self.nodes[node_id].committed_mi += rec.task.length_mi
        self._push(rec.dispatched_s + delay, AT_NODE, (task_id, node_id))

    def _on_at_node(self, task_id: int, node_id: str) -> None:
        rec, ns = self.records[task_id], self.nodes[node_id]
        if rec.status != "pending" or rec.node != node_id:
            return
        if not ns.up:
            ns.committed_mi -= rec.task.length_mi
            self._lost(task_id, "node down on arrival")
            return
        rec.at_node_s = self.now
        heapq.heappush(ns.queue, (self.discipline.key(rec.task, self.now), next(self._seq), task_id))
        self._try_start(ns)

    def _try_start(self, ns: NodeState) -> None:
        while ns.up and ns.queue and ns.busy < ns.spec.cores:
            _, _, task_id = heapq.heappop(ns.queue)
            rec = self.records[task_id]
            ns.advance(self.now)
            ns.busy += 1
            rec.start_s = self.now
            finish = self.now + rec.task.length_mi / ns.spec.mips
            ns.running[task_id] = finish
            self._push(finish, DONE, (task_id, ns.spec.id, ns.epoch))

    def _on_done(self, task_id: int, node_id: str, epoch: int) -> int:
        ns, rec = self.nodes[node_id], self.records[task_id]
        if epoch != ns.epoch or task_id not in ns.running:
            return 0  # the node failed while this task ran
        ns.advance(self.now)
        del ns.running[task_id]
        ns.busy -= 1
        ns.committed_mi -= rec.task.length_mi
        ns.tasks_done += 1
        rec.finish_s = self.now
        self._try_start(ns)
        if rec.task.result_to_source:
            delay = self.router.transfer_time(node_id, rec.task.source, rec.task.output_bytes)
            self._account_transfer(node_id, rec.task.source, rec.task.output_bytes)
            rec.tx_out_s = delay
            self._push(self.now + delay, DELIVER, (task_id,))
            return 0
        rec.delivered_s, rec.status = self.now, "completed"
        return 1

    def _on_deliver(self, task_id: int) -> int:
        rec = self.records[task_id]
        rec.delivered_s, rec.status = self.now, "completed"
        return 1

    def _on_fail(self, node_id: str, scheduled_end: float | None = None) -> None:
        """A random failure (MTBF), or the start of a scheduled outage that ends at ``scheduled_end``."""
        ns = self.nodes[node_id]
        if scheduled_end is not None:
            first = ns.outage_until < self.now
            ns.outage_until = max(ns.outage_until, scheduled_end)
            self._push(scheduled_end, REPAIR, (node_id, True))
            if not ns.up or not first:
                return  # already down: the outage just extends it
        else:
            ns.fail_pending = False
            if not ns.up:
                return  # a random failure while a scheduled outage holds the node down
        ns.advance(self.now)
        ns.up, ns.epoch, ns.failures = False, ns.epoch + 1, ns.failures + 1
        lost = list(ns.running) + [tid for _, _, tid in ns.queue]
        ns.running.clear()
        ns.queue.clear()
        ns.busy = 0
        for tid in lost:
            ns.committed_mi -= self.records[tid].task.length_mi
            self._lost(tid, f"{node_id} failed")
        if scheduled_end is None:
            self._push(self.now + self.rng_failures.exponential(max(ns.spec.mttr_s, 1e-9)), REPAIR, (node_id,))

    def _on_repair(self, node_id: str, scheduled: bool = False) -> None:
        ns = self.nodes[node_id]
        if self.now < ns.outage_until or ns.up:
            return  # a scheduled outage is still in force, or the node is already back
        ns.advance(self.now)
        ns.up, ns.committed_mi = True, max(ns.committed_mi, 0.0)
        if ns.spec.mtbf_s > 0 and self.settings.failures and not ns.fail_pending:
            self._push(self.now + self.rng_failures.exponential(ns.spec.mtbf_s), FAIL, (node_id,))
            ns.fail_pending = True

    def _lost(self, task_id: int, reason: str) -> None:
        rec = self.records[task_id]
        rec.start_s = rec.at_node_s = None
        if self.settings.retry_on_failure and rec.attempts < self.settings.max_attempts:
            rec.node = None
            if self.placement.batch:
                self.pending_batch.append(task_id)
                self._schedule_window(self.now + self.settings.window_s)
            else:
                self._dispatch_online(task_id)
        else:
            rec.status, rec.reason = "failed", reason

    # --- helpers ------------------------------------------------------------------------------------

    def _push(self, t: float, kind: int, payload: tuple) -> None:
        heapq.heappush(self._events, (t, next(self._seq), kind, payload))

    def _all_settled(self) -> bool:
        return all(k in (FAIL, REPAIR) for _, _, k, _ in self._events) and not self.pending_batch

    def _account_overhead(self, t0: int) -> None:
        self.overhead_ns.append(time.perf_counter_ns() - t0)

    def _extra_delay(self) -> float:
        return self.overhead_ns[-1] / 1e9 if self.settings.inject_overhead and self.overhead_ns else 0.0

    def _account_transfer(self, src: str, dst: str, size_bytes: float) -> None:
        if src == dst or size_bytes <= 0:
            return
        route = self.router.route(src, dst)
        if route is None:
            return
        self.bytes_total += size_bytes
        layers = {self.topology.node[src].layer, self.topology.node[dst].layer}
        if "cloud" in layers:
            self.bytes_cloud += size_bytes
        for hop in route.hops:
            self.network_usage += hop.latency_ms / 1000.0 * size_bytes
        self.tx_energy_j += self.settings.e_tx_j_per_mb * size_bytes / 1e6 * len(route.hops)


def simulate(
    topology: Topology,
    trace: Trace,
    placement: Placement,
    discipline: Discipline,
    settings: SimSettings | None = None,
    seed: int = 0,
    progress: ProgressReporter = null_progress,
) -> Simulator:
    return Simulator(topology, trace, placement, discipline, settings, seed).run(progress)
