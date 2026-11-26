"""Runnable plugins for task-graph scheduling."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from smartagri_core.progress import ProgressReporter, null_progress
from smartagri_core.registry import PluginKind, register
from smartagri_core.sched.dag import (
    Platform,
    Workflow,
    check_schedule,
    cpop,
    heft,
    random_schedule,
    random_workflow,
    schedule_metrics,
    schedule_to_dict,
    topcuoglu_example,
    upward_ranks,
)
from smartagri_core.stats import compare, summarize
from smartagri_core.status import CapabilityStatus, DataOrigin

REFERENCE = (
    "H. Topcuoglu, S. Hariri, M.-Y. Wu. Performance-effective and low-complexity task scheduling for "
    "heterogeneous computing. IEEE TPDS 13(3):260-274, 2002."
)


class GraphParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: int = Field(50, ge=2, le=1000, description="Number of tasks in each random graph.")
    processors: int = Field(4, ge=1, le=64, description="Number of heterogeneous processors.")
    ccr: float = Field(
        1.0,
        title="Communication to computation ratio",
        ge=0,
        le=20,
        description="Above 1, moving data costs more than computing on it.",
    )
    beta: float = Field(
        0.5,
        title="Heterogeneity (beta)",
        ge=0,
        le=2,
        description="How much a task's run time differs between processors (0 = identical).",
    )
    alpha: float = Field(
        1.0,
        title="Shape (alpha)",
        ge=0.1,
        le=10,
        json_schema_extra={"x-advanced": True},
        description="Below 1: long, thin graphs. Above 1: short, wide graphs with more parallelism.",
    )
    out_degree: int = Field(3, ge=1, le=20, json_schema_extra={"x-advanced": True}, description="Successors per task.")
    mean_cost: float = Field(
        50.0, title="Mean task run time", gt=0, json_schema_extra={"x-advanced": True, "x-unit": "time units"}
    )


class ScheduleParams(GraphParams):
    workflow: Literal["paper_example", "random"] = Field(
        "paper_example", description="The 10-task example from the HEFT paper, or a random graph."
    )
    seed: int = Field(1, ge=0, description="Seed for the random graph.")


def _build(p: ScheduleParams) -> tuple[Workflow, Platform]:
    if p.workflow == "paper_example":
        wf = topcuoglu_example()
    else:
        wf = random_workflow(
            p.tasks,
            p.processors,
            alpha=p.alpha,
            out_degree=p.out_degree,
            ccr=p.ccr,
            beta=p.beta,
            mean_cost=p.mean_cost,
            seed=p.seed,
        )
    return wf, Platform(tuple(f"P{k + 1}" for k in range(wf.p)))


def _schedule_result(algorithm: str, p: ScheduleParams) -> dict[str, Any]:
    wf, plat = _build(p)
    fn = {"heft": heft, "cpop": cpop}[algorithm]
    sched = fn(wf, plat)
    check_schedule(wf, plat, sched)
    others = {
        name: schedule_metrics(wf, f(wf, plat)) for name, f in (("heft", heft), ("cpop", cpop)) if name != algorithm
    }
    others["random"] = schedule_metrics(wf, random_schedule(wf, plat, seed=p.seed))
    return {
        "data_origin": str(DataOrigin.SYNTHETIC),
        "kind": "scheduler.dag_schedule",
        "params": p.model_dump(mode="json"),
        "workflow": {"name": wf.name, "tasks": wf.n, "edges": len(wf.edges), "processors": list(plat.names)},
        "reference": REFERENCE,
        "schedule": schedule_to_dict(wf, plat, sched),
        "ranks": {wf.name_of(i): r for i, r in enumerate(upward_ranks(wf, plat))},
        "for_comparison": others,
        "note": "Paper example: the published schedule lengths are 80 (HEFT) and 86 (CPOP)."
        if p.workflow == "paper_example"
        else None,
    }


_COMMON = dict(layers=["edge", "fog", "cloud"], phase=4, metrics=["makespan", "slr", "speedup", "efficiency"])


@register(
    kind=PluginKind.SCHEDULER,
    key="heft",
    name="HEFT",
    version="1.0.0",
    status=CapabilityStatus.IMPLEMENTED,
    summary="Heterogeneous Earliest Finish Time list scheduling for task DAGs.",
    description="Orders tasks by upward rank and puts each on the processor where it finishes earliest, "
    "using idle gaps (insertion). Validated against the worked example of Topcuoglu et al. (2002).",
    params=ScheduleParams,
    outputs=["Schedule (Gantt)", "Makespan, SLR, speedup"],
    tags=["scheduling", "dag"],
    **_COMMON,
)
class HeftPlugin:
    def __init__(self, params: ScheduleParams) -> None:
        self.p = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        return _schedule_result("heft", self.p)


@register(
    kind=PluginKind.SCHEDULER,
    key="cpop",
    name="CPOP",
    version="1.0.0",
    status=CapabilityStatus.IMPLEMENTED,
    summary="Critical-Path-on-a-Processor list scheduling for task DAGs.",
    description="Puts every task of the critical path on the single processor that runs them fastest; other "
    "tasks go where they finish earliest. From the same paper as HEFT, used as a baseline.",
    params=ScheduleParams,
    outputs=["Schedule (Gantt)", "Makespan, SLR, speedup"],
    tags=["scheduling", "dag"],
    **_COMMON,
)
class CpopPlugin:
    def __init__(self, params: ScheduleParams) -> None:
        self.p = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        return _schedule_result("cpop", self.p)


class DagComparisonParams(GraphParams):
    algorithms: list[Literal["heft", "cpop", "random"]] = Field(
        default_factory=lambda: ["heft", "cpop", "random"], min_length=2, description="Schedulers to compare."
    )
    graphs: int = Field(30, ge=2, le=1000, description="Random graphs; every algorithm schedules the same ones.")
    base_seed: int = Field(1, title="First seed", ge=0, description="Graph g uses seed base_seed + g.")


METRIC_INFO = {
    "slr": ("Schedule length ratio", "lower", "Makespan divided by the critical path at the fastest speeds"),
    "speedup": ("Speedup", "higher", "Best single-processor time divided by makespan"),
    "makespan": ("Makespan", "lower", "Time until the last task finishes"),
    "efficiency": ("Efficiency", "higher", "Speedup per processor"),
}


@register(
    kind=PluginKind.SIMULATION,
    key="dag_comparison",
    name="Experiment: compare DAG schedulers",
    version="1.0.0",
    status=CapabilityStatus.IMPLEMENTED,
    summary="Schedules the same random task graphs with HEFT, CPOP and a random baseline, with significance tests.",
    description="Generates task graphs with the random generator of Topcuoglu et al. (2002), schedules every "
    "graph with every algorithm, and compares SLR, speedup, makespan and efficiency using Friedman, "
    "Holm-corrected Wilcoxon tests and A12 effect sizes.",
    params=DagComparisonParams,
    layers=["edge", "fog", "cloud"],
    phase=4,
    outputs=["Per-algorithm metrics with 95% CIs", "Significance tests"],
    metrics=list(METRIC_INFO),
    tags=["scheduling", "dag", "experiment"],
)
class DagComparison:
    def __init__(self, params: DagComparisonParams) -> None:
        self.p = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        p = self.p
        samples: dict[str, dict[str, list[float]]] = {m: {a: [] for a in p.algorithms} for m in METRIC_INFO}
        for g in range(p.graphs):
            seed = p.base_seed + g
            wf = random_workflow(
                p.tasks,
                p.processors,
                alpha=p.alpha,
                out_degree=p.out_degree,
                ccr=p.ccr,
                beta=p.beta,
                mean_cost=p.mean_cost,
                seed=seed,
            )
            plat = Platform(tuple(f"P{k + 1}" for k in range(p.processors)))
            for a in p.algorithms:
                sched = random_schedule(wf, plat, seed) if a == "random" else {"heft": heft, "cpop": cpop}[a](wf, plat)
                check_schedule(wf, plat, sched)
                for m, v in schedule_metrics(wf, sched).items():
                    samples[m][a].append(v)
            progress((g + 1) / p.graphs, f"Graph {g + 1} of {p.graphs}")
        clean = lambda d: {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in d.items()}  # noqa: E731
        return {
            "data_origin": str(DataOrigin.SYNTHETIC),
            "kind": "simulation.dag_comparison",
            "params": p.model_dump(mode="json"),
            "reference": REFERENCE,
            "metric_info": {k: list(v) for k, v in METRIC_INFO.items()},
            "summary": {m: {a: clean(summarize(v)) for a, v in by_alg.items()} for m, by_alg in samples.items()},
            "tests": {
                m: compare(by_alg, higher_is_better=METRIC_INFO[m][1] == "higher") for m, by_alg in samples.items()
            },
            "samples": samples,
        }
