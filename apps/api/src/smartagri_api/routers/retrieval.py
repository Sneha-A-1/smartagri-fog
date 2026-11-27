"""Run the data retrieval framework on a synthetic scenario or on stored device readings."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from smartagri_core.agro.sensors import theta_from_depletion
from smartagri_core.retrieval.evaluate import ARCHITECTURES, ArchitectureSettings, evaluate, run_architecture
from smartagri_core.retrieval.framework import RetrievalConfig, Stream, make_tasks, process_stream, summarize_run
from smartagri_core.retrieval.scenario import ScenarioParams, generate
from sqlalchemy import select
from sqlalchemy.orm import Session

from smartagri_api.db import get_session
from smartagri_api.deps import require
from smartagri_api.device_service import field_model, top_up
from smartagri_api.models import Device, Farm, FarmField, Reading, User
from smartagri_api.weather_service import WeatherUnavailable

router = APIRouter(tags=["retrieval"])

METRIC_LABELS = {
    "soil_moisture_m3m3": ("Soil moisture", "m³/m³"),
    "air_temperature_c": ("Air temperature", "°C"),
    "relative_humidity_pct": ("Relative humidity", "%"),
}


class FrameworkSettings(BaseModel):
    """The settings the page exposes; everything else keeps the framework's defaults."""

    validate_range: bool = True
    validate_spikes: bool = True
    validate_stuck: bool = True
    persistence: int = Field(2, ge=1, le=20)
    soil_smoothing_min: float = Field(60, ge=0, le=1440)
    predict: bool = True
    horizon_min: float = Field(360, gt=0, le=4320)
    send_on_delta: bool = True
    soil_deadband: float = Field(0.01, ge=0, le=0.2)
    temperature_deadband: float = Field(0.5, ge=0, le=10)
    heartbeat_min: float = Field(120, gt=0, le=1440)

    def config(self) -> RetrievalConfig:
        base = RetrievalConfig()
        return base.model_copy(
            update={
                "validate_range": self.validate_range,
                "validate_spikes": self.validate_spikes,
                "validate_stuck": self.validate_stuck,
                "persistence": self.persistence,
                "predict": self.predict,
                "horizon_min": self.horizon_min,
                "send_on_delta": self.send_on_delta,
                "heartbeat_min": self.heartbeat_min,
                "smooth_min": base.smooth_min | {"soil_moisture_m3m3": self.soil_smoothing_min},
                "deadband": base.deadband
                | {"soil_moisture_m3m3": self.soil_deadband, "air_temperature_c": self.temperature_deadband},
            }
        )


class RunIn(BaseModel):
    source: Literal["scenario", "devices"] = "scenario"
    scenario: ScenarioParams = Field(default_factory=ScenarioParams)
    farm_id: str | None = None
    days: int = Field(7, ge=1, le=60, description="Devices: how many past days of readings")
    architecture: Literal["cloud_raw", "cloud_periodic", "edge_sod", "edge_drf"] = "edge_drf"
    settings: FrameworkSettings = Field(default_factory=FrameworkSettings)


class StreamOut(BaseModel):
    key: str
    source: str
    metric: str
    label: str
    unit: str
    group: str
    threshold: float | None
    raw: list[list[float | None]]  # [t, value]
    status: list[str]
    transmitted: list[list[float]]
    truth: list[list[float]] | None


class EventOut(BaseModel):
    stream: str
    t: float
    kind: str
    name: str
    task_class: str
    value: float | None
    eta_min: float | None
    detected_at: float | None


class TaskOut(BaseModel):
    id: str
    stream: str
    group: str
    task_type: str
    task_class: str
    arrival: float
    data_time: float
    deadline: float
    freshness_bound: float
    length_mi: float
    input_bytes: float
    output_bytes: float


class RunOut(BaseModel):
    source: str
    architecture: str
    architecture_label: str
    data_origin: str
    start: datetime
    horizon_min: float
    streams: list[StreamOut]
    events: list[EventOut]
    tasks: list[TaskOut]
    summary: dict[str, Any]
    evaluation: dict[str, float | None] | None
    true_events: list[dict[str, Any]] | None
    notes: list[str]


def _threshold(stream: Stream, cfg: RetrievalConfig) -> float | None:
    rule = next((r for r in cfg.rules if r.metric == stream.metric and r.op == "<="), None)
    return rule.resolve(stream.refs) if rule else None


def _device_streams(
    session: Session, farm: Farm, days: int
) -> tuple[list[Stream], dict[str, list[Any]], datetime, list[str]]:
    devices = list(
        session.scalars(
            select(Device).where(Device.farm_id == farm.id, Device.kind.in_(["soil_moisture", "weather_station"]))
        )
    )
    if not devices:
        raise HTTPException(
            422,
            "This farm has no soil-moisture sensors or weather stations. Add some on the IoT "
            "devices page, or use a synthetic scenario.",
        )
    notes = []
    for d in devices:
        try:
            top_up(session, d)
        except WeatherUnavailable as exc:
            notes.append(f"{d.name}: {exc}")
    session.commit()
    now = datetime.now(UTC)
    start = (now - timedelta(days=days)).replace(second=0, microsecond=0)
    streams, samples = [], {}
    for d in devices:
        metrics = ["soil_moisture_m3m3"] if d.kind == "soil_moisture" else ["air_temperature_c"]
        refs: dict[str, float] = {}
        group = farm.name
        if d.kind == "soil_moisture" and d.field_id:
            f = session.get(FarmField, d.field_id)
            if f is not None:
                crop, soil, zr, _ = field_model(session, f)
                refs = {"stress_theta": theta_from_depletion(crop.p * soil.taw_per_m * zr, soil, zr)}
                group = f.name
        for metric in metrics:
            rows = session.execute(
                select(Reading.ts, Reading.value)
                .where(Reading.device_id == d.id, Reading.metric == metric, Reading.ts >= start)
                .order_by(Reading.ts)
            ).all()
            if not rows:
                continue
            key = f"{d.name}:{metric}"
            streams.append(Stream(key, d.name, metric, group, refs))
            samples[key] = [
                ((ts if ts.tzinfo else ts.replace(tzinfo=UTC)) - start).total_seconds() / 60 for ts, _ in rows
            ]
            samples[key] = list(zip(samples[key], [v for _, v in rows], strict=True))
    if not streams:
        raise HTTPException(422, "No readings in that period yet.")
    return streams, samples, start, notes


@router.get("/retrieval/architectures")
def architectures(_: User = Depends(require("project:read"))) -> dict[str, str]:
    return ARCHITECTURES


@router.post("/retrieval/run", response_model=RunOut)
def run(
    body: RunIn, session: Session = Depends(get_session), _: User = Depends(require("project:read"))
) -> dict[str, Any]:
    cfg = body.settings.config()
    settings = ArchitectureSettings()
    notes: list[str] = []
    truth = None
    true_events = None
    evaluation = None
    if body.source == "scenario":
        scn = generate(body.scenario)
        # the page's settings are the framework; the architecture decides which parts run where
        results, tasks = run_architecture(scn, body.architecture, cfg, settings)
        evaluation = evaluate(scn, results, tasks, settings)
        evaluation = {k: (None if v != v else v) for k, v in evaluation.items()}  # NaN -> null
        truth = scn.truth
        true_events = [dataclasses.asdict(e) for e in scn.events]
        streams_meta, start, horizon, origin = scn.streams, scn.start, scn.horizon, "synthetic"
        raw_samples = scn.samples
    else:
        if not body.farm_id:
            raise HTTPException(422, "Choose a farm")
        farm = session.get(Farm, body.farm_id)
        if farm is None:
            raise HTTPException(404, "Farm not found")
        streams_meta, raw_samples, start, notes = _device_streams(session, farm, body.days)
        horizon = body.days * 1440.0
        results = []
        for s in streams_meta:
            res = process_stream(s, raw_samples[s.key], cfg)
            for e in res.events:
                e.detected_at = e.t + settings.edge_latency_min
            results.append(res)
        tasks = make_tasks(results, cfg, horizon)
        devices = session.scalars(select(Device).where(Device.farm_id == farm.id)).all()
        origin = "real" if any(not d.simulated for d in devices) else "synthetic"
        if body.architecture != "edge_drf":
            notes.append(
                "Device readings are always processed with the framework at the edge; the architecture "
                "choice applies to synthetic scenarios."
            )
    streams = []
    for res in results:
        s = res.stream
        label, unit = METRIC_LABELS.get(s.metric, (s.metric, ""))
        samples = raw_samples[s.key]
        if body.source == "scenario" and body.architecture == "cloud_periodic":
            samples = samples[:: settings.duty_factor]
        streams.append(
            {
                "key": s.key,
                "source": s.source,
                "metric": s.metric,
                "label": label,
                "unit": unit,
                "group": s.group,
                "threshold": _threshold(s, cfg),
                "raw": [[t, v] for t, v in samples],
                "status": res.status,
                "transmitted": [[t, v] for t, v in res.transmitted],
                "truth": [[t, v] for t, v in truth[s.key]] if truth else None,
            }
        )
    events = [dataclasses.asdict(e) for r in results for e in r.events]
    return {
        "source": body.source,
        "architecture": body.architecture,
        "architecture_label": ARCHITECTURES[body.architecture],
        "data_origin": origin,
        "start": start,
        "horizon_min": horizon,
        "streams": streams,
        "events": sorted(events, key=lambda e: e["t"]),
        "tasks": [dataclasses.asdict(t) for t in tasks],
        "summary": summarize_run(results, tasks, cfg),
        "evaluation": evaluation,
        "true_events": true_events,
        "notes": notes,
    }
