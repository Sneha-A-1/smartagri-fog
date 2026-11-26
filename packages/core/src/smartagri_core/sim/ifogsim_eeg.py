"""Reproduction of the EEG Tractor Beam Game case study (Gupta et al., 2017, Section 5.1 and 6.1).

H. Gupta, A. V. Dastjerdi, S. K. Ghosh, R. Buyya. "iFogSim: A toolkit for modeling and simulation of
resource management techniques in the Internet of Things, Edge and Fog computing environments."
Software: Practice and Experience 47(9), 2017. doi:10.1002/spe.2509

Every parameter below names its source: the paper's tables, or, where the paper does not give a value
(MIPS, bandwidth, periodic intervals, cloud power), the authors' reference implementation
``org.fog.test.perfeval.VRGameFog`` in iFogSim 1.0.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from smartagri_core.progress import ProgressReporter, null_progress
from smartagri_core.registry import PluginKind, register
from smartagri_core.sim.dataflow import (
    ActuatorSpec,
    AppEdge,
    Application,
    DataflowSettings,
    FogDevice,
    FogNetwork,
    Placement,
    SensorSpec,
    TupleMapping,
    place_cloud_only,
    place_edge_ward,
    simulate_dataflow,
)
from smartagri_core.stats import summarize
from smartagri_core.status import CapabilityStatus, DataOrigin

Headset = Literal["A", "B"]
PlacementKey = Literal["cloud_only", "edge_ward"]

CONFIG_GATEWAYS = {1: 1, 2: 2, 3: 4, 4: 8, 5: 16}  # paper 6.1: Config 1-5 have 1, 2, 4, 8, 16 WiFi gateways
PHONES_PER_GATEWAY = 4  # paper 6.1
SIMULATED_HOURS_IN_PAPER = 3  # paper 6.1

# Table III: tuple CPU length (MI) and average inter-arrival time (ms) per headset
HEADSETS: dict[str, tuple[float, float]] = {"A": (2000.0, 10.0), "B": (2500.0, 5.0)}

LOOP = ("EEG", "client", "concentration_calculator", "client", "DISPLAY")

SOURCES = {
    "Tuple CPU and network lengths": "Paper Table I",
    "Headset tuple length and inter-arrival time": "Paper Table III",
    "Link latencies (6, 2, 4, 100 ms)": "Paper Table VI",
    "Configurations, 4 smartphones per gateway": "Paper Section 6.1",
    "Gateway and smartphone power": "Paper Table II",
    "Device MIPS (cloud 44800, gateways 2800, phone 1000)": "VRGameFog.java (the paper gives GHz only)",
    "Bandwidths (10000 bytes/ms; phone downlink 270)": "VRGameFog.java (not in the paper)",
    "Periodic game-state edges every 100 ms": "VRGameFog.java (not in the paper)",
    "Tuple selectivity 0.9 for EEG to _SENSOR": "VRGameFog.java (not in the paper)",
    "Cloud power 16 x 103 W busy, 16 x 83.25 W idle": (
        "VRGameFog.java; Figure 13's data-centre energy matches these, not Table II"
    ),
    "Client module on the smartphone in cloud-only placement": (
        "VRGameFog.java; consistent with the paper's network-usage results"
    ),
}


def eeg_application(headset: Headset) -> Application:
    eeg_cpu, _ = HEADSETS[headset]
    edges = (
        AppEdge("EEG", "client", "EEG", eeg_cpu, 500, kind="sensor"),
        AppEdge("client", "concentration_calculator", "_SENSOR", 3500, 500),
        AppEdge("concentration_calculator", "connector", "PLAYER_GAME_STATE", 1000, 1000, period=100.0),
        AppEdge("concentration_calculator", "client", "CONCENTRATION", 14, 500),
        AppEdge("connector", "client", "GLOBAL_GAME_STATE", 1000, 1000, period=100.0),
        AppEdge("client", "DISPLAY", "SELF_STATE_UPDATE", 1000, 500, kind="actuator"),
        AppEdge("client", "DISPLAY", "GLOBAL_STATE_UPDATE", 1000, 500, kind="actuator"),
    )
    mappings = (
        TupleMapping("client", "EEG", "_SENSOR", 0.9),
        TupleMapping("client", "CONCENTRATION", "SELF_STATE_UPDATE", 1.0),
        TupleMapping("concentration_calculator", "_SENSOR", "CONCENTRATION", 1.0),
        TupleMapping("client", "GLOBAL_GAME_STATE", "GLOBAL_STATE_UPDATE", 1.0),
    )
    return Application("vr_game", ("client", "concentration_calculator", "connector"), edges, mappings, (LOOP,))


def eeg_network(
    gateways: int, headset: Headset, phones_per_gateway: int = PHONES_PER_GATEWAY, staggered: bool = False
) -> FogNetwork:
    _, interval = HEADSETS[headset]
    devices = {
        "cloud": FogDevice("cloud", 44800, 100, 10000, None, 0.0, 16 * 103, 16 * 83.25, "cloud"),
        "proxy-server": FogDevice("proxy-server", 2800, 10000, 10000, "cloud", 100.0, 107.339, 83.4333, "fog"),
    }
    sensors, actuators = [], []
    n = gateways * phones_per_gateway
    for g in range(gateways):
        gw = f"d-{g}"
        devices[gw] = FogDevice(gw, 2800, 10000, 10000, "proxy-server", 4.0, 107.339, 83.4333, "fog")
        for k in range(phones_per_gateway):
            idx = g * phones_per_gateway + k
            m = f"m-{g}-{k}"
            devices[m] = FogDevice(m, 1000, 10000, 270, gw, 2.0, 87.53, 82.44, "mobile")
            phase = interval * idx / n if staggered else 0.0
            sensors.append(SensorSpec(f"s-{g}-{k}", m, "EEG", interval, 6.0, "deterministic", phase))
            actuators.append(ActuatorSpec(f"a-{g}-{k}", m, "DISPLAY", 1.0))
    return FogNetwork(devices, sensors, actuators)


def eeg_placement(app: Application, net: FogNetwork, strategy: PlacementKey) -> Placement:
    if strategy == "cloud_only":
        return place_cloud_only(app, net, edge_modules=["client"])
    return place_edge_ward(app, net, pinned={"connector": "cloud"})


# Values read from the paper's Figures 11 and 12 by pixel measurement of the published bars
# (resolution about 10 ms and 3 KB). Bars for edge-ward latency are a few pixels tall.
PAPER_FIGURE_VALUES = {
    "loop_delay_ms": {
        ("A", "edge_ward"): [20, 20, 30, 30, 20],
        ("B", "edge_ward"): [30, 20, 30, 30, 20],
        ("A", "cloud_only"): [229, 229, 229, 906, 4064],
        ("B", "cloud_only"): [219, 219, 219, 2958, 4582],
    },
    "network_usage_kb": {
        ("A", "edge_ward"): [None, 9, 17, 35, 70],
        ("B", "edge_ward"): [9, 17, 35, 64, 128],
        ("A", "cloud_only"): [41, 84, 186, 415, 709],
        ("B", "cloud_only"): [78, 163, 357, 697, 1278],
    },
}


# --- plugin ----------------------------------------------------------------------------------------

CITATION = (
    "H. Gupta, A. V. Dastjerdi, S. K. Ghosh, R. Buyya. iFogSim: A toolkit for modeling and simulation of "
    "resource management techniques in the Internet of Things, Edge and Fog computing environments. "
    "Software: Practice and Experience 47(9):1275-1296, 2017."
)


class EEGCaseStudyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configs: list[int] = Field(
        default_factory=lambda: [1, 2, 3, 4, 5],
        title="Configurations",
        description="Paper configurations 1-5 (1, 2, 4, 8 and 16 WiFi gateways, 4 smartphones each).",
    )
    headsets: list[Headset] = Field(default_factory=lambda: ["A", "B"], description="Headset types from Table III.")
    placements: list[PlacementKey] = Field(
        default_factory=lambda: ["cloud_only", "edge_ward"], description="Module placement strategies."
    )
    duration_s: float = Field(
        10.0,
        title="Simulated time (s)",
        ge=2,
        le=600,
        description="The paper simulated 3 hours; steady state is reached within a second.",
    )
    warmup_s: float = Field(1.0, title="Warm-up (s)", ge=0, le=60, description="Excluded from the measurements.")
    replications: int = Field(3, ge=1, le=30, description="Runs per cell with different seeds (selectivity draws).")
    base_seed: int = Field(1, title="First seed", ge=0)
    staggered_sensors: bool = Field(
        False,
        title="Stagger sensor start times",
        description="iFogSim starts every headset at time 0. Staggering spreads them over one interval.",
        json_schema_extra={"x-advanced": True},
    )

    @field_validator("configs")
    @classmethod
    def _configs(cls, v: list[int]) -> list[int]:
        if not v or any(c not in CONFIG_GATEWAYS for c in v):
            raise ValueError("Configurations must be between 1 and 5")
        return sorted(set(v))


def _clean(d: dict[str, float]) -> dict[str, float | None]:
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in d.items()}


def _checks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Statements about the paper's findings, each evaluated on this run's numbers."""

    def cell(h, p, c, metric):
        for r in rows:
            if (r["headset"], r["placement"], r["config"]) == (h, p, c):
                return r[metric]["mean"]
        return None

    configs = sorted({r["config"] for r in rows})
    headsets = sorted({r["headset"] for r in rows})
    have_both = {r["placement"] for r in rows} >= {"cloud_only", "edge_ward"}
    checks = []
    if have_both:
        for metric, label in (("loop_delay_ms", "control-loop delay"), ("network_usage_kb", "network usage")):
            ok = all(
                cell(h, "edge_ward", c, metric) < cell(h, "cloud_only", c, metric) for h in headsets for c in configs
            )
            checks.append(
                {
                    "claim": f"Edge-ward has lower {label} than cloud-only in every configuration",
                    "paper": "Figures 11 and 12",
                    "holds": ok,
                }
            )
    if len(configs) > 1:
        ok = all(
            cell(h, p, a, "network_usage_kb") < cell(h, p, b, "network_usage_kb")
            for h in headsets
            for p in {r["placement"] for r in rows}
            for a, b in zip(configs, configs[1:], strict=False)
        )
        checks.append({"claim": "Network usage grows as gateways are added", "paper": "Figure 12", "holds": ok})
    for pl in sorted({r["placement"] for r in rows}):
        errs = [
            (r["network_usage_kb"]["mean"] / r["paper_network_usage_kb"] - 1, r)
            for r in rows
            if r["placement"] == pl and r["paper_network_usage_kb"]
        ]
        if errs:
            worst, wr = max(errs, key=lambda e: abs(e[0]))
            detail = f"largest difference {worst:+.0%} (headset {wr['headset']}, Config {wr['config']})"
            if pl == "edge_ward":
                detail += (
                    ". Edge-ward placement here follows iFogSim's load rule, which puts the concentration calculator "
                    "on each smartphone for headset A, so every phone sends game state to the cloud."
                )
            checks.append(
                {
                    "claim": f"{pl.replace('_', '-').capitalize()} network usage within 20% of the paper "
                    "in every configuration",
                    "paper": "Figure 12",
                    "holds": max(abs(e) for e, _ in errs) <= 0.20,
                    "detail": detail,
                }
            )
    if "cloud_only" in {r["placement"] for r in rows}:
        low = [c for c in configs if c <= 3]
        errs = [
            abs(
                cell(h, "cloud_only", c, "loop_delay_ms")
                / PAPER_FIGURE_VALUES["loop_delay_ms"][(h, "cloud_only")][c - 1]
                - 1
            )
            for h in headsets
            for c in low
        ]
        if errs:
            checks.append(
                {
                    "claim": "Cloud-only delay within 10% of the paper for Configs 1-3",
                    "paper": "Figure 11",
                    "holds": max(errs) <= 0.10,
                    "detail": f"largest difference {max(errs):.0%}",
                }
            )
        if 5 in configs and 3 in configs:
            ratio = max(
                cell(h, "cloud_only", 5, "loop_delay_ms") / cell(h, "cloud_only", 3, "loop_delay_ms") for h in headsets
            )
            checks.append(
                {
                    "claim": "Cloud-only delay rises sharply at Configs 4-5 (paper: 4 to 20 times Config 3)",
                    "paper": "Figure 11",
                    "holds": ratio >= 4,
                    "detail": f"Config 5 is {ratio:.2f} times Config 3 here. With the published capacities no device "
                    "saturates (see utilisation), so this model has no mechanism for the rise.",
                }
            )
    return checks


@register(
    kind=PluginKind.SIMULATION,
    key="ifogsim_eeg",
    name="Case study: iFogSim EEG Tractor Beam game",
    version="0.1.0",
    status=CapabilityStatus.IMPLEMENTED,
    summary="Reproduces the latency-sensitive game case study of the iFogSim paper and compares with its figures.",
    description=(
        "Rebuilds the EEG Tractor Beam game of Gupta et al. (2017): three modules, a control loop, five "
        "network sizes, two headsets, cloud-only and edge-ward placement. Results are shown next to values "
        "measured from the paper's Figures 11 and 12, with each parameter's source listed."
    ),
    params=EEGCaseStudyParams,
    layers=["edge", "fog", "cloud"],
    outputs=["Control-loop delay", "Network usage", "Power by device class", "Agreement with the paper"],
    metrics=["loop_delay_ms", "network_usage_kb", "power_w"],
    phase=1,
    tags=["simulation", "validation", "case study", "ifogsim"],
)
class EEGCaseStudy:
    def __init__(self, params: EEGCaseStudyParams) -> None:
        self.p = params

    def run(self, progress: ProgressReporter = null_progress) -> dict[str, Any]:
        p = self.p
        settings = lambda seed: DataflowSettings(p.duration_s * 1000, p.warmup_s * 1000, seed)  # noqa: E731
        cells = [(h, pl, c) for pl in p.placements for h in p.headsets for c in p.configs]
        total, done = len(cells) * p.replications, 0
        rows = []
        for h, pl, c in cells:
            gateways = CONFIG_GATEWAYS[c]
            app = eeg_application(h)
            net = eeg_network(gateways, h, staggered=p.staggered_sensors)
            placement = eeg_placement(app, net, pl)
            runs = []
            for r in range(p.replications):
                runs.append(simulate_dataflow(app, net, placement, settings(p.base_seed + r)))
                done += 1
                progress(
                    done / total, f"Config {c}, headset {h}, {pl.replace('_', '-')}: run {r + 1} of {p.replications}"
                )
            loop_key = " -> ".join(LOOP)
            groups = sorted(runs[0]["groups"])
            rows.append(
                {
                    "headset": h,
                    "placement": pl,
                    "config": c,
                    "gateways": gateways,
                    "smartphones": gateways * PHONES_PER_GATEWAY,
                    "loop_delay_ms": _clean(summarize([x["loops"][loop_key]["mean"] for x in runs])),
                    "loop_delay_p95_ms": _clean(summarize([x["loops"][loop_key]["p95"] for x in runs])),
                    "loops_measured": sum(x["loops"][loop_key]["count"] for x in runs),
                    "network_usage_kb": _clean(summarize([x["network_usage_kb"] for x in runs])),
                    "power_w": {g: _clean(summarize([x["groups"][g]["power_w"] for x in runs])) for g in groups},
                    "energy_3h_mj": {
                        g: sum(x["groups"][g]["power_w"] for x in runs)
                        / len(runs)
                        * SIMULATED_HOURS_IN_PAPER
                        * 3600
                        / 1e6
                        for g in groups
                    },
                    "max_cpu_utilization": max(x["max_cpu_utilization"] for x in runs),
                    "busiest_device": max(runs[0]["devices"].items(), key=lambda kv: kv[1]["cpu_utilization"])[0],
                    "max_link_utilization": max(x["max_link_utilization"] for x in runs),
                    "module_hosts": {m: _host_summary(sorted(d)) for m, d in placement.items()},
                    "paper_loop_delay_ms": PAPER_FIGURE_VALUES["loop_delay_ms"][(h, pl)][c - 1],
                    "paper_network_usage_kb": PAPER_FIGURE_VALUES["network_usage_kb"][(h, pl)][c - 1],
                }
            )
        return {
            "data_origin": str(DataOrigin.SYNTHETIC),
            "kind": "simulation.case_study.ifogsim_eeg",
            "params": p.model_dump(mode="json"),
            "paper": {"citation": CITATION, "doi": "10.1002/spe.2509", "figures": "Figures 11 and 12"},
            "sources": SOURCES,
            "paper_values_note": (
                "Paper values were measured from the published bar charts (about 10 ms and 3 KB resolution); "
                "the paper does not print the numbers. Edge-ward bars are only a few pixels tall."
            ),
            "rows": rows,
            "checks": _checks(rows),
            "summary": {"cells": len(cells), "replications": p.replications, "simulated_s_per_run": p.duration_s},
        }


def _host_summary(devices: list[str]) -> str:
    if len(devices) == 1:
        name = devices[0]
        return {"d": f"WiFi gateway {name}", "m": f"smartphone {name}"}.get(name.split("-")[0], name)
    kinds = {"m": "smartphones", "d": "WiFi gateways"}
    prefix = devices[0].split("-")[0]
    return f"{len(devices)} {kinds.get(prefix, 'devices')}"
