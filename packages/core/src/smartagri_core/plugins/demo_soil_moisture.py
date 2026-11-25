"""Demo soil-moisture signal generator (Phase 0).

A small, honest, runnable plugin used to prove the plumbing end to end: schema-driven forms, job
execution with live progress, and provenance labelling. Its output is SYNTHETIC and the model is a
deliberately simple, uncalibrated illustration. Phase 2 replaces it with an FAO-56 soil-water-balance
model driven by real historical weather.

Model (per time step dt, in days):
    * drying:  theta <- wp + (theta - wp) * exp(-k * dt)        (exponential depletion toward wilting point)
    * rain:    at the start of a day, with probability p, add R ~ U(rain_min, rain_max) mm,
               converted to volumetric water content over the root-zone depth; anything above
               field capacity drains away
    * sensor:  measured = theta + N(0, noise_std), clipped to [0, 1]
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from smartagri_core.progress import ProgressReporter, null_progress
from smartagri_core.registry import PluginKind, register
from smartagri_core.status import CapabilityStatus, DataOrigin


class SoilMoistureDemoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(
        30, ge=1, le=365, description="Length of the generated series.", json_schema_extra={"x-unit": "days"}
    )
    samples_per_day: int = Field(
        24, ge=1, le=288, description="How many sensor readings per day.", json_schema_extra={"x-unit": "readings/day"}
    )
    field_capacity: float = Field(
        0.32,
        gt=0,
        le=0.6,
        description="Volumetric water content the soil holds after drainage.",
        json_schema_extra={"x-unit": "m³/m³"},
    )
    wilting_point: float = Field(
        0.12,
        gt=0,
        lt=0.5,
        description="Water content below which plants cannot extract water.",
        json_schema_extra={"x-unit": "m³/m³"},
    )
    initial_moisture: float = Field(
        0.28, gt=0, le=0.6, description="Water content at the start.", json_schema_extra={"x-unit": "m³/m³"}
    )
    drying_rate: float = Field(
        0.08,
        gt=0,
        le=1.0,
        description="Daily depletion rate of plant-available water (evapotranspiration proxy).",
        json_schema_extra={"x-unit": "1/day", "x-advanced": True},
    )
    rain_probability: float = Field(0.15, ge=0, le=1, description="Chance of a rain event on any day.")
    rain_min_mm: float = Field(
        5.0, ge=0, le=200, description="Smallest rain event.", json_schema_extra={"x-unit": "mm", "x-advanced": True}
    )
    rain_max_mm: float = Field(
        25.0, ge=0, le=300, description="Largest rain event.", json_schema_extra={"x-unit": "mm", "x-advanced": True}
    )
    root_zone_depth_m: float = Field(
        0.3,
        gt=0,
        le=2.0,
        description="Depth of soil the sensor represents.",
        json_schema_extra={"x-unit": "m", "x-advanced": True},
    )
    noise_std: float = Field(
        0.005,
        ge=0,
        le=0.1,
        description="Standard deviation of sensor noise.",
        json_schema_extra={"x-unit": "m³/m³", "x-advanced": True},
    )
    seed: int = Field(42, ge=0, description="Random seed. The same seed always gives the same series.")
    demo_delay_ms: int = Field(
        40,
        ge=0,
        le=2000,
        description="Demo only: pause after each simulated day so live progress is visible.",
        json_schema_extra={"x-unit": "ms", "x-advanced": True},
    )

    @model_validator(mode="after")
    def _check_ranges(self) -> SoilMoistureDemoParams:
        if not self.wilting_point < self.field_capacity:
            raise ValueError("wilting_point must be below field_capacity")
        if not self.wilting_point <= self.initial_moisture <= self.field_capacity:
            raise ValueError("initial_moisture must lie between wilting_point and field_capacity")
        if self.rain_min_mm > self.rain_max_mm:
            raise ValueError("rain_min_mm must not exceed rain_max_mm")
        return self


@register(
    kind=PluginKind.DATA_GENERATOR,
    key="soil_moisture_demo",
    name="Soil-moisture demo signal",
    version="0.1.0",
    status=CapabilityStatus.SIMULATED,
    summary="Generates a synthetic soil-moisture series with drying and random rain, for testing the platform.",
    description=(
        "Uncalibrated illustration used in Phase 0 to exercise forms, jobs and provenance labels. "
        "Replaced in Phase 2 by an FAO-56 soil-water-balance model driven by real weather."
    ),
    params=SoilMoistureDemoParams,
    layers=["edge"],
    agri_applications=["Platform testing", "Irrigation demos"],
    outputs=["Time series of true and measured soil moisture", "Rain events", "Summary statistics"],
    phase=0,
    tags=["demo", "synthetic"],
)
class SoilMoistureDemo:
    data_origin = DataOrigin.SYNTHETIC

    def __init__(self, params: SoilMoistureDemoParams) -> None:
        self.params = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        p = self.params
        rng = np.random.default_rng(p.seed)
        steps_per_day = p.samples_per_day
        dt = 1.0 / steps_per_day
        decay = math.exp(-p.drying_rate * dt)

        theta = p.initial_moisture
        true_values: list[float] = []
        measured: list[float] = []
        hours: list[float] = []
        rain_events: list[dict[str, float]] = []

        for day in range(p.days):
            if rng.random() < p.rain_probability:
                rain_mm = float(rng.uniform(p.rain_min_mm, p.rain_max_mm))
                theta = min(p.field_capacity, theta + rain_mm / 1000.0 / p.root_zone_depth_m)
                rain_events.append({"day": day, "rain_mm": round(rain_mm, 2)})
            for step in range(steps_per_day):
                theta = p.wilting_point + (theta - p.wilting_point) * decay
                reading = theta + rng.normal(0.0, p.noise_std) if p.noise_std > 0 else theta
                true_values.append(round(theta, 5))
                measured.append(round(min(1.0, max(0.0, reading)), 5))
                hours.append(round((day + step * dt) * 24.0, 4))
            progress((day + 1) / p.days, f"Simulated day {day + 1} of {p.days}")
            if p.demo_delay_ms:
                time.sleep(p.demo_delay_ms / 1000.0)

        arr = np.asarray(true_values)
        return {
            "data_origin": str(self.data_origin),
            "plugin": "data_generator:soil_moisture_demo",
            "params": p.model_dump(mode="json"),
            "hours": hours,
            "true_moisture": true_values,
            "measured_moisture": measured,
            "rain_events": rain_events,
            "summary": {
                "n_readings": len(true_values),
                "mean": round(float(arr.mean()), 5),
                "min": round(float(arr.min()), 5),
                "max": round(float(arr.max()), 5),
                "rain_days": len(rain_events),
            },
        }
