"""Module-based IoT application simulator following the iFogSim model (Gupta et al., 2017).

An application is a graph of modules connected by edges that carry tuples. Sensors emit tuples,
modules process them on the device that hosts them and emit new tuples according to tuple mappings
(with selectivity), some edges emit periodically, and actuators receive the final tuples. A control
loop is a path such as ``EEG -> client -> concentration_calculator -> client -> DISPLAY``; its delay is
measured from the sensor emission to the actuator receipt, as in iFogSim.

Physical model (chosen to match iFogSim so its published case studies can be reproduced):

* Devices form a tree (cloud at the root). A tuple moves hop by hop along the tree path.
* Every device has one uplink queue and one downlink queue (shared by its children). A hop takes
  ``size / bandwidth`` of transmission time in FIFO order, plus the link latency.
* A device's CPU is processor-shared: all tuples executing on it share its capacity equally,
  which is what iFogSim's time-shared module and tuple schedulers amount to.
* Sensor-to-device and device-to-actuator links add latency only.
* Power is linear between idle and busy; a device is busy while it executes any tuple.

Units follow iFogSim: time in milliseconds; CPU capacity in MIPS and tuple lengths in million
instructions, so a tuple of L MI on a device of C MIPS executes in L / C ms; tuple sizes in bytes and
bandwidth in bytes per millisecond. Network usage is iFogSim's "data rate-delay product": the sum of
latency x size over all device-to-device transfers, divided by the measured time, reported in KB.
"""

from __future__ import annotations

import heapq
import math
import random
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

# --- application and network model ----------------------------------------------------------------


@dataclass(frozen=True)
class FogDevice:
    name: str
    mips: float
    up_bw: float  # bytes per ms
    down_bw: float  # bytes per ms
    parent: str | None = None
    uplink_latency: float = 0.0  # ms, latency of the link to the parent (used in both directions)
    busy_power: float = 0.0  # W
    idle_power: float = 0.0  # W
    group: str = "fog"  # used to aggregate results, e.g. "cloud", "fog", "mobile"


@dataclass(frozen=True)
class SensorSpec:
    name: str
    device: str
    tuple_type: str
    interval: float  # ms between emissions (mean, for exponential)
    latency: float  # ms to its device
    distribution: Literal["deterministic", "exponential"] = "deterministic"
    phase: float = 0.0  # time of the first emission, ms


@dataclass(frozen=True)
class ActuatorSpec:
    name: str
    device: str
    actuator_type: str
    latency: float


@dataclass(frozen=True)
class AppEdge:
    source: str  # module name, or the sensor tuple type for sensor edges
    dest: str  # module name, or the actuator type for actuator edges
    tuple_type: str
    cpu: float  # MI needed to process the tuple at the destination module
    nw: float  # bytes
    kind: Literal["sensor", "module", "actuator"] = "module"
    period: float | None = None  # ms; set for edges that the source module emits periodically


@dataclass(frozen=True)
class TupleMapping:
    module: str
    input_type: str
    output_type: str
    selectivity: float = 1.0


@dataclass(frozen=True)
class Application:
    name: str
    modules: tuple[str, ...]
    edges: tuple[AppEdge, ...]
    mappings: tuple[TupleMapping, ...]
    loops: tuple[tuple[str, ...], ...]

    def edges_from(self, source: str, tuple_type: str) -> list[AppEdge]:
        return [e for e in self.edges if e.source == source and e.tuple_type == tuple_type]

    def sensor_edge(self, tuple_type: str) -> AppEdge:
        for e in self.edges:
            if e.kind == "sensor" and e.tuple_type == tuple_type:
                return e
        raise KeyError(f"No sensor edge for tuple type {tuple_type!r}")


@dataclass
class FogNetwork:
    devices: dict[str, FogDevice]
    sensors: list[SensorSpec]
    actuators: list[ActuatorSpec]
    children: dict[str, list[str]] = field(init=False)
    ancestors: dict[str, list[str]] = field(init=False)  # self first, root last

    def __post_init__(self) -> None:
        roots = [d.name for d in self.devices.values() if d.parent is None]
        if len(roots) != 1:
            raise ValueError(f"The device tree needs exactly one root, found {roots}")
        self.root = roots[0]
        self.children = defaultdict(list)
        for d in self.devices.values():
            if d.parent is not None:
                if d.parent not in self.devices:
                    raise ValueError(f"{d.name}: unknown parent {d.parent}")
                self.children[d.parent].append(d.name)
        self.ancestors = {}
        for name in self.devices:
            chain, cur = [], name
            while cur is not None:
                if cur in chain:
                    raise ValueError(f"Cycle in the device tree at {cur}")
                chain.append(cur)
                cur = self.devices[cur].parent
            self.ancestors[name] = chain
        for s in self.sensors:
            if s.device not in self.devices:
                raise ValueError(f"Sensor {s.name}: unknown device {s.device}")
        for a in self.actuators:
            if a.device not in self.devices:
                raise ValueError(f"Actuator {a.name}: unknown device {a.device}")

    def is_ancestor_or_self(self, a: str, b: str) -> bool:
        """True if ``a`` is ``b`` or one of its ancestors."""
        return a in self.ancestors[b]

    def next_hop(self, here: str, dest: str) -> str:
        if self.is_ancestor_or_self(here, dest):
            # dest is below: go to the child whose subtree contains it
            chain = self.ancestors[dest]
            return chain[chain.index(here) - 1]
        parent = self.devices[here].parent
        assert parent is not None
        return parent


Placement = dict[str, frozenset[str]]  # module -> devices hosting a copy


# --- placement strategies ---------------------------------------------------------------------------


def _module_order(app: Application) -> list[str]:
    """Modules in data-flow order from the sensors (cycles are cut where a module is revisited)."""
    order: list[str] = []
    frontier = [e.dest for e in app.edges if e.kind == "sensor"]
    while frontier:
        nxt = []
        for m in frontier:
            if m in order or m not in app.modules:
                continue
            order.append(m)
            nxt += [e.dest for e in app.edges if e.source == m and e.kind == "module"]
        frontier = nxt
    return order + [m for m in app.modules if m not in order]


def expected_rates(app: Application, net: FogNetwork) -> dict[tuple[str, str], float]:
    """Expected tuples per ms on each (source, tuple_type) edge, per sensor-bearing leaf device.

    Periodic edges count once per module copy (1 / period). Used by edge-ward placement to estimate
    the CPU load each module puts on a device, as iFogSim does.
    """
    leaf_sensors = defaultdict(list)
    for s in net.sensors:
        leaf_sensors[s.device].append(s)
    some_leaf = next(iter(leaf_sensors.values()), [])
    rates: dict[tuple[str, str], float] = defaultdict(float)
    for s in some_leaf:
        rates[(s.tuple_type, s.tuple_type)] += 1.0 / s.interval
    for _ in range(len(app.modules) + 2):  # propagate through the module graph
        for e in app.edges:
            if e.period:
                rates[(e.source, e.tuple_type)] = 1.0 / e.period
        for m in app.mappings:
            incoming = sum(
                r for (src, t), r in rates.items() if t == m.input_type and _edge_dest(app, src, t) == m.module
            )
            rates[(m.module, m.output_type)] = incoming * m.selectivity
    return dict(rates)


def _edge_dest(app: Application, source: str, tuple_type: str) -> str | None:
    for e in app.edges:
        if e.tuple_type == tuple_type and (e.source == source or e.kind == "sensor"):
            return e.dest
    return None


def module_load(app: Application, rates: dict[tuple[str, str], float], module: str) -> float:
    """CPU demand (MI per ms) one copy of ``module`` serving one leaf device places on its host."""
    load = 0.0
    for e in app.edges:
        if e.dest == module and e.kind in ("sensor", "module"):
            load += rates.get((e.source, e.tuple_type), 0.0) * e.cpu
    return load


def place_cloud_only(app: Application, net: FogNetwork, edge_modules: Iterable[str]) -> Placement:
    """Modules that interface with sensors and actuators stay on the sensor's device; the rest run
    in the cloud (the root). This is the ``CLOUD = true`` mapping of iFogSim's VRGameFog example."""
    edge_set = set(edge_modules)
    leaves = sorted({s.device for s in net.sensors})
    placement: Placement = {}
    for m in app.modules:
        placement[m] = frozenset(leaves) if m in edge_set else frozenset({net.root})
    return placement


def place_edge_ward(app: Application, net: FogNetwork, pinned: dict[str, str]) -> Placement:
    """iFogSim's edge-ward strategy (Algorithm 1 in Gupta et al., 2017), load based.

    For each sensor-bearing leaf, modules are taken in data-flow order and placed on the lowest device
    on the path to the cloud that is at or above their upstream module and still has CPU capacity for
    the module's expected load. A device hosting a module for several leaves runs one shared copy.
    """
    rates = expected_rates(app, net)
    used: dict[str, float] = defaultdict(float)
    hosts: dict[str, set[str]] = defaultdict(set)
    for m, dev in pinned.items():
        hosts[m].add(dev)
    order = [m for m in _module_order(app) if m not in pinned]
    for leaf in sorted({s.device for s in net.sensors}):
        path = net.ancestors[leaf]
        level_of: dict[str, int] = {}
        for m in order:
            ups = [e.source for e in app.edges if e.dest == m and e.kind == "module" and e.source in level_of]
            start = max((level_of[u] for u in ups), default=0)
            load = module_load(app, rates, m)
            for i in range(start, len(path)):
                dev = path[i]
                if used[dev] + load <= net.devices[dev].mips or i == len(path) - 1:
                    used[dev] += load
                    hosts[m].add(dev)
                    level_of[m] = i
                    break
    return {m: frozenset(hosts[m]) for m in app.modules}


# --- simulation -------------------------------------------------------------------------------------


class _Tuple:
    __slots__ = ("type", "module", "dest_device", "actuator", "cpu", "nw", "origin", "emitted", "path")

    def __init__(self, type_, module, dest_device, actuator, cpu, nw, origin, emitted, path):
        self.type = type_
        self.module = module  # destination module (None when headed to an actuator)
        self.dest_device = dest_device
        self.actuator = actuator
        self.cpu = cpu
        self.nw = nw
        self.origin = origin  # leaf device whose sensor started this chain, if any
        self.emitted = emitted  # sensor emission time of the chain, if any
        self.path = path  # sensor type and modules visited so far


class _Cpu:
    __slots__ = ("mips", "jobs", "last", "version", "busy", "mi", "next_id")

    def __init__(self, mips: float) -> None:
        self.mips = mips
        self.jobs: dict[int, list] = {}
        self.last = 0.0
        self.version = 0
        self.busy = 0.0
        self.mi = 0.0
        self.next_id = 0

    def advance(self, now: float) -> None:
        n = len(self.jobs)
        dt = now - self.last
        if n and dt > 0:
            share = self.mips * dt / n
            for job in self.jobs.values():
                job[0] -= share
            self.busy += dt
            self.mi += self.mips * dt
        self.last = now


SENSOR, ARRIVE, CPU_DONE, PERIODIC, ACTUATE, WARMUP = range(6)


@dataclass
class DataflowSettings:
    duration_ms: float = 10_000.0
    warmup_ms: float = 1_000.0
    seed: int = 1


class DataflowSim:
    def __init__(self, app: Application, net: FogNetwork, placement: Placement, settings: DataflowSettings) -> None:
        self.app, self.net, self.placement, self.s = app, net, placement, settings
        for m in app.modules:
            if not placement.get(m):
                raise ValueError(f"Module {m} is not placed on any device")
        self.rng = random.Random(settings.seed)
        self.now = 0.0
        self.events: list[tuple[float, int, int, Any]] = []
        self.seq = 0
        self.cpus = {name: _Cpu(d.mips) for name, d in net.devices.items()}
        self.free_at: dict[tuple[str, str], float] = defaultdict(float)
        self.link_busy: dict[tuple[str, str], float] = defaultdict(float)
        self.network_usage = 0.0  # sum of latency x bytes
        self.loop_delays: dict[tuple[str, ...], list[float]] = {loop: [] for loop in app.loops}
        self.executed: dict[str, int] = defaultdict(int)
        self.emitted = 0
        self._mappings = defaultdict(list)
        for mp in app.mappings:
            self._mappings[(mp.module, mp.input_type)].append(mp)
        self._edges = defaultdict(list)
        for e in app.edges:
            self._edges[(e.source, e.tuple_type)].append(e)
        self._actuators = defaultdict(list)
        for a in net.actuators:
            self._actuators[(a.device, a.actuator_type)].append(a)
        self._instance_cache: dict[tuple[str, str], str | None] = {}

    # event plumbing
    def _push(self, t: float, kind: int, payload: Any) -> None:
        self.seq += 1
        heapq.heappush(self.events, (t, self.seq, kind, payload))

    def run(self) -> dict[str, Any]:
        for i, sensor in enumerate(self.net.sensors):
            self._push(sensor.phase, SENSOR, i)
        for e in self.app.edges:
            if e.period:
                for dev in sorted(self.placement[e.source]):
                    self._push(e.period, PERIODIC, (e, dev))
        self._push(self.s.warmup_ms, WARMUP, None)
        end = self.s.duration_ms
        handlers = {
            SENSOR: self._on_sensor,
            ARRIVE: self._on_arrive,
            CPU_DONE: self._on_cpu_done,
            PERIODIC: self._on_periodic,
            ACTUATE: self._on_actuate,
            WARMUP: self._on_warmup,
        }
        while self.events and self.events[0][0] <= end:
            t, _, kind, payload = heapq.heappop(self.events)
            self.now = t
            handlers[kind](payload)
        self.now = end
        for cpu in self.cpus.values():
            cpu.advance(end)
        return self._results()

    # sensors and periodic edges
    def _on_sensor(self, idx: int) -> None:
        s = self.net.sensors[idx]
        gap = s.interval if s.distribution == "deterministic" else self.rng.expovariate(1.0 / s.interval)
        self._push(self.now + gap, SENSOR, idx)
        edge = self.app.sensor_edge(s.tuple_type)
        dest = self._instance_for(edge.dest, s.device)
        if dest is None:
            return
        self.emitted += 1
        tup = _Tuple(s.tuple_type, edge.dest, dest, None, edge.cpu, edge.nw, s.device, self.now, (s.tuple_type,))
        self._push(self.now + s.latency, ARRIVE, (s.device, tup))

    def _on_periodic(self, payload: tuple[AppEdge, str]) -> None:
        edge, dev = payload
        self._push(self.now + edge.period, PERIODIC, payload)  # type: ignore[operator]
        self._emit(edge, dev, None, (edge.source,))

    def _on_warmup(self, _: Any) -> None:
        for cpu in self.cpus.values():
            cpu.advance(self.now)
            cpu.busy = cpu.mi = 0.0
        self.network_usage = 0.0
        self.link_busy.clear()
        self.executed.clear()

    # routing
    def _instance_for(self, module: str, near: str) -> str | None:
        """The copy of ``module`` serving device ``near``: the closest one on its path to the cloud."""
        key = (module, near)
        if key not in self._instance_cache:
            hosts = self.placement[module]
            self._instance_cache[key] = next((d for d in self.net.ancestors[near] if d in hosts), None)
        return self._instance_cache[key]

    def _emit(self, edge: AppEdge, here: str, parent: _Tuple | None, path: tuple[str, ...]) -> None:
        origin = parent.origin if parent else None
        emitted = parent.emitted if parent else None
        if edge.kind == "actuator":
            for act in self._actuators.get((origin or here, edge.dest), []):
                tup = _Tuple(edge.tuple_type, None, act.device, act, 0.0, edge.nw, origin, emitted, path)
                self._route(here, tup)
            return
        if parent is None:  # periodic: to the copy above, or else to every copy below
            above = self._instance_for(edge.dest, here)
            targets = (
                [above]
                if above
                else sorted(d for d in self.placement[edge.dest] if self.net.is_ancestor_or_self(here, d))
            )
        else:
            target = (self._instance_for(edge.dest, origin) if origin else None) or self._instance_for(edge.dest, here)
            targets = [target] if target else sorted(self.placement[edge.dest])[:1]
        for dev in targets:
            tup = _Tuple(edge.tuple_type, edge.dest, dev, None, edge.cpu, edge.nw, origin, emitted, path)
            self._route(here, tup)

    def _route(self, here: str, tup: _Tuple) -> None:
        if here == tup.dest_device:
            self._deliver(here, tup)
            return
        nxt = self.net.next_hop(here, tup.dest_device)
        dev = self.net.devices[here]
        if nxt == dev.parent:
            q, bw, lat = (here, "up"), dev.up_bw, dev.uplink_latency
        else:
            q, bw, lat = (here, "down"), dev.down_bw, self.net.devices[nxt].uplink_latency
        tx = tup.nw / bw if bw > 0 else 0.0
        start = max(self.now, self.free_at[q])
        self.free_at[q] = start + tx
        self.link_busy[q] += tx
        self.network_usage += lat * tup.nw
        self._push(start + tx + lat, ARRIVE, (nxt, tup))

    def _on_arrive(self, payload: tuple[str, _Tuple]) -> None:
        here, tup = payload
        self._route(here, tup)

    def _deliver(self, here: str, tup: _Tuple) -> None:
        if tup.actuator is not None:
            self._push(self.now + tup.actuator.latency, ACTUATE, tup)
            return
        cpu = self.cpus[here]
        cpu.advance(self.now)
        cpu.next_id += 1
        cpu.jobs[cpu.next_id] = [tup.cpu, tup]
        self._reschedule(here, cpu)

    # processing
    def _reschedule(self, dev: str, cpu: _Cpu) -> None:
        cpu.version += 1
        if cpu.jobs:
            least = min(job[0] for job in cpu.jobs.values())
            self._push(self.now + max(least, 0.0) * len(cpu.jobs) / cpu.mips, CPU_DONE, (dev, cpu.version))

    def _on_cpu_done(self, payload: tuple[str, int]) -> None:
        dev, version = payload
        cpu = self.cpus[dev]
        if version != cpu.version:
            return
        cpu.advance(self.now)
        done = [jid for jid, job in cpu.jobs.items() if job[0] <= 1e-9 * max(1.0, job[1].cpu)]
        finished = [cpu.jobs.pop(jid)[1] for jid in done]
        self._reschedule(dev, cpu)
        for tup in finished:
            self._processed(dev, tup)

    def _processed(self, dev: str, tup: _Tuple) -> None:
        self.executed[tup.module] += 1
        path = (*tup.path, tup.module)
        for mp in self._mappings.get((tup.module, tup.type), []):
            if mp.selectivity >= 1.0 or self.rng.random() < mp.selectivity:
                for edge in self._edges.get((tup.module, mp.output_type), []):
                    self._emit(edge, dev, tup, path)

    def _on_actuate(self, tup: _Tuple) -> None:
        if tup.emitted is None or tup.emitted < self.s.warmup_ms:
            return
        full = (*tup.path, tup.actuator.actuator_type)
        if full in self.loop_delays:
            self.loop_delays[full].append(self.now - tup.emitted)

    # results
    def _results(self) -> dict[str, Any]:
        window = self.s.duration_ms - self.s.warmup_ms
        devices = {}
        groups: dict[str, dict[str, float]] = defaultdict(lambda: {"devices": 0, "power_w": 0.0, "busy_sum": 0.0})
        for name, d in self.net.devices.items():
            util = self.cpus[name].busy / window if window > 0 else 0.0
            power = d.idle_power + (d.busy_power - d.idle_power) * util
            devices[name] = {"group": d.group, "cpu_utilization": util, "mean_power_w": power}
            g = groups[d.group]
            g["devices"] += 1
            g["power_w"] += power
            g["busy_sum"] += util
        for g in groups.values():
            g["mean_utilization"] = g.pop("busy_sum") / g["devices"]
        links = {f"{dev}:{direction}": busy / window for (dev, direction), busy in self.link_busy.items()}
        loops = {}
        for loop, delays in self.loop_delays.items():
            loops[" -> ".join(loop)] = _describe(delays)
        return {
            "measured_ms": window,
            "loops": loops,
            "network_usage_kb": self.network_usage / window / 1000.0 if window > 0 else 0.0,
            "groups": {k: dict(v) for k, v in groups.items()},
            "devices": devices,
            "max_link_utilization": max(links.values(), default=0.0),
            "max_cpu_utilization": max((d["cpu_utilization"] for d in devices.values()), default=0.0),
            "executed": dict(self.executed),
            "sensor_tuples": self.emitted,
        }


def _describe(xs: list[float]) -> dict[str, float | int | None]:
    if not xs:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "max": None}
    s = sorted(xs)
    pick = lambda q: s[min(len(s) - 1, int(math.floor(q * (len(s) - 1) + 0.5)))]  # noqa: E731
    return {"count": len(s), "mean": sum(s) / len(s), "p50": pick(0.5), "p95": pick(0.95), "max": s[-1]}


def simulate_dataflow(
    app: Application, net: FogNetwork, placement: Placement, settings: DataflowSettings | None = None
) -> dict[str, Any]:
    return DataflowSim(app, net, placement, settings or DataflowSettings()).run()
