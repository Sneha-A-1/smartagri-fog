"""The retrieval-framework evaluation experiment."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field

from smartagri_core.progress import ProgressReporter, null_progress
from smartagri_core.registry import PluginKind, register
from smartagri_core.retrieval.evaluate import ARCHITECTURES, ArchitectureSettings, evaluate, run_architecture
from smartagri_core.retrieval.framework import RetrievalConfig
from smartagri_core.retrieval.scenario import ScenarioParams, generate
from smartagri_core.stats import compare, summarize
from smartagri_core.status import CapabilityStatus, DataOrigin

METRICS = {
    "f1": ("Alert F1 score", "higher", "Harmonic mean of alert precision and event recall"),
    "precision": ("Alert precision", "higher", "Share of alerts that correspond to a real event"),
    "recall": ("Event recall", "higher", "Share of real stress, frost and heat events alerted"),
    "false_alarms_per_day": ("False alarms per day", "lower", "Alerts with no real event nearby"),
    "time_to_detect_min": ("Time to detect frost and heat (min)", "lower", "Decision time minus true onset"),
    "early_warning_share": ("Events with an early warning", "higher", "Share of events predicted before onset"),
    "fault_recall": ("Stuck sensors detected", "higher", "Share of stuck-sensor episodes flagged"),
    "urgent_aoi_min": ("Age of data at the scheduler (min)", "lower", "Urgent tasks: arrival minus newest sample time"),
    "transmitted_share": ("Readings transmitted", "lower", "Share of raw readings sent upstream"),
    "soil_rmse": ("Soil reconstruction error (m3/m3)", "lower", "RMSE of the transmitted soil series vs the truth"),
}


class RetrievalEvaluationParams(ScenarioParams):
    architectures: list[Literal["cloud_raw", "cloud_periodic", "edge_sod", "edge_drf"]] = Field(
        default_factory=lambda: list(ARCHITECTURES), min_length=2, description="Architectures to compare."
    )
    replications: int = Field(
        10, ge=2, le=200, description="Scenarios with different seeds (paired across architectures)."
    )
    upload_min: float = Field(15, title="Cloud upload interval (min)", gt=0, le=1440)
    duty_factor: int = Field(
        4, title="Duty cycle (keep 1 reading in N)", ge=2, le=96, json_schema_extra={"x-advanced": True}
    )
    persistence: int = Field(2, ge=1, le=20, description="Framework: consecutive readings needed for an alert.")
    soil_smoothing_min: float = Field(
        60, title="Soil smoothing window (min)", ge=0, le=1440, json_schema_extra={"x-advanced": True}
    )
    soil_deadband: float = Field(
        0.01, title="Soil dead band (m3/m3)", ge=0, le=0.2, json_schema_extra={"x-advanced": True}
    )
    horizon_min: float = Field(
        360, title="Early-warning horizon (min)", gt=0, le=4320, json_schema_extra={"x-advanced": True}
    )


@register(
    kind=PluginKind.SIMULATION,
    key="retrieval_evaluation",
    name="Experiment: data retrieval architectures",
    version="1.0.0",
    status=CapabilityStatus.IMPLEMENTED,
    summary="Cloud-centric vs edge retrieval on scenarios with known events and sensor faults.",
    description=(
        "Generates seeded farm scenarios (soil-moisture probes and a weather station, with stress, frost and heat "
        "events, noise, spikes, stuck sensors and missing readings) and compares cloud batch upload, duty-cycled "
        "sensing, a send-on-delta gateway and the full data retrieval framework on detection accuracy, time to "
        "detect, early warning, Age of Information and data volume."
    ),
    params=RetrievalEvaluationParams,
    layers=["iot", "edge", "cloud"],
    outputs=["Per-architecture metrics with 95% CIs", "Significance tests"],
    metrics=list(METRICS),
    phase=3,
    tags=["retrieval", "edge", "experiment", "aoi"],
)
class RetrievalEvaluation:
    def __init__(self, params: RetrievalEvaluationParams) -> None:
        self.p = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        p = self.p
        base = RetrievalConfig()
        base = base.model_copy(
            update={
                "persistence": p.persistence,
                "horizon_min": p.horizon_min,
                "smooth_min": base.smooth_min | {"soil_moisture_m3m3": p.soil_smoothing_min},
                "deadband": base.deadband | {"soil_moisture_m3m3": p.soil_deadband},
            }
        )
        settings = ArchitectureSettings(upload_min=p.upload_min, duty_factor=p.duty_factor)
        scenario_fields = set(ScenarioParams.model_fields)
        samples: dict[str, dict[str, list[float]]] = {m: {a: [] for a in p.architectures} for m in METRICS}
        events = []
        for k in range(p.replications):
            scn = generate(ScenarioParams(**(p.model_dump(include=scenario_fields) | {"seed": p.seed + k})))
            events.append(len([e for e in scn.events if e.name != "stuck"]))
            for a in p.architectures:
                results, tasks = run_architecture(scn, a, base, settings)
                m = evaluate(scn, results, tasks, settings)
                for key in METRICS:
                    samples[key][a].append(m[key])
            progress((k + 1) / p.replications, f"Scenario {k + 1} of {p.replications}")
        usable = {m: v for m, v in METRICS.items() if not any(math.isnan(x) for xs in samples[m].values() for x in xs)}
        clean = lambda d: {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in d.items()}  # noqa: E731
        return {
            "data_origin": str(DataOrigin.SYNTHETIC),
            "kind": "simulation.strategy_comparison",
            "title": "Data retrieval architectures",
            "description": (
                f"{p.replications} synthetic scenarios of {p.days} days: {p.fields} soil-moisture probes and a weather "
                f"station read every {p.interval_min} min, about {sum(events) / len(events):.0f} stress, frost and "
                "heat "
                f"events each, with noise, spikes ({p.spike_prob:.1%}), stuck sensors and {p.dropout:.0%} missing "
                f"readings. Cloud uploads every {p.upload_min:g} min. Every architecture saw the same scenarios."
            ),
            "params": p.model_dump(mode="json"),
            "labels": {a: ARCHITECTURES[a] for a in p.architectures},
            "metric_info": {k: list(v) for k, v in usable.items()},
            "summary": {m: {a: clean(summarize(v)) for a, v in samples[m].items()} for m in usable},
            "tests": {m: compare(samples[m], higher_is_better=METRICS[m][1] == "higher") for m in usable},
            "highlight": ["f1", "transmitted_share"],
            "samples": {m: samples[m] for m in usable},
        }
