"""Retrieval architectures and their evaluation against a scenario's ground truth.

Architectures (``ARCHITECTURES``):

* ``cloud_raw``: the gateway forwards every reading in batches every ``upload_min`` minutes; the cloud
  applies the full framework logic. Detection waits for the batch and the WAN.
* ``cloud_periodic``: like cloud_raw, but sensors are duty-cycled to one reading in ``duty_factor`` to
  save energy and bandwidth.
* ``edge_sod``: the edge sends on delta and raises alerts immediately, but without validation, persistence
  or prediction (a typical "smart gateway").
* ``edge_drf``: the full data retrieval framework at the edge.

Metrics: detection precision, recall and F1 for threshold events; time to detect frost and heat (decision
time minus true onset); for soil stress, the offset of the first alert from the true onset in hours (negative
means early: soil dries slowly, so noise crosses a threshold before the true value does); early-warning lead time;
fault-detection recall; Age of Information of urgent tasks at the scheduler
and the share exceeding their freshness bound; share of readings transmitted; reconstruction error of the
transmitted stream (zero-order hold) against the truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from smartagri_core.retrieval.framework import Event, RetrievalConfig, StreamResult, make_tasks, process_stream
from smartagri_core.retrieval.scenario import Scenario

ARCHITECTURES = {
    "cloud_raw": "Cloud: all readings uploaded in batches",
    "cloud_periodic": "Cloud: duty-cycled sensors, batched uploads",
    "edge_sod": "Edge: send-on-delta, no validation",
    "edge_drf": "Edge: full data retrieval framework",
}


@dataclass(frozen=True)
class ArchitectureSettings:
    upload_min: float = 15.0  # batch upload interval for the cloud architectures
    wan_latency_min: float = 0.25  # rural uplink and cloud processing, minutes (15 s)
    edge_latency_min: float = 0.02  # edge processing, minutes (about 1 s)
    duty_factor: int = 4  # cloud_periodic keeps one reading in this many
    # How long before a true onset an alert still counts as detecting it. Soil dries by about 0.003 m3/m3 a day,
    # so a probe with 0.01 noise crosses a soil threshold days before the true value does; frost and heat change
    # within hours. Alerts after the event's end plus the grace period are false alarms.
    match_lead_min: tuple[tuple[str, float], ...] = (("soil_stress", 2880.0), ("frost", 60.0), ("heat", 60.0))
    match_grace_min: float = 60.0

    def lead_for(self, name: str) -> float:
        return dict(self.match_lead_min).get(name, 60.0)


def architecture_config(name: str, base: RetrievalConfig) -> RetrievalConfig:
    if name in ("cloud_raw", "cloud_periodic"):
        return base.model_copy(update={"send_on_delta": False})
    if name == "edge_sod":
        return base.model_copy(
            update={
                "validate_range": False,
                "validate_spikes": False,
                "validate_stuck": False,
                "persistence": 1,
                "predict": False,
                "smooth_min": {},  # a typical gateway forwards raw readings
                "rules": [r.model_copy(update={"cooldown_min": 0.0}) for r in base.rules],
            }
        )
    if name == "edge_drf":
        return base
    raise ValueError(f"Unknown architecture {name!r}")


def run_architecture(
    scn: Scenario, name: str, base: RetrievalConfig, s: ArchitectureSettings
) -> tuple[list[StreamResult], list[Any]]:
    cfg = architecture_config(name, base)
    results = []
    for stream in scn.streams:
        samples = scn.samples[stream.key]
        if name == "cloud_periodic":
            samples = samples[:: s.duty_factor]
        res = process_stream(stream, samples, cfg)
        for e in res.events:
            if name.startswith("cloud"):
                e.detected_at = math.ceil((e.t + 1e-9) / s.upload_min) * s.upload_min + s.wan_latency_min
            else:
                e.detected_at = e.t + s.edge_latency_min
        if name.startswith("cloud"):
            res.transmitted = [(t, v) for t, v in samples if v is not None]  # everything goes up
        results.append(res)
    return results, make_tasks(results, cfg, scn.horizon)


def _rmse(sent: list[tuple[float, float]], truth: list[tuple[float, float]]) -> float:
    if not sent:
        return math.nan
    j, err, n = 0, 0.0, 0
    for t, v in truth:
        while j + 1 < len(sent) and sent[j + 1][0] <= t:
            j += 1
        if sent[j][0] <= t:
            err += (sent[j][1] - v) ** 2
            n += 1
    return math.sqrt(err / n) if n else math.nan


def evaluate(scn: Scenario, results: list[StreamResult], tasks: list[Any], s: ArchitectureSettings) -> dict[str, float]:
    alerts: list[Event] = [e for r in results for e in r.events if e.kind == "threshold"]
    predicted: list[Event] = [e for r in results for e in r.events if e.kind == "predicted"]
    faults: list[Event] = [e for r in results for e in r.events if e.kind == "fault"]
    true_events = [e for e in scn.events if e.name != "stuck"]
    true_faults = [e for e in scn.events if e.name == "stuck"]

    matched: set[int] = set()
    ttd, soil_offset, lead = [], [], []
    detected = 0
    for ev in true_events:
        hits = [
            i
            for i, a in enumerate(alerts)
            if a.stream == ev.stream
            and a.name == ev.name
            and ev.onset - s.lead_for(ev.name) <= a.t <= ev.end + s.match_grace_min
        ]
        if hits:
            detected += 1
            matched.update(hits)
            first = min(hits, key=lambda i: alerts[i].detected_at or alerts[i].t)
            delay = (alerts[first].detected_at or alerts[first].t) - ev.onset
            (soil_offset if ev.name == "soil_stress" else ttd).append(delay)
        warns = [
            p
            for p in predicted
            if p.stream == ev.stream and p.name == ev.name and ev.onset - 2 * 1440 <= p.t <= ev.onset
        ]
        if warns:
            lead.append(ev.onset - min(p.detected_at or p.t for p in warns))
    # early warnings that came true: a real event of the same kind on the same stream starts within the horizon
    # (plus the matching tolerance) after the warning
    horizon = max((e.eta_min or 0.0) for e in predicted) if predicted else 0.0
    useful = sum(
        1
        for p in predicted
        if any(
            ev.stream == p.stream
            and ev.name == p.name
            and p.t <= ev.onset + s.lead_for(ev.name)
            and ev.onset <= p.t + max(horizon, p.eta_min or 0.0) + s.lead_for(ev.name)
            for ev in true_events
        )
    )
    precision = len(matched) / len(alerts) if alerts else math.nan
    recall = detected / len(true_events) if true_events else math.nan
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall and not math.isnan(precision + recall)
        else 0.0
    )
    fault_hits = sum(
        1 for fe in true_faults if any(f.stream == fe.stream and fe.onset <= f.t <= fe.end + 60 for f in faults)
    )
    urgent = [t for t in tasks if t.urgent]
    aoi = [t.arrival - t.data_time for t in urgent]
    stale = [t for t in urgent if t.arrival - t.data_time > t.freshness_bound]
    raw = sum(r.raw for r in results) if results else 0
    raw_full = sum(len(scn.samples[k]) for k in scn.samples)
    sent = sum(len(r.transmitted) for r in results)
    rmse = [_rmse(r.transmitted, scn.truth[r.stream.key]) for r in results if r.stream.metric.startswith("soil")]
    days = scn.horizon / 1440
    del raw
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_alarms_per_day": (len(alerts) - len(matched)) / days,
        "time_to_detect_min": sum(ttd) / len(ttd) if ttd else math.nan,
        "soil_alert_offset_h": sum(soil_offset) / len(soil_offset) / 60 if soil_offset else math.nan,
        "early_warning_lead_min": sum(lead) / len(lead) if lead else 0.0,
        "early_warning_share": len(lead) / len(true_events) if true_events else math.nan,
        "early_warning_precision": useful / len(predicted) if predicted else math.nan,
        "fault_recall": fault_hits / len(true_faults) if true_faults else math.nan,
        "urgent_aoi_min": sum(aoi) / len(aoi) if aoi else math.nan,
        "freshness_violations": len(stale) / len(urgent) if urgent else 0.0,
        "transmitted_share": sent / raw_full if raw_full else math.nan,
        "soil_rmse": sum(x for x in rmse if not math.isnan(x)) / max(1, sum(1 for x in rmse if not math.isnan(x))),
        "urgent_tasks_per_day": len(urgent) / days,
        "true_events": float(len(true_events)),
    }
