"""Reproducible experiments: a declarative specification, a runner, and exports for papers.

An experiment compares several algorithms (placement policy + queue discipline) on one scenario over many
replications. Replication r uses seed ``base_seed + r``; its workload trace is generated once and replayed for
every algorithm (common random numbers), which is what makes the paired statistical tests valid.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import platform
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from smartagri_core import __version__
from smartagri_core.progress import ProgressReporter, null_progress
from smartagri_core.registry import PluginKind, get_registry, register
from smartagri_core.sim.engine import SimSettings, simulate
from smartagri_core.sim.metrics import HEADLINE_METRICS, METRIC_INFO, compute_metrics
from smartagri_core.sim.policies import DISCIPLINE_KEYS, PLACEMENT_KEYS
from smartagri_core.sim.runner import ScenarioParams
from smartagri_core.sim.topology import Topology
from smartagri_core.sim.workload import WorkloadSpec, generate_trace
from smartagri_core.stats import ALPHA, compare
from smartagri_core.status import CapabilityStatus, DataOrigin

SPEC_VERSION = 1


class AlgorithmSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(
        None, max_length=60, description="Name shown in results; defaults to placement/discipline"
    )
    placement: PLACEMENT_KEYS
    discipline: DISCIPLINE_KEYS = "fcfs"
    placement_params: dict[str, Any] = Field(default_factory=dict)

    @property
    def display(self) -> str:
        return self.label or f"{self.placement}/{self.discipline}"


class ExperimentSpec(BaseModel):
    """Everything needed to reproduce an experiment. Saved with every result."""

    model_config = ConfigDict(extra="forbid")

    spec_version: int = SPEC_VERSION
    name: str = Field("Untitled experiment", min_length=1, max_length=200)
    description: str = ""
    objective: str = Field("", description="Research question or hypothesis this experiment addresses")
    scenario: ScenarioParams = Field(default_factory=ScenarioParams)
    topology: Topology | None = Field(None, description="A designed topology; replaces the generated farm network")
    workload: WorkloadSpec | None = Field(None, description="A designed workload; replaces the default task mix")
    topology_name: str = ""
    workload_name: str = ""
    algorithms: list[AlgorithmSpec] = Field(min_length=2)
    replications: int = Field(30, ge=2, le=500)
    base_seed: int = Field(1, ge=0)
    metrics: list[str] = Field(default_factory=lambda: list(HEADLINE_METRICS))
    alpha: float = Field(ALPHA, gt=0, lt=0.5, description="Significance level")

    @model_validator(mode="after")
    def _check(self) -> ExperimentSpec:
        labels = [a.display for a in self.algorithms]
        if len(set(labels)) != len(labels):
            raise ValueError("Each algorithm must have a distinct label (or a distinct placement/discipline pair)")
        unknown = [m for m in self.metrics if m not in METRIC_INFO]
        if unknown:
            raise ValueError(f"Unknown metrics: {', '.join(unknown)}")
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()

    def build(self) -> tuple[Topology, WorkloadSpec, SimSettings]:
        """The simulated system: saved topology/workload when given, otherwise the generated scenario."""
        topo, workload, settings = self.scenario.build()
        return self.topology or topo, self.workload or workload, settings

    @property
    def total_runs(self) -> int:
        return self.replications * len(self.algorithms)


def run_experiment(spec: ExperimentSpec, progress: ProgressReporter = null_progress) -> dict[str, Any]:
    reg = get_registry()
    topo, workload, settings = spec.build()
    runs: list[dict[str, Any]] = []
    trace_hashes: list[str] = []
    total = spec.total_runs
    for r in range(spec.replications):
        seed = spec.base_seed + r
        trace = generate_trace(workload, topo, seed)
        trace_hashes.append(trace.sha256)
        for alg in spec.algorithms:
            placement = reg.create(f"placement:{alg.placement}", alg.placement_params)
            discipline = reg.create(f"queue_discipline:{alg.discipline}")
            sim = simulate(topo, trace, placement, discipline, settings, seed=seed)
            metrics = {
                k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in compute_metrics(sim).items()
            }
            runs.append({"replication": r, "seed": seed, "algorithm": alg.display, "metrics": metrics})
            progress(len(runs) / total, f"Run {len(runs)} of {total}: {alg.display}, replication {r + 1}")

    labels = [a.display for a in spec.algorithms]
    analysis: dict[str, Any] = {}
    for metric in METRIC_INFO:
        samples = {lab: [_num(run["metrics"][metric]) for run in runs if run["algorithm"] == lab] for lab in labels}
        analysis[metric] = compare(samples, higher_is_better=METRIC_INFO[metric][2], alpha=spec.alpha)

    return {
        "data_origin": str(DataOrigin.SYNTHETIC),
        "kind": "experiment",
        "spec": spec.model_dump(mode="json"),
        "spec_sha256": spec.sha256,
        "algorithms": labels,
        "metric_info": {k: list(v) for k, v in METRIC_INFO.items()},
        "headline_metrics": spec.metrics,
        "analysis": analysis,
        "runs": runs,
        "provenance": {
            "topology_sha256": topo.sha256,
            "trace_sha256": trace_hashes,
            "core_version": __version__,
            "python": platform.python_version(),
        },
        "summary": {
            "algorithms": len(labels),
            "replications": spec.replications,
            "runs": len(runs),
            "significant_metrics": sum(1 for m in spec.metrics if analysis[m]["significant"]),
        },
    }


@register(
    kind=PluginKind.SIMULATION,
    key="experiment",
    name="Experiment runner",
    version="0.1.0",
    status=CapabilityStatus.IMPLEMENTED,
    summary="Runs a saved experiment: algorithms x replications on identical workloads, with significance tests.",
    description="Used by the Experiments page and the command line (smartagri experiment run spec.yaml).",
    params=ExperimentSpec,
    phase=1,
    tags=["internal", "experiment"],
)
class ExperimentRunner:
    def __init__(self, spec: ExperimentSpec) -> None:
        self.spec = spec

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        return run_experiment(self.spec, progress)


# --- exports -------------------------------------------------------------------------------------


def runs_to_csv(result: dict[str, Any]) -> str:
    """One row per (replication, algorithm) with every metric: ready for R, Python or Excel."""
    metrics = list(result["metric_info"])
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["replication", "seed", "algorithm", *metrics])
    for run in result["runs"]:
        writer.writerow(
            [run["replication"], run["seed"], run["algorithm"], *[_csv(run["metrics"][m]) for m in metrics]]
        )
    return out.getvalue()


def latex_tables(result: dict[str, Any], metrics: list[str] | None = None) -> str:
    """Two booktabs tables: means with 95% CIs, and mean ranks with the omnibus test per metric."""
    metrics = metrics or result["headline_metrics"]
    info = result["metric_info"]
    algs = result["algorithms"]
    spec = result["spec"]
    n = spec["replications"]
    cols = "l" + "r" * len(metrics)

    def head() -> str:
        names = [f"{_tex(info[m][0])}{f' ({_tex(info[m][1])})' if info[m][1] else ''}" for m in metrics]
        return "Algorithm & " + " & ".join(names) + r" \\"

    lines = [
        "% Generated by SmartAgri-Fog. Requires \\usepackage{booktabs}. Data: simulated (synthetic).",
        f"% Experiment: {_tex(spec['name'])}; spec SHA-256 {result['spec_sha256'][:12]}",
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        rf"\caption{{{_tex(spec['name'])}: mean $\pm$ 95\% confidence half-width over {n} replications.}}",
        rf"\begin{{tabular}}{{{cols}}}",
        r"\toprule",
        head(),
        r"\midrule",
    ]
    for a in algs:
        cells = []
        for m in metrics:
            s = result["analysis"][m]["summaries"][a]
            cells.append(f"{_fmt(s['mean'])} $\\pm$ {_fmt(s['half_width'])}")
        lines.append(f"{_tex(a)} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]

    lines += [
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        rf"\caption{{{_tex(spec['name'])}: mean ranks (1 = best) and Friedman test; CD = Nemenyi critical difference "
        rf"($\alpha = {spec['alpha']}$).}}",
        rf"\begin{{tabular}}{{{cols}}}",
        r"\toprule",
        head(),
        r"\midrule",
    ]
    for a in algs:
        cells = [_fmt(result["analysis"][m]["mean_ranks"][a], 2) for m in metrics]
        lines.append(f"{_tex(a)} & " + " & ".join(cells) + r" \\")
    lines.append(r"\midrule")
    lines.append(
        "Friedman $p$ & "
        + " & ".join(_p_tex(result["analysis"][m]["omnibus"].get("p_value")) for m in metrics)
        + r" \\"
    )
    lines.append(
        "CD & "
        + " & ".join(_fmt(result["analysis"][m]["omnibus"].get("critical_difference"), 2) for m in metrics)
        + r" \\"
    )
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    return "\n".join(lines) + "\n"


def _num(v: Any) -> float:
    return math.nan if v is None else float(v)


def _csv(v: Any) -> str:
    return "" if v is None else repr(v) if isinstance(v, float) else str(v)


def _fmt(v: Any, digits: int | None = None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "--"
    if digits is not None:
        return f"{v:.{digits}f}"
    a = abs(v)
    return f"{v:.0f}" if a >= 1000 else f"{v:.1f}" if a >= 100 else f"{v:.2f}" if a >= 1 else f"{v:.3f}"


def _p_tex(p: Any) -> str:
    if p is None:
        return "--"
    return "$<0.001$" if p < 0.001 else f"{p:.3f}"


def _tex(s: str) -> str:
    for a, b in [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
        ("µ", r"$\mu$"),
    ]:
        s = s.replace(a, b)
    return s
