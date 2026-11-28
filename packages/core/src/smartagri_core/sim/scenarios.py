"""Stress scenarios for evaluating schedulers (and AURA in particular).

Each scenario changes the default agricultural workload and simulator settings in one documented way.
Event times are fractions of the run's duration, so a scenario works for any duration. All values below
are modelling assumptions; they are recorded with every result through the parameters and the event list.

* ``none``: the original workload with no freshness bounds (kept so earlier results stay reproducible).
* ``normal``: the same arrival rates, but every task carries a data timestamp and a freshness bound (AoI).
* ``monsoon_burst``: urgent tasks arrive six times faster for up to 20 minutes on half of the gateways
  (correlated emergencies in one area), with early warnings as imperfect as the data retrieval framework's
  measured ones: 60% of affected gateways warned, 39% of warnings true (docs/retrieval-framework.md).
* ``heat_wave``: urgent tasks arrive 2.5 times faster on every gateway for half the run, with a forecast
  that warns 90% of gateways and is right 80% of the time.
* ``cloud_disconnection``: the cloud is unreachable for 30 minutes (or half the run, if shorter).
* ``fog_failure``: one fog server fails for 20 minutes (or a third of the run, if shorter).
"""

from __future__ import annotations

from typing import Any, Literal

from smartagri_core.sim.engine import Outage, SimSettings
from smartagri_core.sim.topology import Layer, Topology
from smartagri_core.sim.workload import AGRI_TASK_CLASSES, Surge, WarningModel, WorkloadSpec

StressKey = Literal["none", "normal", "monsoon_burst", "heat_wave", "cloud_disconnection", "fog_failure"]

STRESS_INFO: dict[str, tuple[str, str]] = {
    "none": ("Original workload", "The default task mix without data-freshness bounds."),
    "normal": (
        "Normal load with data freshness",
        "Default arrival rates; every task has an input age and a freshness bound.",
    ),
    "monsoon_burst": (
        "Monsoon burst",
        "Urgent tasks arrive 6× faster for up to 20 min on half the gateways; "
        "early warnings 60% recall, 39% precision.",
    ),
    "heat_wave": (
        "Heat wave",
        "Urgent tasks arrive 2.5× faster everywhere for half the run; forecast warnings 90% recall, 80% precision.",
    ),
    "cloud_disconnection": ("Cloud disconnection", "The cloud is unreachable for 30 min (or half the run)."),
    "fog_failure": ("Fog server failure", "One fog server is down for 20 min (or a third of the run)."),
}

# Input age at arrival (uniform up to the first value) and freshness bound, per task class, in seconds.
# Assumptions: soil probes report every 30-60 s over LoRaWAN, cameras upload images up to 2 min after capture,
# aggregation runs on readings up to 5 min old. Yield prediction uses historical data and has no bound.
FRESHNESS: dict[str, tuple[float, float | None]] = {
    "irrigation_decision": (30.0, 30.0),
    "soil_moisture_analysis": (60.0, 60.0),
    "leaf_disease_detection": (120.0, 120.0),
    "sensor_aggregation": (300.0, 300.0),
    "yield_prediction": (0.0, None),
}


def fresh_classes(classes=AGRI_TASK_CLASSES):
    """The task classes with input age and freshness bounds; classes not in FRESHNESS keep their own values."""
    out = []
    for cls in classes:
        if cls.name in FRESHNESS:
            age, bound = FRESHNESS[cls.name]
            cls = cls.model_copy(update={"data_age_max_s": age, "freshness_s": bound})
        out.append(cls)
    return tuple(out)


def apply_stress(
    stress: str, topo: Topology, spec: WorkloadSpec, settings: SimSettings
) -> tuple[WorkloadSpec, SimSettings, list[dict[str, Any]]]:
    """The workload and settings for a scenario, plus a list of its events for display."""
    if stress == "none":
        return spec, settings, []
    d = spec.duration_s
    spec = spec.model_copy(update={"classes": fresh_classes(spec.classes), "name": f"{spec.name}+{stress}"})
    events: list[dict[str, Any]] = []
    if stress == "monsoon_burst":
        surge = Surge(
            name="monsoon burst", start_s=0.4 * d, duration_s=min(0.25 * d, 1200.0), factor=6.0, source_share=0.5
        )
        spec = spec.model_copy(
            update={
                "surges": (surge,),
                "warnings": WarningModel(recall=0.6, precision=0.39, lead_min_s=300.0, lead_max_s=1800.0),
            }
        )
        events.append(_surge_event(surge))
    elif stress == "heat_wave":
        surge = Surge(name="heat wave", start_s=0.25 * d, duration_s=0.5 * d, factor=2.5, source_share=1.0)
        spec = spec.model_copy(
            update={
                "surges": (surge,),
                "warnings": WarningModel(recall=0.9, precision=0.8, lead_min_s=600.0, lead_max_s=1800.0),
            }
        )
        events.append(_surge_event(surge))
    elif stress == "cloud_disconnection":
        outage = Outage(target="cloud", start_s=0.25 * d, duration_s=min(1800.0, 0.5 * d), label="cloud disconnection")
        settings = settings.model_copy(update={"outages": (outage,)})
        events.append(_outage_event(outage))
    elif stress == "fog_failure":
        fogs = sorted(n.id for n in topo.by_layer(Layer.FOG) if n.can_compute)
        if not fogs:
            raise ValueError("The fog-failure scenario needs at least one fog server")
        outage = Outage(target=fogs[0], start_s=0.3 * d, duration_s=min(1200.0, d / 3), label="fog server failure")
        settings = settings.model_copy(update={"outages": (outage,)})
        events.append(_outage_event(outage))
    return spec, settings, events


def _surge_event(s: Surge) -> dict[str, Any]:
    return {
        "kind": "surge",
        "label": s.name,
        "start_s": s.start_s,
        "end_s": s.start_s + s.duration_s,
        "detail": f"{s.factor:g}× urgent arrivals on {round(100 * s.source_share)}% of gateways",
    }


def _outage_event(o: Outage) -> dict[str, Any]:
    return {
        "kind": "outage",
        "label": o.label or f"{o.target} outage",
        "start_s": o.start_s,
        "end_s": o.start_s + o.duration_s,
        "detail": f"{o.target} unavailable",
    }
