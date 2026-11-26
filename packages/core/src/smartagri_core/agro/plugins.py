"""Runnable agronomy experiments."""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from smartagri_core.agro.fao56 import CROPS, SOILS, IrrigationPolicy
from smartagri_core.agro.sensors import STRATEGIES, SensorModel, closed_loop_season
from smartagri_core.agro.weather import synthetic_weather, to_balance_weather
from smartagri_core.progress import ProgressReporter, null_progress
from smartagri_core.registry import PluginKind, register
from smartagri_core.stats import compare, summarize
from smartagri_core.status import CapabilityStatus, DataOrigin

METRICS = {
    "relative_yield": ("Relative yield", "higher", "Yield as a fraction of the water-unlimited potential (FAO-33)"),
    "stress_days": ("Days with water stress", "lower", "Days when the true crop could not transpire fully"),
    "irrigation_gross_mm": ("Irrigation applied (mm)", "lower", "Water pumped, at the field's application efficiency"),
    "deep_percolation_mm": ("Water lost below the roots (mm)", "lower", "Drainage from over-irrigation and rain"),
    "irrigation_events": ("Irrigation events", "lower", "Number of irrigations in the season"),
    "belief_error_mm": ("Depletion error (mm)", "lower", "Mean gap between what the farmer believes and the truth"),
}


class SensorIrrigationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crop: Literal[tuple(CROPS)] = Field("wheat", description="Crop (FAO-56 coefficients).")  # type: ignore[valid-type]
    soil: Literal[tuple(SOILS)] = Field("sandy_loam", description="Soil texture (FAO-56 Table 19).")  # type: ignore[valid-type]
    latitude: float = Field(28.6, ge=-60, le=60, description="Latitude for the synthetic weather and radiation.")
    elevation_m: float = Field(220, ge=0, le=5000, title="Elevation (m)")
    sowing: date = Field(date(2025, 11, 10), description="Sowing date (each season uses this day and month).")
    et_multiplier: float = Field(
        1.2,
        title="True water use / model",
        ge=0.5,
        le=2.0,
        description="How much more (or less) water the real field uses than FAO-56 predicts.",
    )
    noise_sd: float = Field(
        0.02,
        title="Sensor noise (m3/m3)",
        ge=0,
        le=0.1,
        description="Standard deviation of a reading; 0.02 is typical of uncalibrated capacitive probes.",
    )
    bias: float = Field(0.0, title="Sensor bias (m3/m3)", ge=-0.1, le=0.1, json_schema_extra={"x-advanced": True})
    dropout: float = Field(
        0.05, title="Missing readings", ge=0, le=0.9, description="Fraction of evenings without a reading."
    )
    efficiency: float = Field(0.6, title="Application efficiency", gt=0, le=1, json_schema_extra={"x-advanced": True})
    seasons: int = Field(
        30, ge=2, le=500, description="Seasons with different synthetic weather (paired across strategies)."
    )
    base_seed: int = Field(1, title="First seed", ge=0)
    process_cv: float = Field(
        0.25,
        title="Model uncertainty per day",
        ge=0.01,
        le=2,
        json_schema_extra={"x-advanced": True},
        description="Kalman filter: assumed daily error of the model, as a fraction of crop water use.",
    )
    strategies: list[Literal["model", "sensor", "fused", "oracle"]] = Field(
        default_factory=lambda: ["model", "sensor", "fused", "oracle"],
        min_length=2,
        description="Decision strategies to compare.",
    )


@register(
    kind=PluginKind.SIMULATION,
    key="sensor_irrigation",
    name="Experiment: model-only vs sensor-assisted irrigation",
    version="1.0.0",
    status=CapabilityStatus.IMPLEMENTED,
    summary="Closed-loop seasons: irrigation decided from the FAO-56 model, a soil-moisture sensor, or both.",
    description=(
        "Simulates many seasons on a field whose true water use differs from the FAO-56 model. The farmer "
        "irrigates from a belief (model only, sensor-corrected, or the truth); yield, stress, water applied and "
        "drainage are measured on the true field and compared with Friedman and Holm-corrected Wilcoxon tests."
    ),
    params=SensorIrrigationParams,
    layers=["iot", "edge"],
    outputs=["Per-strategy outcomes with 95% CIs", "Significance tests"],
    metrics=list(METRICS),
    phase=2,
    tags=["irrigation", "sensors", "experiment", "fao-56"],
)
class SensorIrrigationExperiment:
    def __init__(self, params: SensorIrrigationParams) -> None:
        self.p = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        p = self.p
        crop, soil = CROPS[p.crop], SOILS[p.soil]
        model = SensorModel(noise_sd=p.noise_sd, bias=p.bias, dropout=p.dropout, et_multiplier=p.et_multiplier)
        policy = IrrigationPolicy(efficiency=p.efficiency)
        samples: dict[str, dict[str, list[float]]] = {m: {s: [] for s in p.strategies} for m in METRICS}
        for k in range(p.seasons):
            seed = p.base_seed + k
            sowing = (
                p.sowing.replace(year=p.sowing.year + k)
                if not (p.sowing.month == 2 and p.sowing.day == 29)
                else p.sowing
            )
            end = date.fromordinal(sowing.toordinal() + crop.season_days)
            weather = to_balance_weather(
                synthetic_weather(p.latitude, sowing, end, seed=seed), p.latitude, p.elevation_m
            )
            for s in p.strategies:
                out = closed_loop_season(
                    weather, crop, soil, sowing, crop.root_depth_m, policy, model, s, key=f"season{seed}"
                )
                for m, v in out.items():
                    samples[m][s].append(v)
            progress((k + 1) / p.seasons, f"Season {k + 1} of {p.seasons}")
        metrics = {m: v for m, v in METRICS.items() if not any(math.isnan(x) for xs in samples[m].values() for x in xs)}
        clean = lambda d: {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in d.items()}  # noqa: E731
        return {
            "data_origin": str(DataOrigin.SYNTHETIC),
            "kind": "simulation.strategy_comparison",
            "title": "Model-only vs sensor-assisted irrigation",
            "description": (
                f"{p.seasons} seasons of {crop.name.lower()} on {soil.name.lower()} with synthetic weather at latitude "
                f"{p.latitude}. The true field uses {p.et_multiplier:.2f} times the FAO-56 water requirement; "
                "the sensor "
                f"has noise {p.noise_sd} m3/m3 and misses {p.dropout:.0%} of evenings. Every strategy faced the same "
                "seasons. Outcomes are measured on the true field."
            ),
            "params": p.model_dump(mode="json"),
            "labels": {s: STRATEGIES[s] for s in p.strategies},
            "metric_info": {k: list(v) for k, v in metrics.items()},
            "summary": {m: {s: clean(summarize(v)) for s, v in samples[m].items()} for m in metrics},
            "tests": {m: compare(samples[m], higher_is_better=METRICS[m][1] == "higher") for m in metrics},
            "highlight": ["relative_yield", "irrigation_gross_mm"],
            "samples": {m: samples[m] for m in metrics},
        }
