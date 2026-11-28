"""Performance metrics computed from a finished simulation."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from smartagri_core.sim.engine import Simulator

# key -> (label, unit, higher_is_better). Drives tables and charts in the interface.
METRIC_INFO: dict[str, tuple[str, str, bool]] = {
    "tasks_total": ("Tasks", "", True),
    "completion_rate": ("Completed", "%", True),
    "deadline_success_rate": ("Deadlines met", "%", True),
    "urgent_deadline_success_rate": ("Urgent deadlines met", "%", True),
    "mean_response_s": ("Mean response time", "s", False),
    "p95_response_s": ("95th-percentile response time", "s", False),
    "urgent_mean_response_s": ("Urgent mean response time", "s", False),
    "mean_wait_s": ("Mean queueing time", "s", False),
    "mean_exec_s": ("Mean execution time", "s", False),
    "mean_transfer_s": ("Mean transfer time", "s", False),
    "energy_dynamic_j": ("Dynamic energy", "J", False),
    "energy_total_j": ("Total energy", "J", False),
    "energy_per_task_j": ("Energy per completed task", "J", False),
    "energy_edge_j": ("Edge energy", "J", False),
    "energy_fog_j": ("Fog energy", "J", False),
    "energy_cloud_j": ("Cloud energy", "J", False),
    "network_usage": ("Network usage (iFogSim definition)", "B", False),
    "bytes_total_mb": ("Data transferred", "MB", False),
    "bytes_cloud_mb": ("Data sent to or from the cloud", "MB", False),
    "cost": ("Cloud cost", "$", False),
    "utilization_edge": ("Edge utilisation", "%", True),
    "utilization_fog": ("Fog utilisation", "%", True),
    "utilization_cloud": ("Cloud utilisation", "%", True),
    "load_balance_cv": ("Load imbalance (CV of node utilisation)", "", False),
    "share_edge": ("Tasks run at the edge", "%", True),
    "share_fog": ("Tasks run in the fog", "%", True),
    "share_cloud": ("Tasks run in the cloud", "%", True),
    "scheduling_overhead_us": ("Mean scheduling decision time", "µs", False),
    "makespan_s": ("Makespan", "s", False),
    "node_failures": ("Node failures", "", False),
    "effective_deadline_success_rate": ("Effective deadlines met (deadline or data freshness)", "%", True),
    "aoi_violation_rate": ("Stale decisions (AoI violations)", "%", False),
    "urgent_aoi_violation_rate": ("Urgent stale decisions", "%", False),
    "decision_value_pct": ("Decision value delivered", "%", True),
    "autonomy_ratio": ("Urgent tasks completed locally (edge or fog)", "%", True),
    "replicated_tasks": ("Tasks replicated on a second node", "", False),
}

# Decision value (AURA design): full weight by the effective deadline, then exponential decay with a half-life
# of one stated deadline, and nothing after three deadlines. Weights follow the priority classes.
VALUE_WEIGHT = {"critical": 4.0, "high": 2.0, "medium": 1.0, "low": 0.5}


def decision_value(task, delivered_s: float | None) -> float:
    w = VALUE_WEIGHT.get(task.priority, 1.0)
    if delivered_s is None:
        return 0.0
    late = delivered_s - task.effective_deadline
    if late <= 0:
        return w
    if late > 3.0 * task.deadline_s:
        return 0.0
    return w * math.exp(-math.log(2.0) * late / task.deadline_s)


# Metrics shown by default in comparison tables.
HEADLINE_METRICS = [
    "deadline_success_rate",
    "urgent_deadline_success_rate",
    "mean_response_s",
    "p95_response_s",
    "energy_dynamic_j",
    "bytes_cloud_mb",
    "cost",
    "load_balance_cv",
    "scheduling_overhead_us",
]


# Extra metrics shown for stress scenarios (they need data timestamps or concern urgent autonomy).
STRESS_METRICS = [
    "effective_deadline_success_rate",
    "aoi_violation_rate",
    "decision_value_pct",
    "autonomy_ratio",
]


def compute_metrics(sim: Simulator) -> dict[str, float]:
    records = [r for r in sim.records.values() if r.replica_of is None]  # replica copies are not tasks
    replicas = len(sim.records) - len(records)
    n = len(records)
    done = [r for r in records if r.status == "completed"]
    urgent = [r for r in records if r.task.urgent]
    resp = np.array([r.response_s for r in done], dtype=float) if done else np.array([np.nan])
    urgent_done = [r for r in urgent if r.status == "completed"]
    horizon = max(sim.now, 1e-9)

    layer_of = {nid: ns.spec.layer for nid, ns in sim.nodes.items()}
    energy = {"edge": 0.0, "fog": 0.0, "cloud": 0.0}
    busy = {"edge": 0.0, "fog": 0.0, "cloud": 0.0}
    capacity = {"edge": 0.0, "fog": 0.0, "cloud": 0.0}
    utils = []
    cost = 0.0
    for ns in sim.nodes.values():
        if not ns.spec.can_compute:
            continue
        layer = str(ns.spec.layer)
        energy[layer] += ns.idle_j + ns.dynamic_j
        busy[layer] += ns.busy_core_s
        capacity[layer] += ns.spec.cores * horizon
        utils.append(ns.busy_core_s / (ns.spec.cores * horizon))
        cost += ns.busy_core_s * ns.spec.cost_per_core_s
    dynamic = sum(ns.dynamic_j for ns in sim.nodes.values())
    total_energy = sum(energy.values()) + sim.tx_energy_j
    shares = {"edge": 0, "fog": 0, "cloud": 0}
    for r in done:
        shares[str(layer_of[r.node])] += 1
    util_arr = np.array(utils) if utils else np.array([0.0])

    def delivered(r) -> float | None:
        return r.delivered_s if r.status == "completed" else None

    fresh = [r for r in records if math.isfinite(r.task.freshness_s)]
    urgent_fresh = [r for r in fresh if r.task.urgent]

    def stale_share(rs: list) -> float:
        if not rs:
            return float("nan")
        bad = sum(1 for r in rs if delivered(r) is None or delivered(r) > r.task.stale_at)
        return pct(bad / len(rs))

    weight_total = sum(VALUE_WEIGHT.get(r.task.priority, 1.0) for r in records)
    value_total = sum(decision_value(r.task, delivered(r)) for r in records)
    local_urgent = sum(1 for r in urgent_done if str(layer_of[r.node]) in ("edge", "fog"))

    def pct(x: float) -> float:
        return round(100.0 * x, 4)

    def mean(values: list[float]) -> float:
        return float(np.mean(values)) if values else float("nan")

    return {
        "tasks_total": n,
        "completion_rate": pct(len(done) / n) if n else float("nan"),
        "deadline_success_rate": pct(sum(r.deadline_met for r in records) / n) if n else float("nan"),
        "urgent_deadline_success_rate": pct(sum(r.deadline_met for r in urgent) / len(urgent))
        if urgent
        else float("nan"),
        "mean_response_s": float(np.nanmean(resp)),
        "p95_response_s": float(np.nanpercentile(resp, 95)),
        "urgent_mean_response_s": mean([r.response_s for r in urgent_done]),  # type: ignore[misc]
        "mean_wait_s": mean([r.start_s - r.at_node_s for r in done]),  # type: ignore[operator]
        "mean_exec_s": mean([r.finish_s - r.start_s for r in done]),  # type: ignore[operator]
        "mean_transfer_s": mean([r.tx_in_s + r.tx_out_s for r in done]),
        "energy_dynamic_j": dynamic,
        "energy_total_j": total_energy,
        "energy_per_task_j": total_energy / len(done) if done else float("nan"),
        "energy_edge_j": energy["edge"],
        "energy_fog_j": energy["fog"],
        "energy_cloud_j": energy["cloud"],
        "network_usage": sim.network_usage / horizon,
        "bytes_total_mb": sim.bytes_total / 1e6,
        "bytes_cloud_mb": sim.bytes_cloud / 1e6,
        "cost": cost,
        "utilization_edge": pct(busy["edge"] / capacity["edge"]) if capacity["edge"] else float("nan"),
        "utilization_fog": pct(busy["fog"] / capacity["fog"]) if capacity["fog"] else float("nan"),
        "utilization_cloud": pct(busy["cloud"] / capacity["cloud"]) if capacity["cloud"] else float("nan"),
        "load_balance_cv": float(util_arr.std() / util_arr.mean()) if util_arr.mean() > 0 else 0.0,
        "share_edge": pct(shares["edge"] / len(done)) if done else float("nan"),
        "share_fog": pct(shares["fog"] / len(done)) if done else float("nan"),
        "share_cloud": pct(shares["cloud"] / len(done)) if done else float("nan"),
        "scheduling_overhead_us": float(np.mean(sim.overhead_ns)) / 1000.0 if sim.overhead_ns else 0.0,
        "makespan_s": horizon,
        "node_failures": sum(ns.failures for ns in sim.nodes.values()),
        "effective_deadline_success_rate": pct(
            sum(1 for r in records if delivered(r) is not None and delivered(r) <= r.task.effective_deadline) / n
        )
        if n
        else float("nan"),
        "aoi_violation_rate": stale_share(fresh),
        "urgent_aoi_violation_rate": stale_share(urgent_fresh),
        "decision_value_pct": pct(value_total / weight_total) if weight_total else float("nan"),
        "autonomy_ratio": pct(local_urgent / len(urgent)) if urgent else float("nan"),
        "replicated_tasks": replicas,
    }


def node_stats(sim: Simulator) -> list[dict[str, float | str | int]]:
    """Per-node statistics for the resource view, ordered cloud, fog, edge."""
    horizon = max(sim.now, 1e-9)
    order = {"cloud": 0, "fog": 1, "edge": 2, "iot": 3}
    rows = []
    for ns in sim.nodes.values():
        if not ns.spec.can_compute:
            continue
        rows.append(
            {
                "id": ns.spec.id,
                "layer": str(ns.spec.layer),
                "cores": ns.spec.cores,
                "mips": ns.spec.mips,
                "utilization": round(100.0 * ns.busy_core_s / (ns.spec.cores * horizon), 4),
                "tasks_done": ns.tasks_done,
                "energy_j": ns.idle_j + ns.dynamic_j,
                "dynamic_energy_j": ns.dynamic_j,
                "failures": ns.failures,
                "availability": round(100.0 * ns.up_s / horizon, 4),
            }
        )
    return sorted(rows, key=lambda r: (order[str(r["layer"])], str(r["id"])))
