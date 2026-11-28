"""Workload model: agricultural task classes and frozen, seeded task traces.

A trace is generated once from (spec, topology, seed) and then replayed unchanged for every algorithm,
so differences between algorithms are never caused by different random workloads.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
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
    data_age_max_s: float = Field(
        0.0, ge=0, description="Input data is up to this old when the task arrives (uniform); 0 = fresh"
    )
    freshness_s: float | None = Field(
        None, gt=0, description="Freshness bound: input data older than this is too stale to act on"
    )


class Surge(BaseModel):
    """Extra arrivals of some task classes during a window, at a share of the gateways (e.g. a monsoon burst)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = "surge"
    start_s: float = Field(ge=0)
    duration_s: float = Field(gt=0)
    factor: float = Field(ge=1, description="Arrival rate during the surge, as a multiple of the normal rate")
    priorities: tuple[Priority, ...] = ("critical", "high")
    source_share: float = Field(1.0, gt=0, le=1, description="Share of gateways affected (chosen by the seed)")


class WarningModel(BaseModel):
    """Early warnings of surges, as an imperfect predictor such as the data retrieval framework produces."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    recall: float = Field(0.6, ge=0, le=1, description="Share of affected gateways warned before a surge")
    precision: float = Field(0.39, gt=0, le=1, description="Share of warnings followed by a real surge")
    lead_min_s: float = Field(300.0, ge=0, description="Shortest warning lead time")
    lead_max_s: float = Field(1800.0, ge=0, description="Longest warning lead time")


@dataclass(frozen=True, slots=True)
class Signal:
    """An early warning: at time_s, gateway source is predicted to see a surge in about eta_s seconds."""

    time_s: float
    source: str
    eta_s: float
    true: bool  # ground truth, for evaluation only; schedulers must not read it
    surge: str


class WorkloadSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = "workload"
    duration_s: float = Field(3600.0, gt=0)
    intensity: float = Field(1.0, gt=0, description="Multiplies every arrival rate")
    classes: tuple[TaskClass, ...]
    sources: tuple[str, ...] | None = Field(None, description="Gateway ids; default: every IoT-layer node")
    surges: tuple[Surge, ...] = ()
    warnings: WarningModel | None = None


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
    data_time_s: float | None = None  # timestamp of the newest input sample (None = arrival time)
    freshness_s: float = math.inf  # input older than this is too stale to act on

    @property
    def urgent(self) -> bool:
        return self.priority in URGENT

    @property
    def abs_deadline(self) -> float:
        return self.arrival_s + self.deadline_s

    @property
    def data_time(self) -> float:
        return self.arrival_s if self.data_time_s is None else self.data_time_s

    @property
    def stale_at(self) -> float:
        """Moment the input data becomes too old to act on (infinite without a freshness bound)."""
        return self.data_time + self.freshness_s

    @property
    def effective_deadline(self) -> float:
        """The earlier of the stated deadline and the moment the input data becomes stale (AURA's D_i)."""
        return min(self.abs_deadline, self.stale_at)


@dataclass(frozen=True)
class Trace:
    spec_name: str
    seed: int
    tasks: tuple[Task, ...]
    # The generator settings, when the trace was generated (learned policies train on fresh traces from it).
    spec: WorkloadSpec | None = field(default=None, compare=False, repr=False)
    signals: tuple[Signal, ...] = ()  # early warnings, sorted by time

    @property
    def sha256(self) -> str:
        # Fields added later are left out while they hold their defaults, so older traces keep their hashes.
        def row(t: Task) -> dict:
            d = asdict(t)
            if d["data_time_s"] is None:
                del d["data_time_s"]
            if d["freshness_s"] == math.inf:
                del d["freshness_s"]
            return d

        body: list = [row(t) for t in self.tasks]
        if self.signals:
            body = [body, [asdict(s) for s in self.signals]]
        payload = json.dumps(body, sort_keys=True).encode()
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
    # Surges and early warnings use their own random streams, so a spec without them gives the same trace
    # as before they existed.
    affected: dict[int, list[int]] = {}
    for k, surge in enumerate(spec.surges):
        srng = np.random.default_rng(np.random.SeedSequence([seed, 0xA7, k]))
        n_aff = max(1, int(round(surge.source_share * len(sources))))
        affected[k] = sorted(srng.choice(len(sources), size=n_aff, replace=False).tolist())
        end = min(surge.start_s + surge.duration_s, spec.duration_s)
        span = max(end - surge.start_s, 0.0)
        for ci, cls in enumerate(spec.classes):
            if cls.priority not in surge.priorities:
                continue
            rate = cls.rate_per_source_per_h * spec.intensity / 3600.0 * (surge.factor - 1.0)
            for si in affected[k]:
                n = srng.poisson(rate * span)
                times = srng.uniform(surge.start_s, surge.start_s + span, size=n)
                if cls.length_dist == "fixed":
                    lengths = np.full(n, cls.length_mi)
                elif cls.length_dist == "exponential":
                    lengths = srng.exponential(cls.length_mi, size=n)
                else:
                    lengths = srng.uniform(
                        cls.length_mi * (1 - cls.length_spread), cls.length_mi * (1 + cls.length_spread), n
                    )
                raw.extend(zip(times.tolist(), [si] * n, [ci] * n, lengths.tolist(), strict=True))
    raw.sort(key=lambda r: (r[0], r[1], r[2]))
    arng = np.random.default_rng(np.random.SeedSequence([seed, 0xA8]))
    tasks = []
    for i, (t, si, ci, length) in enumerate(raw):
        cls = spec.classes[ci]
        data_time = t - arng.uniform(0.0, cls.data_age_max_s) if cls.data_age_max_s > 0 else None
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
                data_time_s=data_time,
                freshness_s=cls.freshness_s if cls.freshness_s is not None else math.inf,
            )
        )
    signals = _warnings(spec, sources, affected, seed)
    return Trace(spec_name=spec.name, seed=seed, tasks=tuple(tasks), spec=spec, signals=signals)


def _warnings(spec: WorkloadSpec, sources: list[str], affected: dict[int, list[int]], seed: int) -> tuple[Signal, ...]:
    """True warnings for a share (recall) of affected gateways, plus false alarms so that precision holds."""
    wm = spec.warnings
    if wm is None or not spec.surges:
        return ()
    wrng = np.random.default_rng(np.random.SeedSequence([seed, 0xA9]))
    out: list[Signal] = []
    for k, surge in enumerate(spec.surges):
        for si in affected[k]:
            if wrng.random() >= wm.recall:
                continue
            lead = wrng.uniform(wm.lead_min_s, max(wm.lead_max_s, wm.lead_min_s))
            t = max(surge.start_s - lead, 0.0)
            out.append(Signal(t, sources[si], surge.start_s - t, True, surge.name))
    n_true = len(out)
    n_false = int(round(n_true * (1.0 - wm.precision) / wm.precision)) if n_true else 0
    for _ in range(n_false):
        t = wrng.uniform(0.0, spec.duration_s)
        eta = wrng.uniform(wm.lead_min_s, max(wm.lead_max_s, wm.lead_min_s))
        out.append(Signal(t, sources[int(wrng.integers(len(sources)))], eta, False, "false alarm"))
    out.sort(key=lambda s: (s.time_s, s.source))
    return tuple(out)


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
