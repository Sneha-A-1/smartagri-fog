"""Workload model: agricultural task classes and frozen, seeded task traces.

A trace is generated once from (spec, topology, seed) and then replayed unchanged for every algorithm,
so differences between algorithms are never caused by different random workloads.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from smartagri_core.sim.topology import Layer, Topology

Priority = Literal["critical", "high", "medium", "low"]
PRIORITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}
URGENT = {"critical", "high"}


class TaskClass(BaseModel):
    """One kind of agricultural computing task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    category: str = "general"
    priority: Priority = "medium"
    rate_per_source_per_h: float = Field(60.0, ge=0, description="Mean arrivals per gateway per hour (Poisson)")
    length_mi: float = Field(1000.0, gt=0, description="Mean processing length in million instructions")
    length_dist: Literal["fixed", "exponential", "uniform"] = "fixed"
    length_spread: float = Field(0.2, ge=0, le=1, description="Half-width of the uniform distribution, as a fraction")
    input_kb: float = Field(1.0, ge=0)
    output_kb: float = Field(0.5, ge=0)
    ram_mb: float = Field(64.0, ge=0)
    deadline_s: float = Field(10.0, gt=0, description="Maximum acceptable response time")
    result_to: Literal["source", "none"] = Field("source", description="Where the result goes (actuator at source)")


class WorkloadSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = "workload"
    duration_s: float = Field(3600.0, gt=0)
    intensity: float = Field(1.0, gt=0, description="Multiplies every arrival rate")
    classes: tuple[TaskClass, ...]
    sources: tuple[str, ...] | None = Field(None, description="Gateway ids; default: every IoT-layer node")


@dataclass(frozen=True, slots=True)
class Task:
    id: int
    cls: str
    category: str
    priority: str
    source: str
    arrival_s: float
    length_mi: float
    input_bytes: float
    output_bytes: float
    ram_mb: float
    deadline_s: float
    result_to_source: bool

    @property
    def urgent(self) -> bool:
        return self.priority in URGENT

    @property
    def abs_deadline(self) -> float:
        return self.arrival_s + self.deadline_s


@dataclass(frozen=True)
class Trace:
    spec_name: str
    seed: int
    tasks: tuple[Task, ...]

    @property
    def sha256(self) -> str:
        payload = json.dumps([asdict(t) for t in self.tasks], sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()


def generate_trace(spec: WorkloadSpec, topology: Topology, seed: int) -> Trace:
    """Poisson arrivals per (gateway, task class), merged and sorted by time. Deterministic for a seed."""
    sources = list(spec.sources) if spec.sources else [n.id for n in topology.by_layer(Layer.IOT)]
    if not sources:
        raise ValueError("The topology has no IoT gateways to generate tasks from")
    rng = np.random.default_rng(np.random.SeedSequence([seed, 0xA6]))
    raw: list[tuple[float, int, int, float]] = []  # (time, source idx, class idx, length)
    for ci, cls in enumerate(spec.classes):
        rate = cls.rate_per_source_per_h * spec.intensity / 3600.0
        if rate <= 0:
            continue
        for si in range(len(sources)):
            n = rng.poisson(rate * spec.duration_s)
            times = rng.uniform(0.0, spec.duration_s, size=n)
            if cls.length_dist == "fixed":
                lengths = np.full(n, cls.length_mi)
            elif cls.length_dist == "exponential":
                lengths = rng.exponential(cls.length_mi, size=n)
            else:
                lengths = rng.uniform(
                    cls.length_mi * (1 - cls.length_spread), cls.length_mi * (1 + cls.length_spread), n
                )
            raw.extend(zip(times.tolist(), [si] * n, [ci] * n, lengths.tolist(), strict=True))
    raw.sort(key=lambda r: (r[0], r[1], r[2]))
    tasks = []
    for i, (t, si, ci, length) in enumerate(raw):
        cls = spec.classes[ci]
        tasks.append(
            Task(
                id=i,
                cls=cls.name,
                category=cls.category,
                priority=cls.priority,
                source=sources[si],
                arrival_s=t,
                length_mi=max(length, 1e-6),
                input_bytes=cls.input_kb * 1024,
                output_bytes=cls.output_kb * 1024,
                ram_mb=cls.ram_mb,
                deadline_s=cls.deadline_s,
                result_to_source=cls.result_to == "source",
            )
        )
    return Trace(spec_name=spec.name, seed=seed, tasks=tuple(tasks))


# Illustrative agricultural task mix. Sizes and lengths are placeholders to be replaced by profiled values
# (Phase 1b); they are recorded with every experiment so results can be traced to their assumptions.
AGRI_TASK_CLASSES: tuple[TaskClass, ...] = (
    TaskClass(
        name="irrigation_decision",
        category="irrigation",
        priority="critical",
        rate_per_source_per_h=30,
        length_mi=300,
        length_dist="uniform",
        input_kb=0.5,
        output_kb=0.1,
        ram_mb=32,
        deadline_s=2.0,
    ),
    TaskClass(
        name="soil_moisture_analysis",
        category="soil",
        priority="high",
        rate_per_source_per_h=60,
        length_mi=1000,
        length_dist="uniform",
        input_kb=2,
        output_kb=0.5,
        ram_mb=64,
        deadline_s=10.0,
    ),
    TaskClass(
        name="leaf_disease_detection",
        category="crop_health",
        priority="high",
        rate_per_source_per_h=6,
        length_mi=20000,
        length_dist="uniform",
        input_kb=500,
        output_kb=1,
        ram_mb=512,
        deadline_s=30.0,
    ),
    TaskClass(
        name="sensor_aggregation",
        category="aggregation",
        priority="medium",
        rate_per_source_per_h=12,
        length_mi=2000,
        length_dist="uniform",
        input_kb=20,
        output_kb=2,
        ram_mb=128,
        deadline_s=60.0,
        result_to="none",
    ),
    TaskClass(
        name="yield_prediction",
        category="analytics",
        priority="low",
        rate_per_source_per_h=1,
        length_mi=200000,
        length_dist="uniform",
        input_kb=100,
        output_kb=5,
        ram_mb=2048,
        deadline_s=600.0,
        result_to="none",
    ),
)


def agri_workload(duration_s: float = 3600.0, intensity: float = 1.0) -> WorkloadSpec:
    return WorkloadSpec(name="agri-mix", duration_s=duration_s, intensity=intensity, classes=AGRI_TASK_CLASSES)
