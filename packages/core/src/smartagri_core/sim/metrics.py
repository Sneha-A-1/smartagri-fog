"""Performance metrics computed from a finished simulation."""

from __future__ import annotations

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
}

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


def compute_metrics(sim: Simulator) -> dict[str, float]:
    records = list(sim.records.values())
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
    }
