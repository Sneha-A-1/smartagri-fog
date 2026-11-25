"""Runnable simulation plugins: a single run, and a replicated comparison of placement policies.

Comparisons use common random numbers: for each replication one workload trace is generated from the
replication's seed and replayed for every algorithm.
"""

from __future__ import annotations

import math
import platform
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from smartagri_core import __version__
from smartagri_core.progress import ProgressReporter, null_progress
from smartagri_core.registry import PluginKind, get_registry, register
from smartagri_core.sim.engine import SimSettings, Simulator, simulate
from smartagri_core.sim.metrics import HEADLINE_METRICS, METRIC_INFO, compute_metrics, node_stats
from smartagri_core.sim.policies import DISCIPLINE_KEYS, PLACEMENT_KEYS
from smartagri_core.sim.topology import FarmTopologyParams, Topology, farm_topology
from smartagri_core.sim.workload import WorkloadSpec, agri_workload, generate_trace
from smartagri_core.stats import summarize
from smartagri_core.status import CapabilityStatus, DataOrigin


class ScenarioParams(BaseModel):
    """Scenario settings shared by simulation plugins (flat, so the GUI can render them as one form)."""

    model_config = ConfigDict(extra="forbid")

    farms: int = Field(4, ge=1, le=200, description="Number of farms.")
    gateways_per_farm: int = Field(2, ge=1, le=50, description="IoT gateways per farm (task sources).")
    edge_per_farm: int = Field(1, title="Edge devices per farm", ge=1, le=20, description="Edge devices per farm.")
    fog_nodes: int = Field(2, ge=1, le=50, description="Regional fog servers.")
    cloud_nodes: int = Field(1, ge=1, le=10, description="Cloud servers.")
    duration_s: float = Field(
        title="Duration",
        default=3600.0,
        ge=60,
        le=7 * 86400,
        description="Simulated time over which tasks arrive.",
        json_schema_extra={"x-unit": "s"},
    )
    intensity: float = Field(
        20.0, gt=0, le=200, description="Workload multiplier on the agricultural task mix (1 = light load)."
    )
    window_s: float = Field(
        title="Batch window",
        default=5.0,
        gt=0,
        le=600,
        description="Batch window for Min-Min and Max-Min.",
        json_schema_extra={"x-unit": "s", "x-advanced": True},
    )
    mtbf_edge_s: float = Field(
        title="Edge MTBF",
        default=0.0,
        ge=0,
        description="Mean time between edge-device failures (0 = no failures).",
        json_schema_extra={"x-unit": "s", "x-advanced": True},
    )
    mtbf_fog_s: float = Field(
        title="Fog MTBF",
        default=0.0,
        ge=0,
        description="Mean time between fog-server failures (0 = no failures).",
        json_schema_extra={"x-unit": "s", "x-advanced": True},
    )
    mttr_s: float = Field(
        title="Repair time (MTTR)",
        default=300.0,
        ge=0,
        description="Mean repair time after a failure.",
        json_schema_extra={"x-unit": "s", "x-advanced": True},
    )
    wan_bandwidth_mbps: float = Field(
        title="Cloud link bandwidth",
        default=50.0,
        gt=0,
        le=10000,
        description="Fog-to-cloud link bandwidth.",
        json_schema_extra={"x-unit": "Mbit/s", "x-advanced": True},
    )
    wan_latency_ms: float = Field(
        title="Cloud link latency",
        default=100.0,
        ge=0,
        le=2000,
        description="Fog-to-cloud one-way latency.",
        json_schema_extra={"x-unit": "ms", "x-advanced": True},
    )

    def build(self) -> tuple[Topology, WorkloadSpec, SimSettings]:
        topo = farm_topology(
            FarmTopologyParams(
                farms=self.farms,
                gateways_per_farm=self.gateways_per_farm,
                edge_per_farm=self.edge_per_farm,
                fog_nodes=self.fog_nodes,
                cloud_nodes=self.cloud_nodes,
                mtbf_edge_s=self.mtbf_edge_s,
                mtbf_fog_s=self.mtbf_fog_s,
                mttr_s=self.mttr_s,
                wan_bandwidth_mbps=self.wan_bandwidth_mbps,
                wan_latency_ms=self.wan_latency_ms,
            )
        )
        return topo, agri_workload(self.duration_s, self.intensity), SimSettings(window_s=self.window_s)


def _make_policies(placement: str, discipline: str) -> tuple[Any, Any]:
    reg = get_registry()
    return reg.create(f"placement:{placement}"), reg.create(f"queue_discipline:{discipline}")


def _environment() -> dict[str, str]:
    return {"core_version": __version__, "python": platform.python_version()}


def _clean(d: dict[str, float]) -> dict[str, float | None]:
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in d.items()}


class SingleRunParams(ScenarioParams):
    placement: PLACEMENT_KEYS = Field("mct", description="Which node runs each task.")
    discipline: DISCIPLINE_KEYS = Field("edf", description="Order in which each node runs its waiting tasks.")
    seed: int = Field(1, ge=0, description="Random seed for the workload and failures.")


@register(
    kind=PluginKind.SIMULATION,
    key="single_run",
    name="Simulation: single run",
    version="0.1.0",
    status=CapabilityStatus.IMPLEMENTED,
    summary="Simulates one placement policy on a generated farm network and agricultural workload.",
    description=(
        "Runs the discrete-event simulator once. Results describe a simulated system and are labelled "
        "synthetic. Use the comparison plugin for statistically meaningful comparisons."
    ),
    params=SingleRunParams,
    layers=["edge", "fog", "cloud"],
    outputs=["Performance metrics", "Per-layer statistics"],
    metrics=list(METRIC_INFO),
    phase=1,
    tags=["simulation"],
)
class SingleRun:
    def __init__(self, params: SingleRunParams) -> None:
        self.p = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        topo, spec, settings = self.p.build()
        return single_run_result(
            topo,
            spec,
            settings,
            self.p.placement,
            self.p.discipline,
            self.p.seed,
            self.p.model_dump(mode="json"),
            progress,
        )


def single_run_result(
    topo: Topology,
    workload: WorkloadSpec,
    settings: SimSettings,
    placement_key: str,
    discipline_key: str,
    seed: int,
    params: dict[str, Any],
    progress: ProgressReporter = null_progress,
) -> dict[str, Any]:
    """Run once and package metrics, per-node statistics and provenance."""
    trace = generate_trace(workload, topo, seed)
    placement, discipline = _make_policies(placement_key, discipline_key)
    sim: Simulator = simulate(topo, trace, placement, discipline, settings, seed=seed, progress=progress)
    metrics = _clean(compute_metrics(sim))
    return {
        "data_origin": str(DataOrigin.SYNTHETIC),
        "kind": "simulation.single_run",
        "params": params,
        "provenance": {"topology_sha256": topo.sha256, "trace_sha256": trace.sha256, **_environment()},
        "metric_info": {k: list(v) for k, v in METRIC_INFO.items()},
        "metrics": metrics,
        "nodes": node_stats(sim),
        "summary": {
            k: metrics[k] for k in ["tasks_total", "deadline_success_rate", "mean_response_s", "energy_dynamic_j"]
        },
    }


class CustomRunParams(BaseModel):
    """A single run on a saved topology and workload (used by the Simulation page)."""

    model_config = ConfigDict(extra="forbid")

    topology: Topology
    workload: WorkloadSpec
    placement: PLACEMENT_KEYS = "mct"
    discipline: DISCIPLINE_KEYS = "edf"
    seed: int = Field(1, ge=0)
    settings: SimSettings = Field(default_factory=SimSettings)
    topology_name: str = ""
    workload_name: str = ""


@register(
    kind=PluginKind.SIMULATION,
    key="custom_run",
    name="Simulation: run a saved network and workload",
    version="0.1.0",
    status=CapabilityStatus.IMPLEMENTED,
    summary="Simulates one policy on a topology and workload designed in the browser.",
    params=CustomRunParams,
    phase=1,
    tags=["internal", "simulation"],
)
class CustomRun:
    def __init__(self, params: CustomRunParams) -> None:
        self.p = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        params = {
            "placement": self.p.placement,
            "discipline": self.p.discipline,
            "seed": self.p.seed,
            "topology": self.p.topology_name or self.p.topology.name,
            "workload": self.p.workload_name or self.p.workload.name,
            "settings": self.p.settings.model_dump(mode="json"),
        }
        return single_run_result(
            self.p.topology,
            self.p.workload,
            self.p.settings,
            self.p.placement,
            self.p.discipline,
            self.p.seed,
            params,
            progress,
        )


class ComparisonParams(ScenarioParams):
    placements: list[PLACEMENT_KEYS] = Field(
        default_factory=lambda: ["cloud_only", "edge_ward", "least_loaded", "mct", "min_min"],
        min_length=1,
        description="Placement policies to compare on identical workloads.",
    )
    discipline: DISCIPLINE_KEYS = Field("edf", description="Queue discipline used by every node.")
    replications: int = Field(10, ge=2, le=100, description="Independent repetitions per policy (30 for papers).")
    base_seed: int = Field(1, title="First seed", ge=0, description="Replication r uses seed base_seed + r.")

    @model_validator(mode="after")
    def _unique(self) -> ComparisonParams:
        if len(set(self.placements)) != len(self.placements):
            raise ValueError("Each placement policy may appear only once")
        return self


@register(
    kind=PluginKind.SIMULATION,
    key="comparison",
    name="Simulation: compare placement policies",
    version="0.1.0",
    status=CapabilityStatus.IMPLEMENTED,
    summary="Runs several placement policies on identical workloads, repeated with different seeds, with 95% CIs.",
    description=(
        "Common random numbers: each replication generates one workload trace and replays it for every "
        "policy. Reports mean and 95% confidence interval per metric. Significance tests arrive in Phase 1b."
    ),
    params=ComparisonParams,
    layers=["edge", "fog", "cloud"],
    outputs=["Per-policy metrics with confidence intervals"],
    metrics=HEADLINE_METRICS,
    phase=1,
    tags=["simulation", "experiment"],
)
class Comparison:
    def __init__(self, params: ComparisonParams) -> None:
        self.p = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        topo, spec, settings = self.p.build()
        runs: list[dict[str, Any]] = []
        total = self.p.replications * len(self.p.placements)
        trace_hashes = []
        for r in range(self.p.replications):
            seed = self.p.base_seed + r
            trace = generate_trace(spec, topo, seed)
            trace_hashes.append(trace.sha256)
            for placement_key in self.p.placements:
                placement, discipline = _make_policies(placement_key, self.p.discipline)
                sim = simulate(topo, trace, placement, discipline, settings, seed=seed)
                runs.append(
                    {
                        "replication": r,
                        "seed": seed,
                        "placement": placement_key,
                        "metrics": _clean(compute_metrics(sim)),
                    }
                )
                done = len(runs)
                progress(done / total, f"Run {done} of {total}: {placement_key}, replication {r + 1}")

        table: dict[str, dict[str, dict[str, float]]] = {}
        for placement_key in self.p.placements:
            mine = [run["metrics"] for run in runs if run["placement"] == placement_key]
            table[placement_key] = {
                m: _clean(summarize([x[m] if x[m] is not None else math.nan for x in mine])) for m in METRIC_INFO
            }
        return {
            "data_origin": str(DataOrigin.SYNTHETIC),
            "kind": "simulation.comparison",
            "params": self.p.model_dump(mode="json"),
            "provenance": {"topology_sha256": topo.sha256, "trace_sha256": trace_hashes, **_environment()},
            "metric_info": {k: list(v) for k, v in METRIC_INFO.items()},
            "headline_metrics": HEADLINE_METRICS,
            "comparison": table,
            "runs": runs,
            "summary": {
                "policies": len(self.p.placements),
                "replications": self.p.replications,
                "runs": len(runs),
                "tasks_per_run": runs[0]["metrics"]["tasks_total"] if runs else 0,
            },
        }
