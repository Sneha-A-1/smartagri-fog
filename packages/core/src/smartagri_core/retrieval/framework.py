"""The data retrieval framework (DRF): what an edge node does with raw sensor streams.

Each stream (one metric from one source) passes through five stages, in order, sample by sample:

1. **Validate**: physical range check, spike detection (Hampel filter: deviation from the median of recent
   readings, in units of the scaled median absolute deviation) and stuck-sensor detection (no change
   over a time window). Invalid samples are not used or transmitted; a range or stuck fault raises one
   maintenance event per episode.
2. **Smooth** slow signals with a moving median (soil moisture changes over days while a probe's noise is
   larger than a day's change), then **detect** with threshold rules with a persistence requirement (k consecutive
   valid samples) and hysteresis
   (re-arm only after the value moves back past the threshold by a margin) and a cool-down (the same alert
   is not repeated on a stream within a set time), so noise does not cause repeated or spurious alerts. Thresholds
   can be numbers or per-stream references such as a field's
   water-stress soil moisture.
3. **Predict**: for armed rules, a least-squares trend over a recent window estimates the time until the
   threshold is crossed; a crossing expected within the horizon raises a predicted event (an early warning
   that AURA uses to reserve capacity).
4. **Reduce**: send-on-delta. A valid sample is transmitted upstream only if it differs from the last
   transmitted value by at least the dead band, if the heartbeat interval has elapsed, or if it triggered
   an event.
5. **Emit tasks**: each alert becomes a task for the scheduler with a class (critical, high, medium, low),
   a deadline, a freshness bound and the timestamp of its newest input sample (for Age of Information).
   Periodic aggregation of transmitted data becomes low-priority (strategic) tasks.

Times are minutes from the start of the stream; values are in the metric's unit.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskClass = Literal["critical", "high", "medium", "low"]
CLASS_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class Bounds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    low: float
    high: float


class Rule(BaseModel):
    """Alert when ``metric`` goes below (``op`` "<=") or above (">=") a threshold."""

    model_config = ConfigDict(extra="forbid")
    name: str
    metric: str
    op: Literal["<=", ">="]
    threshold: float | None = None
    threshold_ref: str | None = Field(None, description="Per-stream reference, e.g. 'stress_theta'")
    task_class: TaskClass = "high"
    hysteresis: float = Field(0.0, ge=0, description="Re-arm margin past the threshold")
    cooldown_min: float = Field(0.0, ge=0, description="Do not repeat this alert on a stream within this time")
    task_type: str = "alert"

    def resolve(self, refs: dict[str, float]) -> float | None:
        if self.threshold_ref is not None:
            return refs.get(self.threshold_ref)
        return self.threshold


class TaskProfile(BaseModel):
    """Size and timing of the task an event creates (seeded from AURA's task model)."""

    model_config = ConfigDict(extra="forbid")
    length_mi: float = 500
    input_bytes: float = 2_000
    output_bytes: float = 200
    deadline_min: float = 10
    freshness_min: float = 30


DEFAULT_PROFILES: dict[str, TaskProfile] = {
    "critical": TaskProfile(length_mi=300, input_bytes=1_000, deadline_min=2, freshness_min=10),
    "high": TaskProfile(length_mi=800, input_bytes=4_000, deadline_min=10, freshness_min=30),
    "medium": TaskProfile(length_mi=1_500, input_bytes=8_000, deadline_min=60, freshness_min=120),
    "low": TaskProfile(length_mi=20_000, input_bytes=0, deadline_min=240, freshness_min=1_440),
}


class RetrievalConfig(BaseModel):
    """Every switch of the framework. The defaults are the full DRF."""

    model_config = ConfigDict(extra="forbid")

    validate_range: bool = True
    validate_spikes: bool = True
    validate_stuck: bool = True
    bounds: dict[str, Bounds] = Field(
        default_factory=lambda: {
            "soil_moisture_m3m3": Bounds(low=0.0, high=0.6),
            "air_temperature_c": Bounds(low=-30, high=55),
            "relative_humidity_pct": Bounds(low=0, high=100),
        }
    )
    spike_window: int = Field(7, ge=3, le=50, description="Recent valid samples used for the median")
    spike_sigmas: float = Field(4.0, gt=0, description="Deviation limit in scaled MADs")
    spike_min_abs: dict[str, float] = Field(
        default_factory=lambda: {"soil_moisture_m3m3": 0.03, "air_temperature_c": 3.0, "relative_humidity_pct": 10.0},
        description="A deviation smaller than this is never a spike (avoids flagging noise when the MAD is tiny)",
    )
    stuck_minutes: float = Field(180, gt=0, description="No change for this long means a stuck sensor")
    stuck_epsilon: float = Field(1e-6, ge=0)

    rules: list[Rule] = Field(
        default_factory=lambda: [
            Rule(
                name="soil_stress",
                metric="soil_moisture_m3m3",
                op="<=",
                threshold_ref="stress_theta",
                task_class="high",
                hysteresis=0.01,
                cooldown_min=720,
                task_type="irrigation_decision",
            ),
            Rule(
                name="frost",
                metric="air_temperature_c",
                op="<=",
                threshold=2.0,
                task_class="critical",
                hysteresis=1.0,
                cooldown_min=180,
                task_type="frost_protection",
            ),
            Rule(
                name="heat",
                metric="air_temperature_c",
                op=">=",
                threshold=40.0,
                task_class="high",
                hysteresis=1.0,
                cooldown_min=180,
                task_type="heat_advisory",
            ),
        ]
    )
    persistence: int = Field(2, ge=1, le=20, description="Consecutive valid samples needed to raise an alert")
    smooth_min: dict[str, float] = Field(
        default_factory=lambda: {"soil_moisture_m3m3": 60.0, "air_temperature_c": 0.0, "relative_humidity_pct": 30.0},
        description="Moving-median window per metric used for rules, prediction and transmission (0 = raw). "
        "Slow signals such as soil moisture are smoothed; fast ones such as temperature are not.",
    )

    predict: bool = True
    trend_window_min: float = Field(240, gt=0)
    trend_min_points: int = Field(6, ge=3)
    horizon_min: float = Field(360, gt=0, description="Raise an early warning if a crossing is expected within this")

    send_on_delta: bool = True
    deadband: dict[str, float] = Field(
        default_factory=lambda: {
            "soil_moisture_m3m3": 0.01,
            "air_temperature_c": 0.5,
            "relative_humidity_pct": 3.0,
        }
    )
    heartbeat_min: float = Field(120, gt=0, description="Transmit at least this often even without change")
    bytes_per_sample: int = Field(32, ge=1)

    aggregation_min: float = Field(60, gt=0, description="Window of the strategic aggregation tasks")
    profiles: dict[str, TaskProfile] = Field(default_factory=lambda: dict(DEFAULT_PROFILES))


@dataclass(frozen=True)
class Stream:
    key: str  # unique stream id, e.g. "probe-3:soil_moisture_m3m3"
    source: str
    metric: str
    group: str = ""  # field or farm the stream belongs to (for aggregation tasks)
    refs: dict[str, float] = field(default_factory=dict)


@dataclass
class Event:
    stream: str
    t: float  # time of the sample that caused it
    kind: Literal["threshold", "predicted", "fault"]
    name: str  # rule name, or fault type
    task_class: TaskClass
    value: float | None
    eta_min: float | None = None  # predicted events: expected minutes to the crossing
    detected_at: float | None = None  # filled in by the architecture (edge: t; cloud: upload time)


@dataclass
class Task:
    id: str
    stream: str
    group: str
    task_type: str
    task_class: TaskClass
    arrival: float  # when the task reaches the scheduler
    data_time: float  # timestamp of its newest input sample (AoI = decision time - data_time)
    deadline: float
    freshness_bound: float
    length_mi: float
    input_bytes: float
    output_bytes: float

    @property
    def urgent(self) -> bool:
        return self.task_class in ("critical", "high")


@dataclass
class StreamResult:
    stream: Stream
    status: list[str]  # per input sample: ok, missing, range, spike, stuck
    transmitted: list[tuple[float, float]]
    events: list[Event]
    raw: int = 0
    valid: int = 0


def _slope(points: deque[tuple[float, float]]) -> float | None:
    n = len(points)
    if n < 2:
        return None
    mt = sum(t for t, _ in points) / n
    mv = sum(v for _, v in points) / n
    den = sum((t - mt) ** 2 for t, _ in points)
    if den == 0:
        return None
    return sum((t - mt) * (v - mv) for t, v in points) / den


def process_stream(stream: Stream, samples: list[tuple[float, float | None]], cfg: RetrievalConfig) -> StreamResult:
    """Run stages 1-4 over one stream's samples (sorted by time)."""
    rules = [r for r in cfg.rules if r.metric == stream.metric]
    thresholds = [r.resolve(stream.refs) for r in rules]
    bounds = cfg.bounds.get(stream.metric)
    min_abs = cfg.spike_min_abs.get(stream.metric, 0.0)
    delta = cfg.deadband.get(stream.metric, 0.0)
    smooth = cfg.smooth_min.get(stream.metric, 0.0)
    window: deque[tuple[float, float]] = deque()
    recent: deque[float] = deque(maxlen=cfg.spike_window)
    trend: deque[tuple[float, float]] = deque()
    stuck_since: tuple[float, float] | None = None  # (start time, value) of the current unchanged run
    fault_open: dict[str, bool] = {"range": False, "stuck": False}
    armed = [True] * len(rules)
    consec = [0] * len(rules)
    warned = [False] * len(rules)
    last_alert: list[float | None] = [None] * len(rules)
    last_sent: tuple[float, float] | None = None
    res = StreamResult(stream, [], [], [])

    for t, v in samples:
        res.raw += 1
        if v is None or (isinstance(v, float) and math.isnan(v)):
            res.status.append("missing")
            continue
        status = "ok"
        if cfg.validate_range and bounds and not (bounds.low <= v <= bounds.high):
            status = "range"
        if status == "ok" and cfg.validate_stuck:
            if stuck_since is None or abs(v - stuck_since[1]) > cfg.stuck_epsilon:
                stuck_since = (t, v)
            elif t - stuck_since[0] >= cfg.stuck_minutes:
                status = "stuck"
        if status == "ok" and cfg.validate_spikes and len(recent) >= 3:
            m = median(recent)
            mad = median(abs(x - m) for x in recent) * 1.4826
            if abs(v - m) > max(cfg.spike_sigmas * mad, min_abs):
                status = "spike"
        if status != "range":
            # Hampel window over recent readings, flagged or not: a genuine level change (irrigation, rain)
            # is accepted after a few samples instead of being rejected forever.
            recent.append(v)
        for fault in ("range", "stuck"):
            if status == fault and not fault_open[fault]:
                fault_open[fault] = True
                res.events.append(Event(stream.key, t, "fault", fault, "medium", v))
            elif status == "ok":
                fault_open[fault] = False
        res.status.append(status)
        if status != "ok":
            continue
        res.valid += 1
        if smooth > 0:
            window.append((t, v))
            while window and t - window[0][0] >= smooth:
                window.popleft()
            v = median(x for _, x in window)
        trend.append((t, v))
        while trend and t - trend[0][0] > cfg.trend_window_min:
            trend.popleft()

        triggered = False
        for i, (rule, thr) in enumerate(zip(rules, thresholds, strict=True)):
            if thr is None:
                continue
            breached = v <= thr if rule.op == "<=" else v >= thr
            consec[i] = consec[i] + 1 if breached else 0
            if armed[i] and consec[i] >= cfg.persistence:
                if last_alert[i] is None or t - last_alert[i] >= rule.cooldown_min:
                    res.events.append(Event(stream.key, t, "threshold", rule.name, rule.task_class, v))
                    last_alert[i], triggered = t, True
                armed[i] = False
            elif not armed[i] and not breached:
                released = v > thr + rule.hysteresis if rule.op == "<=" else v < thr - rule.hysteresis
                if released:
                    armed[i], warned[i] = True, False
            if cfg.predict and armed[i] and not breached and not warned[i] and len(trend) >= cfg.trend_min_points:
                s = _slope(trend)
                if s and ((rule.op == "<=" and s < 0) or (rule.op == ">=" and s > 0)):
                    eta = (thr - v) / s
                    if 0 < eta <= cfg.horizon_min:
                        res.events.append(Event(stream.key, t, "predicted", rule.name, rule.task_class, v, eta_min=eta))
                        warned[i] = True

        send = (
            not cfg.send_on_delta
            or last_sent is None
            or abs(v - last_sent[1]) >= delta
            or t - last_sent[0] >= cfg.heartbeat_min
            or triggered
        )
        if send:
            res.transmitted.append((t, v))
            last_sent = (t, v)
    return res


def make_tasks(results: list[StreamResult], cfg: RetrievalConfig, horizon: float) -> list[Task]:
    """Stage 5: tasks from alerts (urgent or maintenance) and from periodic aggregation (strategic)."""
    tasks: list[Task] = []
    rule_types = {r.name: r.task_type for r in cfg.rules}
    for res in results:
        for e in res.events:
            if e.kind == "predicted":
                continue  # early warnings feed capacity reservation, not the task queue
            prof = cfg.profiles[e.task_class]
            arrival = e.detected_at if e.detected_at is not None else e.t
            ttype = rule_types.get(e.name, "alert") if e.kind == "threshold" else "maintenance"
            tasks.append(
                Task(
                    f"t{len(tasks)}",
                    e.stream,
                    res.stream.group,
                    ttype,
                    e.task_class,
                    arrival,
                    e.t,
                    arrival + prof.deadline_min,
                    prof.freshness_min,
                    prof.length_mi,
                    prof.input_bytes,
                    prof.output_bytes,
                )
            )
    by_group: dict[str, list[tuple[float, float]]] = {}
    for res in results:
        by_group.setdefault(res.stream.group, []).extend(res.transmitted)
    low = cfg.profiles["low"]
    w = cfg.aggregation_min
    for group, sent in sorted(by_group.items()):
        n_windows = int(math.ceil(horizon / w))
        counts = [0] * max(n_windows, 1)
        for t, _ in sent:
            counts[min(int(t // w), len(counts) - 1)] += 1
        for k, c in enumerate(counts):
            if c == 0:
                continue
            end = (k + 1) * w
            tasks.append(
                Task(
                    f"t{len(tasks)}",
                    f"{group}:aggregate",
                    group,
                    "aggregation",
                    "low",
                    end,
                    end,
                    end + low.deadline_min,
                    low.freshness_min,
                    low.length_mi,
                    c * cfg.bytes_per_sample,
                    low.output_bytes,
                )
            )
    tasks.sort(key=lambda x: (x.arrival, CLASS_ORDER[x.task_class]))
    return tasks


def summarize_run(results: list[StreamResult], tasks: list[Task], cfg: RetrievalConfig) -> dict[str, Any]:
    raw = sum(r.raw for r in results)
    sent = sum(len(r.transmitted) for r in results)
    statuses: dict[str, int] = {}
    for r in results:
        for s in r.status:
            statuses[s] = statuses.get(s, 0) + 1
    events: dict[str, int] = {}
    for r in results:
        for e in r.events:
            events[f"{e.kind}:{e.name}"] = events.get(f"{e.kind}:{e.name}", 0) + 1
    by_class: dict[str, int] = {}
    for t in tasks:
        by_class[t.task_class] = by_class.get(t.task_class, 0) + 1
    return {
        "samples": raw,
        "transmitted": sent,
        "reduction": 1 - sent / raw if raw else 0.0,
        "bytes_raw": raw * cfg.bytes_per_sample,
        "bytes_transmitted": sent * cfg.bytes_per_sample,
        "status": statuses,
        "events": events,
        "tasks_by_class": by_class,
        "urgent_tasks": sum(1 for t in tasks if t.urgent),
    }
