"""AURA: Age- and Urgency-aware Reliable Allocation (working name).

Implements the design in the project document (tab "Proposed algorithm: AURA") on the platform's simulator:

* **Tier 1, urgent tasks (online, per arrival; Algorithm 1).** For each eligible node, estimate the finish time
  F = upload + wait for a core + urgent work queued ahead + execution + return, and the probability p that the
  placement succeeds. Score the node by p·V(F) − α·w·E/E_max − β·w·C/C_max, where V is the decision value
  (full weight w by the effective deadline D = min(stated deadline, data time + freshness bound), then
  exponential decay with a half-life of one deadline, zero after three) and E, C are the energy and cost of the
  placement. The best node wins. A critical task whose best placement has p < p_min is replicated on the best
  node of another layer, whose failure is independent of the first.
* **Tier 2, strategic tasks (batch, every window; Algorithm 2).** Medium and low tasks wait for the window.
  NSGA-II (seeded with Min-Min, greedy MCT and edge-ward) maps them using only capacity not reserved for urgent
  work, weighting energy and cost more than the urgent tier does. Tasks with no reachable node (for example
  during a cloud disconnection) are deferred to the next window while their deadline allows (store and forward).
* **Anticipatory reservation (every period; Algorithm 3).** For each farm region (an edge device and its
  gateways), demand = EWMA of urgent arrivals × (1 + κ × share of the region's gateways under an active early
  warning) × mean urgent length. The edge device reserves that share of its capacity (between r_min and r_max);
  demand beyond it is reserved on the region's fog server.
* **Queue discipline** ``queue_discipline:aura``: urgent tasks before strategic ones, then earliest effective
  deadline.

Not implemented (reported as such): preempting a running strategic task, and switching to a registered light
variant of a task. The urgent tier overtakes queued strategic work through the queue discipline instead.

Ablations, each registered as its own placement: ``aura_noaoi`` (deadline only), ``aura_noreserve`` (r = 0),
``aura_staticreserve`` (fixed r, no warnings), ``aura_noreliability`` (p = 1, no replication) and
``aura_singletier`` (Algorithm 1 for every task).
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from smartagri_core.registry import PluginKind, register
from smartagri_core.sched.batchopt import SolverSettings, Weights, nsga2
from smartagri_core.sim.metrics import VALUE_WEIGHT
from smartagri_core.sim.opt_placement import problem_from_view
from smartagri_core.sim.policies import ALL_LAYERS, DEFER, ClusterView, Discipline, Placement
from smartagri_core.sim.topology import Layer
from smartagri_core.sim.workload import PRIORITY_RANK, Task
from smartagri_core.status import CapabilityStatus

IMPL = CapabilityStatus.IMPLEMENTED
SOURCE = "smartagri-proposed"
REFERENCE = "SmartAgri-Fog project document, 'Proposed algorithm: AURA' (this work)"


def value(task: Task, finish: float, deadline: float) -> float:
    """Decision value of delivering at ``finish`` against effective deadline ``deadline`` (AURA's V_i)."""
    w = VALUE_WEIGHT.get(task.priority, 1.0)
    late = finish - deadline
    if late <= 0:
        return w
    if late > 3.0 * task.deadline_s:
        return 0.0
    return w * math.exp(-math.log(2.0) * late / task.deadline_s)


class AuraParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_aoi: bool = Field(True, description="Use the data-freshness bound in the effective deadline.")
    reservation: Literal["anticipatory", "static", "none"] = Field(
        "anticipatory", description="Capacity reservation for urgent work."
    )
    use_reliability: bool = Field(True, description="Weight nodes by success probability and replicate critical tasks.")
    two_tier: bool = Field(True, description="Batch strategic tasks with NSGA-II (off: Algorithm 1 for every task).")
    alpha: float = Field(0.02, ge=0, description="Urgent tier: energy penalty, as a share of the task's value weight.")
    beta: float = Field(0.02, ge=0, description="Urgent tier: cost penalty, as a share of the task's value weight.")
    alpha_strategic: float = Field(
        0.2,
        ge=0,
        description="Single-tier variant: energy penalty for strategic tasks.",
        json_schema_extra={"x-advanced": True},
    )
    beta_strategic: float = Field(
        0.2,
        ge=0,
        description="Single-tier variant: cost penalty for strategic tasks.",
        json_schema_extra={"x-advanced": True},
    )
    p_min: float = Field(
        0.95, ge=0, le=1, description="Replicate a critical task when its success probability is lower."
    )
    prior_mtbf_s: float = Field(
        86_400.0,
        gt=0,
        description="Assumed mean time between failures before any is observed.",
        json_schema_extra={"x-advanced": True},
    )
    budget: int = Field(300, ge=20, le=100_000, description="Strategic tier: NSGA-II evaluations per window.")
    pop_size: int = Field(20, ge=4, le=500, json_schema_extra={"x-advanced": True})
    w_energy: float = Field(0.3, ge=0, description="Strategic tier: weight of energy when choosing from the front.")
    w_cost: float = Field(0.3, ge=0, description="Strategic tier: weight of cloud cost when choosing from the front.")
    period_s: float = Field(60.0, gt=0, description="Reservation update period.")
    ewma: float = Field(
        0.3, gt=0, le=1, description="Smoothing of the urgent arrival rate.", json_schema_extra={"x-advanced": True}
    )
    kappa: float = Field(
        3.0, ge=0, description="Expected extra urgent load per warned gateway, as a multiple of normal."
    )
    warning_hold_s: float = Field(
        1200.0,
        ge=0,
        description="A warning stays active this long after its predicted onset.",
        json_schema_extra={"x-advanced": True},
    )
    r_min: float = Field(0.0, ge=0, le=1, json_schema_extra={"x-advanced": True})
    r_max: float = Field(0.6, ge=0, le=1, description="Largest share of a node that can be reserved.")
    static_share: float = Field(0.3, ge=0, le=1, description="Reservation of the static variant.")


class Aura(Placement):
    """AURA placement policy (hybrid: urgent online, strategic in windows)."""

    hybrid = True

    def __init__(self, params: AuraParams | None = None) -> None:
        self.p = params or AuraParams()
        self.settings = SolverSettings(self.p.budget, self.p.pop_size)
        self.weights = Weights(deadline=1.0, response=0.05, energy=self.p.w_energy, cost=self.p.w_cost)

    # --- set-up ---------------------------------------------------------------------------------------

    def reset(self, view: ClusterView, rng: np.random.Generator) -> None:
        super().reset(view, rng)
        topology, _, _ = view.training_context()
        layer = {n.id: n.layer for n in topology.nodes}
        adj = topology.adjacency
        self.region_of: dict[str, str] = {}  # gateway -> edge node
        self.gateways: dict[str, list[str]] = defaultdict(list)
        for n in topology.nodes:
            if n.layer == Layer.IOT:
                edges = sorted(m for m, _ in adj[n.id] if layer[m] == Layer.EDGE)
                if edges:
                    self.region_of[n.id] = edges[0]
                    self.gateways[edges[0]].append(n.id)
        self.fog_of: dict[str, str] = {}
        for e in self.gateways:
            fogs = sorted(m for m, _ in adj[e] if layer[m] == Layer.FOG)
            if fogs:
                self.fog_of[e] = fogs[0]
        self.capacity = {n.id: n.mips * n.cores for n in topology.nodes if n.can_compute}
        self.layer = layer
        self.reserved: dict[str, float] = {}
        if self.p.reservation == "static":
            self.reserved = {nid: self.p.static_share for nid in self.capacity if layer[nid] in (Layer.EDGE, Layer.FOG)}
        self.rate: dict[str, float] = defaultdict(float)
        self.count: dict[str, int] = defaultdict(int)
        self.mean_len = 1000.0
        self.n_urgent = 0
        self.next_explain = 0.0
        self.last_update = 0.0
        self.log: dict[str, Any] = {
            "tier1": 0,
            "tier2": 0,
            "replicated": 0,
            "deferred": 0,
            "late_at_decision": 0,
            "reservation": [],
            "explanations": [],
        }

    def defer(self, task: Task) -> bool:
        return self.p.two_tier and not task.urgent

    # --- Tier 1 ---------------------------------------------------------------------------------------

    def _deadline(self, task: Task) -> float:
        return task.effective_deadline if self.p.use_aoi else task.abs_deadline

    def _success(self, view: ClusterView, node: str, span: float) -> float:
        if not self.p.use_reliability:
            return 1.0
        t0 = 3600.0  # weight of the prior, in seconds of pseudo-observation
        rate = (view.failures_seen(node) + t0 / self.p.prior_mtbf_s) / (view.now + t0)
        return math.exp(-rate * max(span, 0.0))

    def place(self, task: Task, view: ClusterView):
        self._observe(task, view)
        nodes = view.eligible(task)
        if not nodes:
            return None
        self.log["tier1"] += 1
        now = view.now
        deadline = self._deadline(task)
        w = VALUE_WEIGHT.get(task.priority, 1.0)
        alpha, beta = (self.p.alpha, self.p.beta) if task.urgent else (self.p.alpha_strategic, self.p.beta_strategic)
        rows = []
        for n in nodes:
            exe = task.length_mi / n.mips
            tx_in = view.transfer_time(task.source, n.id, task.input_bytes)
            tx_out = view.transfer_time(n.id, task.source, task.output_bytes) if task.result_to_source else 0.0
            if task.urgent:  # urgent work overtakes queued strategic work, but waits for a free core
                wait = view.core_free_in(n.id) + view.urgent_backlog_s(n.id)
            else:
                wait = max(view.core_free_in(n.id), view.backlog_s(n.id))
            finish = now + tx_in + wait + exe + tx_out
            energy = (n.p_max_w - n.p_idle_w) / max(n.cores, 1) * exe
            cost = n.cost_per_core_s * exe
            rows.append((n, finish, self._success(view, n.id, finish - now), energy, cost))
        e_max = max(r[3] for r in rows) or 1.0
        c_max = max(r[4] for r in rows) or 1.0
        scored = []
        for n, finish, p, energy, cost in rows:
            v = value(task, finish, deadline)
            score = p * v - alpha * w * energy / e_max - beta * w * cost / c_max
            scored.append((score, -finish, n.id, n, finish, p, v))
        scored.sort(key=lambda r: (-r[0], -r[1], r[2]))
        best = scored[0]
        if best[4] > deadline:
            self.log["late_at_decision"] += 1
        if task.urgent:
            self.n_urgent += 1
            # Keep one example decision per reservation period (at most 30), spread over the whole run.
            if now >= self.next_explain and len(self.log["explanations"]) < 30:
                self.next_explain = now + self.p.period_s
                self.log["explanations"].append(self._explain(task, deadline, scored[:3], now))
        if self.p.use_reliability and task.priority == "critical" and best[5] < self.p.p_min:
            others = [r for r in scored[1:] if self.layer[r[2]] != self.layer[best[2]]]
            if others:
                self.log["replicated"] += 1
                return [best[2], others[0][2]]
        return best[2]

    @staticmethod
    def _explain(task: Task, deadline: float, top: list, now: float) -> dict[str, Any]:
        return {
            "time_s": round(now, 1),
            "task": task.cls,
            "priority": task.priority,
            "effective_deadline_in_s": round(deadline - now, 3),
            "candidates": [
                {
                    "node": r[2],
                    "score": round(r[0], 4),
                    "finish_in_s": round(r[4] - now, 3),
                    "success_probability": round(r[5], 6),
                    "value": round(r[6], 4),
                }
                for r in top
            ],
        }

    # --- reservation (Algorithm 3) --------------------------------------------------------------------

    def _observe(self, task: Task, view: ClusterView) -> None:
        if task.urgent:
            self.count[self.region_of.get(task.source, "")] += 1
            self.mean_len = 0.99 * self.mean_len + 0.01 * task.length_mi
        if view.now - self.last_update >= self.p.period_s:
            self._update_reservation(view)

    def _update_reservation(self, view: ClusterView) -> None:
        dt = max(view.now - self.last_update, 1e-9)
        self.last_update = view.now
        for region in self.gateways:
            self.rate[region] = (1 - self.p.ewma) * self.rate[region] + self.p.ewma * self.count[region] / dt
        self.count.clear()
        if self.p.reservation != "anticipatory":
            return
        warned: set[str] = set()
        for s in view.signals_until_now():
            if view.now <= s.time_s + s.eta_s + self.p.warning_hold_s:
                warned.add(s.source)
        reserved: dict[str, float] = {}
        overflow: dict[str, float] = defaultdict(float)
        for edge, gws in self.gateways.items():
            share = sum(1 for g in gws if g in warned) / len(gws)
            demand = self.rate[edge] * (1.0 + self.p.kappa * share) * self.mean_len  # MI/s
            cap = self.capacity.get(edge, 0.0)
            if cap <= 0:
                continue
            reserved[edge] = min(max(demand / cap, self.p.r_min), self.p.r_max)
            if edge in self.fog_of:
                overflow[self.fog_of[edge]] += max(demand - self.p.r_max * cap, 0.0)
        for fog in {f for f in self.fog_of.values()}:
            cap = self.capacity.get(fog, 0.0)
            if cap > 0:
                reserved[fog] = min(max(overflow[fog] / cap, self.p.r_min), self.p.r_max)
        self.reserved = reserved
        edge_r = [v for k, v in reserved.items() if self.layer[k] == Layer.EDGE]
        fog_r = [v for k, v in reserved.items() if self.layer[k] == Layer.FOG]
        self.log["reservation"].append(
            {
                "time_s": round(view.now, 1),
                "edge": float(np.mean(edge_r)) if edge_r else 0.0,
                "fog": float(np.mean(fog_r)) if fog_r else 0.0,
                "warned_gateways": len(warned),
            }
        )

    # --- Tier 2 (Algorithm 2) -------------------------------------------------------------------------

    def place_batch(self, tasks: list[Task], view: ClusterView) -> dict[int, str | None]:
        for t in tasks:
            self._observe(t, view)
        out: dict[int, str | None] = {}
        scale = {nid: 1.0 - r for nid, r in self.reserved.items()} if self.p.reservation != "none" else None
        problem = problem_from_view(tasks, view, self.weights, capacity_scale=scale)
        placed = set(problem.task_ids) if problem is not None else set()
        window = view._sim.settings.window_s
        for t in tasks:
            if t.id not in placed:
                if view.now + window < t.abs_deadline:
                    out[t.id] = DEFER
                    self.log["deferred"] += 1
                else:
                    out[t.id] = None
        if problem is None:
            return out
        order = {Layer.EDGE: 0, Layer.FOG: 1, Layer.CLOUD: 2}
        edge_ward = np.array(
            [
                min(
                    range(int(problem.n_cand[i])),
                    key=lambda k, i=i: (order.get(self.layer[problem.node_ids[problem.cand[i, k]]], 3), k),
                )
                for i in range(problem.n_tasks)
            ],
            dtype=np.int64,
        )
        res = nsga2(problem, self.rng, self.settings, [problem.min_min(), problem.greedy_mct(), edge_ward])
        self.log["tier2"] += problem.n_tasks
        out.update(problem.mapping(res.genes))
        return out


_SUMMARY = (
    "Two-tier, freshness- and urgency-aware scheduler with anticipatory capacity reservation "
    "for agricultural edge-fog-cloud systems."
)
_DESCRIPTION = (
    "Tier 1 places urgent tasks online by expected decision value (Age-of-Information-aware deadlines, "
    "success probability, energy and cost) and replicates critical tasks when success is uncertain. Tier 2 maps "
    "strategic tasks every window with NSGA-II on capacity not reserved for urgent work. Reservations "
    "anticipate surges from early warnings. Not implemented: preempting running tasks and light task variants."
)

register(
    kind=PluginKind.SCHEDULER,
    key="aura",
    name="AURA (proposed)",
    version="1.0.0",
    status=IMPL,
    source=SOURCE,
    summary=_SUMMARY,
    description=_DESCRIPTION,
    references=[REFERENCE],
    params=AuraParams,
    layers=["edge", "fog", "cloud"],
    agri_applications=["Irrigation emergencies", "Crop-health alerts", "Strategic analytics"],
    inputs=["Tasks with class, deadline and freshness bound", "Topology state", "Early warnings"],
    outputs=["Task-to-node placements", "Decision explanations", "Reservation timeline"],
    metrics=["Urgent deadline success", "AoI violations", "Decision value", "Energy", "Cost", "Autonomy ratio"],
    tags=["proposed"],
    phase=4,
)(Aura)

ABLATIONS: dict[str, tuple[str, str, dict[str, Any]]] = {
    "aura": ("AURA (proposed)", "The full algorithm.", {}),
    "aura_noaoi": ("AURA without AoI", "Effective deadline uses the stated deadline only.", {"use_aoi": False}),
    "aura_noreserve": ("AURA without reservation", "No capacity is reserved for urgent work.", {"reservation": "none"}),
    "aura_staticreserve": (
        "AURA with static reservation",
        "A fixed share is reserved; early warnings are ignored.",
        {"reservation": "static"},
    ),
    "aura_noreliability": (
        "AURA without reliability",
        "Success probability is taken as 1 and nothing is replicated.",
        {"use_reliability": False},
    ),
    "aura_singletier": ("AURA single tier", "Algorithm 1 places every task; no NSGA-II tier.", {"two_tier": False}),
}

for _key, (_name, _what, _overrides) in ABLATIONS.items():

    def _factory(params: AuraParams | None = None, _o=_overrides):
        base = (params or AuraParams()).model_dump()
        return Aura(AuraParams(**(base | _o)))

    _factory.__name__ = f"make_{_key}"
    register(
        kind=PluginKind.PLACEMENT,
        key=_key,
        name=_name,
        version="1.0.0",
        status=IMPL,
        source=SOURCE,
        summary=_what if _key != "aura" else _SUMMARY,
        description=_DESCRIPTION if _key == "aura" else f"Ablation of AURA. {_what}",
        references=[REFERENCE],
        params=AuraParams,
        layers=ALL_LAYERS,
        tags=["proposed"] + (["ablation"] if _key != "aura" else []),
        phase=4,
    )(_factory)


@register(
    kind=PluginKind.QUEUE_DISCIPLINE,
    key="aura",
    name="Urgent first, earliest effective deadline (AURA)",
    version="1.0.0",
    status=IMPL,
    source=SOURCE,
    summary="Urgent tasks before strategic ones, then by the earlier of deadline and data staleness.",
    references=[REFERENCE],
    layers=ALL_LAYERS,
    tags=["proposed"],
    phase=4,
)
class AuraQueue(Discipline):
    def __init__(self, params=None) -> None:
        pass

    def key(self, task: Task, enqueued_s: float) -> tuple:
        return (0 if task.urgent else 1, task.effective_deadline, enqueued_s)


@register(
    kind=PluginKind.QUEUE_DISCIPLINE,
    key="urgent_edf",
    name="Urgent first, earliest deadline",
    version="1.0.0",
    status=IMPL,
    source=SOURCE,
    summary="Urgent tasks before strategic ones, then earliest stated deadline (used by the no-AoI ablation).",
    references=[REFERENCE],
    layers=ALL_LAYERS,
    tags=["proposed", "ablation"],
    phase=4,
)
class UrgentEDF(Discipline):
    def __init__(self, params=None) -> None:
        pass

    def key(self, task: Task, enqueued_s: float) -> tuple:
        return (PRIORITY_RANK[task.priority] > 1, task.abs_deadline, enqueued_s)
