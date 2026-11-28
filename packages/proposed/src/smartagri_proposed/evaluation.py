"""AURA evaluation: AURA, its ablations and the baselines on every stress scenario, with statistics.

For each scenario and replication one workload trace is generated (seed = base_seed + replication) and every
algorithm runs on that same trace. Results per scenario are compared with many-to-one paired Wilcoxon tests
(AURA against each other algorithm, Holm-corrected) and Vargha-Delaney A12. The four hypotheses of the design
(H1 to H4) are then checked mechanically against those tests, and each verdict lists its evidence.
"""

from __future__ import annotations

import math
import time
from typing import Any

from pydantic import Field, field_validator
from smartagri_core.progress import ProgressReporter, null_progress
from smartagri_core.registry import PluginKind, PluginNotFoundError, get_registry, register
from smartagri_core.sim.engine import simulate
from smartagri_core.sim.metrics import METRIC_INFO, compute_metrics
from smartagri_core.sim.runner import ScenarioParams, _environment
from smartagri_core.sim.scenarios import STRESS_INFO, StressKey
from smartagri_core.sim.workload import generate_trace
from smartagri_core.stats import compare_to_reference, summarize
from smartagri_core.status import CapabilityStatus, DataOrigin

from smartagri_proposed.aura import ABLATIONS, REFERENCE, SOURCE

BASELINE_NAMES = {
    "mct": "MCT",
    "edge_ward": "Edge-ward",
    "cloud_only": "Cloud-only",
    "least_loaded": "Least loaded",
    "min_min": "Min-Min (batch)",
    "nsga2": "NSGA-II (batch)",
    "round_robin": "Round Robin",
    "random": "Random",
    "max_min": "Max-Min (batch)",
    "ga": "GA (batch)",
    "pso": "PSO (batch)",
    "aco": "ACO (batch)",
    "dqn": "DQN (learned)",
}
DEFAULT_ALGORITHMS = [
    "aura",
    "aura_noaoi",
    "aura_noreserve",
    "aura_staticreserve",
    "aura_noreliability",
    "aura_singletier",
    "mct",
    "mct@aura",
    "edge_ward",
    "cloud_only",
    "least_loaded",
    "min_min",
    "nsga2",
]
METRICS = {  # metric -> higher is better
    "urgent_deadline_success_rate": True,
    "effective_deadline_success_rate": True,
    "aoi_violation_rate": False,
    "decision_value_pct": True,
    "p95_response_s": False,
    "energy_dynamic_j": False,
    "cost": False,
    "autonomy_ratio": True,
    "deadline_success_rate": True,
    "scheduling_overhead_us": False,
}
BURST = ["monsoon_burst", "heat_wave"]
STRESSED = ["monsoon_burst", "heat_wave", "cloud_disconnection", "fog_failure"]


def parse(entry: str) -> tuple[str, str]:
    """'placement' or 'placement@discipline' -> (placement, discipline) with AURA's defaults."""
    if "@" in entry:
        placement, discipline = entry.split("@", 1)
        return placement, discipline
    if entry == "aura_noaoi":
        return entry, "urgent_edf"
    if entry.startswith("aura"):
        return entry, "aura"
    return entry, "edf"


def label(entry: str) -> str:
    placement, discipline = parse(entry)
    base = ABLATIONS[placement][0] if placement in ABLATIONS else BASELINE_NAMES.get(placement, placement)
    return f"{base} + AURA queue" if "@" in entry and discipline == "aura" else base


class AuraEvaluationParams(ScenarioParams):
    stress: StressKey = Field(
        "normal",
        title="Scenario (single runs only)",
        description="Not used here: the evaluation runs every scenario in the list below.",
        json_schema_extra={"x-advanced": True},
    )
    duration_s: float = Field(
        title="Duration",
        default=1800.0,
        ge=60,
        le=7 * 86400,
        description="Simulated time per run.",
        json_schema_extra={"x-unit": "s"},
    )
    intensity: float = Field(100.0, gt=0, le=200, description="Workload multiplier (100 = busy season).")
    scenarios: list[StressKey] = Field(
        default_factory=lambda: ["normal", "monsoon_burst", "heat_wave", "cloud_disconnection", "fog_failure"],
        min_length=1,
        description="Scenarios to evaluate (see docs/scenarios.md).",
    )
    algorithms: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ALGORITHMS),
        min_length=2,
        description="Placements, optionally with a queue discipline as placement@discipline. Must include aura.",
    )
    replications: int = Field(5, ge=2, le=100, description="Seeded workloads per scenario (30 for a paper).")
    base_seed: int = Field(1, title="Seed", ge=0)

    @field_validator("algorithms")
    @classmethod
    def _check(cls, v: list[str]) -> list[str]:
        if "aura" not in v:
            raise ValueError("The evaluation compares everything with AURA, so 'aura' must be included")
        if len(set(v)) != len(v):
            raise ValueError("Each algorithm may appear only once")
        reg = get_registry()
        reg.ensure_loaded()
        for entry in v:
            placement, discipline = parse(entry)
            for kind, key in (("placement", placement), ("queue_discipline", discipline)):
                try:
                    spec = reg.get(f"{kind}:{key}")
                except (KeyError, PluginNotFoundError):
                    spec = None
                if spec is None or not spec.runnable:
                    raise ValueError(f"Unknown or unavailable {kind.replace('_', ' ')}: {key}")
        return v


def _verdict(wins: int, ties: int, losses: int) -> str:
    """Per-scenario verdict from significant wins, non-significant comparisons and significant losses."""
    if losses:
        return "not supported"
    if wins and ties == 0:
        return "supported"
    if wins:
        return "partly supported"
    return "inconclusive"  # no significant difference either way (often too few replications)


@register(
    kind=PluginKind.SIMULATION,
    key="aura_evaluation",
    name="AURA evaluation (scenarios, ablations, baselines)",
    version="1.0.0",
    status=CapabilityStatus.IMPLEMENTED,
    source=SOURCE,
    summary="Runs AURA, its five ablations and the baselines on every stress scenario, and checks hypotheses H1-H4.",
    description=(
        "Identical seeded workloads for every algorithm. Many-to-one Wilcoxon tests (Holm-corrected) with A12 "
        "per scenario and metric. Also records AURA's reservation timeline and example decision explanations."
    ),
    references=[REFERENCE],
    params=AuraEvaluationParams,
    layers=["edge", "fog", "cloud"],
    outputs=["Per-scenario results with 95% CIs", "Tests against AURA", "Hypothesis verdicts", "Reservation timeline"],
    tags=["proposed", "simulation", "experiment"],
    phase=4,
)
class AuraEvaluation:
    def __init__(self, params: AuraEvaluationParams) -> None:
        self.p = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        p = self.p
        reg = get_registry()
        reg.ensure_loaded()
        names = {a: label(a) for a in p.algorithms}
        samples: dict[str, dict[str, dict[str, list[float]]]] = {}
        logs: dict[str, Any] = {}
        events: dict[str, Any] = {}
        runtime: dict[str, list[float]] = {a: [] for a in p.algorithms}
        total = len(p.scenarios) * p.replications * len(p.algorithms)
        done = 0
        for sc in p.scenarios:
            sp = ScenarioParams(**(p.model_dump(include=set(ScenarioParams.model_fields)) | {"stress": sc}))
            topo, spec, settings = sp.build()
            events[sc] = sp.scenario_events()
            samples[sc] = {a: {m: [] for m in METRIC_INFO} for a in p.algorithms}
            for r in range(p.replications):
                seed = p.base_seed + r
                trace = generate_trace(spec, topo, seed)
                if r == 0:
                    events[sc] = {
                        "events": events[sc],
                        "warnings": len(trace.signals),
                        "true_warnings": sum(1 for s in trace.signals if s.true),
                        "tasks": len(trace.tasks),
                    }
                for a in p.algorithms:
                    placement_key, discipline = parse(a)
                    extra = {"episode_s": p.duration_s, "episodes": 20} if placement_key == "dqn" else {}
                    placement = reg.create(f"placement:{placement_key}", extra)
                    t0 = time.perf_counter()
                    sim = simulate(
                        topo, trace, placement, reg.create(f"queue_discipline:{discipline}"), settings, seed=seed
                    )
                    runtime[a].append(time.perf_counter() - t0)
                    for m, v in compute_metrics(sim).items():
                        samples[sc][a][m].append(float(v) if v is not None else math.nan)
                    if a == "aura" and r == 0 and hasattr(placement, "log"):
                        logs[sc] = placement.log
                    done += 1
                    progress(done / total, f"{STRESS_INFO[sc][0]}: replication {r + 1}, {names[a]}")

        table = {
            sc: {a: {m: summarize(samples[sc][a][m]) for m in METRICS} for a in p.algorithms} for sc in p.scenarios
        }
        tests = {
            sc: {
                m: compare_to_reference({names[a]: samples[sc][a][m] for a in p.algorithms}, names["aura"], hib)
                for m, hib in METRICS.items()
            }
            for sc in p.scenarios
        }
        hypotheses = self._hypotheses(tests, names, table)
        return _finite(
            {
                "data_origin": str(DataOrigin.SYNTHETIC),
                "kind": "simulation.aura_evaluation",
                "params": p.model_dump(mode="json"),
                "scenario_info": {k: list(STRESS_INFO[k]) for k in p.scenarios},
                "events": events,
                "algorithms": p.algorithms,
                "names": names,
                "metrics": list(METRICS),
                "metric_info": {k: list(METRIC_INFO[k]) for k in METRICS},
                "table": table,
                "tests": tests,
                "hypotheses": hypotheses,
                "aura_logs": logs,
                "runtime_s": {a: summarize(v) for a, v in runtime.items()},
                "provenance": _environment(),
                "summary": {
                    "scenarios": len(p.scenarios),
                    "algorithms": len(p.algorithms),
                    "replications": p.replications,
                    "runs": total,
                    "hypotheses": {h["id"]: h["verdict"] for h in hypotheses},
                },
            }
        )

    def _hypotheses(self, tests, names, table) -> list[dict[str, Any]]:
        p = self.p
        baselines = [names[a] for a in p.algorithms if not parse(a)[0].startswith("aura")]
        out: list[dict[str, Any]] = []

        def outcomes(sc: str, metric: str, against: list[str]) -> list[dict[str, Any]]:
            return [r for r in tests[sc][metric]["rows"] if r["other"] in against]

        # H1: urgent deadlines and freshness under burst and failure scenarios.
        evidence, verdicts = [], []
        for sc in [s for s in STRESSED if s in p.scenarios]:
            rows = outcomes(sc, "urgent_deadline_success_rate", baselines) + outcomes(
                sc, "aoi_violation_rate", baselines
            )
            w = sum(r["outcome"] == "better" for r in rows)
            t = sum(r["outcome"] == "no significant difference" for r in rows)
            losses = [
                f"{r['other']} ({'urgent deadlines' if i < len(rows) // 2 else 'stale decisions'})"
                for i, r in enumerate(rows)
                if r["outcome"] == "worse"
            ]
            v = _verdict(w, t, len(losses))
            verdicts.append(v)
            evidence.append({"scenario": sc, "wins": w, "ties": t, "losses": losses, "verdict": v})
        out.append(
            self._h(
                "H1",
                "AURA raises urgent deadline success and freshness compliance over the baselines "
                "under burst and failure scenarios.",
                verdicts,
                evidence,
                "Counts of baselines AURA is significantly better than, not different from, or worse "
                "than, on urgent deadlines met and on stale decisions.",
            )
        )
        if not baselines:
            out[-1]["verdict"] = "not tested"

        # H2: anticipatory beats static reservation during surges.
        static = names.get("aura_staticreserve")
        evidence, verdicts = [], []
        if static:
            for sc in [s for s in BURST if s in p.scenarios]:
                rows = outcomes(sc, "urgent_deadline_success_rate", [static]) + outcomes(
                    sc, "decision_value_pct", [static]
                )
                w = sum(r["outcome"] == "better" for r in rows)
                t = sum(r["outcome"] == "no significant difference" for r in rows)
                losses = [r["other"] for r in rows if r["outcome"] == "worse"]
                v = _verdict(w, t, len(losses))
                verdicts.append(v)
                evidence.append({"scenario": sc, "rows": rows, "verdict": v})
        out.append(
            self._h(
                "H2",
                "Anticipatory reservation beats static reservation during surges.",
                verdicts,
                evidence,
                "AURA against AURA with static reservation, on urgent deadlines met and decision value.",
            )
        )

        # H3: autonomy under cloud disconnection.
        evidence, verdicts = [], []
        if "cloud_disconnection" in p.scenarios and baselines:
            rows = outcomes("cloud_disconnection", "autonomy_ratio", baselines)
            w = sum(r["outcome"] == "better" for r in rows)
            t = sum(r["outcome"] == "no significant difference" for r in rows)
            losses = [r["other"] for r in rows if r["outcome"] == "worse"]
            v = _verdict(w, t, len(losses))
            verdicts.append(v)
            evidence.append({"scenario": "cloud_disconnection", "rows": rows, "verdict": v})
        out.append(
            self._h(
                "H3",
                "Under cloud disconnection AURA completes more urgent work locally (autonomy ratio).",
                verdicts,
                evidence,
                "AURA against each baseline on the autonomy ratio.",
            )
        )

        # H4: the strategic tier lowers energy and cost without hurting urgent metrics.
        refs = [names[a] for a in ("aura_singletier", "edge_ward") if a in names]
        evidence, verdicts = [], []
        for sc in p.scenarios:
            if not refs:
                break
            rows = outcomes(sc, "energy_dynamic_j", refs) + outcomes(sc, "cost", refs)
            urgent = outcomes(sc, "urgent_deadline_success_rate", refs)
            w = sum(r["outcome"] == "better" for r in rows)
            t = sum(r["outcome"] == "no significant difference" for r in rows)
            losses = [r["other"] for r in rows if r["outcome"] == "worse"]
            losses += [f"{r['other']} (urgent deadlines)" for r in urgent if r["outcome"] == "worse"]
            v = _verdict(w, t, len(losses))
            verdicts.append(v)
            evidence.append({"scenario": sc, "wins": w, "ties": t, "losses": losses, "verdict": v})
        out.append(
            self._h(
                "H4",
                "The strategic tier lowers energy and cost compared with single-tier AURA and edge-ward "
                "placement without hurting urgent deadlines.",
                verdicts,
                evidence,
                "AURA against single-tier AURA and edge-ward on energy and cloud cost, and on urgent "
                "deadlines met (which must not be worse).",
            )
        )
        return out

    @staticmethod
    def _h(hid: str, text: str, verdicts: list[str], evidence: list, how: str) -> dict[str, Any]:
        if not verdicts:
            overall = "not tested"
        elif len(set(verdicts)) == 1:
            overall = verdicts[0]
        else:
            overall = "mixed"
        return {"id": hid, "statement": text, "verdict": overall, "how": how, "evidence": evidence}


def _finite(x: Any) -> Any:
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_finite(v) for v in x]
    return x
