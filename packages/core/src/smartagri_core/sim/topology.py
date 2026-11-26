"""Infrastructure model: nodes, links, routing, and a parametric farm-topology generator.

Units: MIPS per core, MB of RAM, watts, Mbit/s, milliseconds of one-way propagation latency.
"""

from __future__ import annotations

import hashlib
import heapq
import json
from enum import StrEnum
from functools import cached_property

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Layer(StrEnum):
    IOT = "iot"  # gateways that collect sensor data and drive actuators; no general compute
    EDGE = "edge"
    FOG = "fog"
    CLOUD = "cloud"


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str = ""
    layer: Layer
    cores: int = Field(1, ge=0, description="Processing cores; 0 means the node cannot run tasks")
    mips: float = Field(1000.0, ge=0, description="Million instructions per second, per core")
    ram_mb: float = Field(1024.0, ge=0)
    p_idle_w: float = Field(0.0, ge=0, description="Power draw when idle")
    p_max_w: float = Field(0.0, ge=0, description="Power draw with every core busy")
    cost_per_core_s: float = Field(0.0, ge=0, description="Monetary cost per busy core-second")
    mtbf_s: float = Field(0.0, ge=0, description="Mean time between failures; 0 disables failures")
    mttr_s: float = Field(0.0, ge=0, description="Mean time to repair")

    @property
    def can_compute(self) -> bool:
        return self.cores > 0 and self.mips > 0


class LinkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    a: str
    b: str
    kind: str = Field("ethernet", description="wifi, ethernet, 4g, 5g, lorawan, zigbee, ble, nbiot, wan")
    bandwidth_mbps: float = Field(100.0, gt=0)
    latency_ms: float = Field(1.0, ge=0)


class Topology(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = "topology"
    nodes: tuple[NodeSpec, ...]
    links: tuple[LinkSpec, ...]

    @model_validator(mode="after")
    def _validate(self) -> Topology:
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("Node ids must be unique")
        known = set(ids)
        for link in self.links:
            if link.a not in known or link.b not in known:
                raise ValueError(f"Link {link.a}-{link.b} refers to an unknown node")
            if link.a == link.b:
                raise ValueError(f"Link {link.a}-{link.b} connects a node to itself")
        return self

    # --- derived structures (cached; the model is frozen) ---------------------------------------

    @cached_property
    def node(self) -> dict[str, NodeSpec]:
        return {n.id: n for n in self.nodes}

    @cached_property
    def adjacency(self) -> dict[str, list[tuple[str, LinkSpec]]]:
        adj: dict[str, list[tuple[str, LinkSpec]]] = {n.id: [] for n in self.nodes}
        for link in self.links:
            adj[link.a].append((link.b, link))
            adj[link.b].append((link.a, link))
        return adj

    @cached_property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()

    def by_layer(self, layer: Layer) -> list[NodeSpec]:
        return [n for n in self.nodes if n.layer == layer]

    def summary(self) -> dict[str, object]:
        """Counts and capacity per layer, for display and validation."""
        layers: dict[str, dict[str, float]] = {}
        for layer in Layer:
            nodes = self.by_layer(layer)
            layers[str(layer)] = {
                "nodes": len(nodes),
                "cores": sum(n.cores for n in nodes),
                "capacity_mips": sum(n.cores * n.mips for n in nodes),
                "ram_mb": sum(n.ram_mb for n in nodes),
            }
        kinds: dict[str, int] = {}
        for link in self.links:
            kinds[link.kind] = kinds.get(link.kind, 0) + 1
        return {
            "nodes": len(self.nodes),
            "links": len(self.links),
            "layers": layers,
            "link_kinds": kinds,
            "sha256": self.sha256,
        }

    def validation_report(self) -> list[str]:
        """Human-readable problems that make a topology unusable for simulation."""
        problems: list[str] = []
        if not any(n.can_compute for n in self.nodes):
            problems.append("No node can run tasks (every node has 0 cores or 0 MIPS).")
        if not self.by_layer(Layer.IOT):
            problems.append("No IoT gateway: tasks need a source node in the 'iot' layer.")
        compute = [n.id for n in self.nodes if n.can_compute]
        router = Router(self)
        for gw in self.by_layer(Layer.IOT):
            if not any(router.reachable(gw.id, c) for c in compute):
                problems.append(f"Gateway {gw.id} cannot reach any computing node.")
        return problems


class Route(BaseModel):
    model_config = ConfigDict(frozen=True)
    hops: tuple[LinkSpec, ...]
    latency_s: float
    min_bandwidth_mbps: float


class Router:
    """Minimum-latency routing (Dijkstra) with cached routes.

    Transfer time over a route = sum over hops of (bits / bandwidth + propagation latency). Version 1 does
    not model contention between simultaneous transfers on a link (see docs/simulation-model.md).
    """

    def __init__(self, topology: Topology) -> None:
        self.topology = topology
        self._cache: dict[tuple[str, str], Route | None] = {}

    def route(self, src: str, dst: str) -> Route | None:
        key = (src, dst)
        if key not in self._cache:
            self._cache[key] = self._dijkstra(src, dst)
        return self._cache[key]

    def reachable(self, src: str, dst: str) -> bool:
        return self.route(src, dst) is not None

    def transfer_time(self, src: str, dst: str, size_bytes: float) -> float:
        if src == dst:
            return 0.0
        r = self.route(src, dst)
        if r is None:
            return float("inf")
        bits = size_bytes * 8.0
        return sum(bits / (h.bandwidth_mbps * 1e6) + h.latency_ms / 1000.0 for h in r.hops)

    def _dijkstra(self, src: str, dst: str) -> Route | None:
        if src == dst:
            return Route(hops=(), latency_s=0.0, min_bandwidth_mbps=float("inf"))
        adj = self.topology.adjacency
        dist: dict[str, float] = {src: 0.0}
        prev: dict[str, tuple[str, LinkSpec]] = {}
        heap: list[tuple[float, str]] = [(0.0, src)]
        while heap:
            d, u = heapq.heappop(heap)
            if u == dst:
                break
            if d > dist.get(u, float("inf")):
                continue
            for v, link in adj[u]:
                nd = d + link.latency_ms / 1000.0
                if nd < dist.get(v, float("inf")) - 1e-15:
                    dist[v] = nd
                    prev[v] = (u, link)
                    heapq.heappush(heap, (nd, v))
        if dst not in dist:
            return None
        hops: list[LinkSpec] = []
        cur = dst
        while cur != src:
            u, link = prev[cur]
            hops.append(link)
            cur = u
        hops.reverse()
        return Route(hops=tuple(hops), latency_s=dist[dst], min_bandwidth_mbps=min(h.bandwidth_mbps for h in hops))


# --- presets -----------------------------------------------------------------------------------

# Illustrative defaults, to be calibrated by profiling real hardware. Sources noted in docs/simulation-model.md.
DEVICE_PRESETS: dict[str, dict[str, float]] = {
    "iot": {"cores": 0, "mips": 0, "ram_mb": 0, "p_idle_w": 0.0, "p_max_w": 0.0, "cost_per_core_s": 0.0},
    "edge": {"cores": 4, "mips": 1000, "ram_mb": 4096, "p_idle_w": 2.7, "p_max_w": 6.4, "cost_per_core_s": 0.0},
    "fog": {"cores": 8, "mips": 2800, "ram_mb": 16384, "p_idle_w": 83.4, "p_max_w": 107.3, "cost_per_core_s": 0.0},
    "cloud": {
        "cores": 32,
        "mips": 4480,
        "ram_mb": 131072,
        "p_idle_w": 83.4,
        "p_max_w": 107.3,
        "cost_per_core_s": 1.2e-5,
    },
}

# Typical values per link technology, used as starting points in the topology designer. Illustrative: real
# throughput and latency depend on configuration, distance and load, and should be set from measurements.
LINK_KIND_PRESETS: dict[str, dict[str, float]] = {
    "ethernet": {"bandwidth_mbps": 100.0, "latency_ms": 1.0},
    "wifi": {"bandwidth_mbps": 20.0, "latency_ms": 5.0},
    "4g": {"bandwidth_mbps": 10.0, "latency_ms": 50.0},
    "5g": {"bandwidth_mbps": 100.0, "latency_ms": 10.0},
    "lorawan": {"bandwidth_mbps": 0.005, "latency_ms": 100.0},
    "zigbee": {"bandwidth_mbps": 0.25, "latency_ms": 15.0},
    "ble": {"bandwidth_mbps": 1.0, "latency_ms": 10.0},
    "nbiot": {"bandwidth_mbps": 0.06, "latency_ms": 1600.0},
    "wan": {"bandwidth_mbps": 50.0, "latency_ms": 100.0},
}

LINK_PRESETS: dict[str, dict[str, float | str]] = {
    "gateway_edge": {"kind": "wifi", "bandwidth_mbps": 20.0, "latency_ms": 6.0},
    "edge_fog": {"kind": "ethernet", "bandwidth_mbps": 100.0, "latency_ms": 4.0},
    "fog_cloud": {"kind": "wan", "bandwidth_mbps": 50.0, "latency_ms": 100.0},
}


class FarmTopologyParams(BaseModel):
    """Parameters for :func:`farm_topology`. Exposed as a form in the GUI."""

    model_config = ConfigDict(extra="forbid")

    farms: int = Field(4, ge=1, le=200, description="Number of farms (each with its own gateways and edge nodes).")
    gateways_per_farm: int = Field(2, ge=1, le=50, description="IoT gateways per farm; tasks originate here.")
    edge_per_farm: int = Field(1, ge=1, le=20, description="Edge computing devices per farm.")
    fog_nodes: int = Field(2, ge=1, le=50, description="Regional fog servers shared by the farms.")
    cloud_nodes: int = Field(1, ge=1, le=10, description="Cloud servers.")
    mtbf_edge_s: float = Field(
        0.0,
        ge=0,
        description="Mean time between edge failures (0 = never fail).",
        json_schema_extra={"x-unit": "s", "x-advanced": True},
    )
    mtbf_fog_s: float = Field(
        0.0,
        ge=0,
        description="Mean time between fog failures (0 = never fail).",
        json_schema_extra={"x-unit": "s", "x-advanced": True},
    )
    mttr_s: float = Field(
        300.0,
        ge=0,
        description="Mean time to repair a failed node.",
        json_schema_extra={"x-unit": "s", "x-advanced": True},
    )
    wan_bandwidth_mbps: float = Field(
        50.0,
        gt=0,
        description="Fog-to-cloud link bandwidth.",
        json_schema_extra={"x-unit": "Mbit/s", "x-advanced": True},
    )
    wan_latency_ms: float = Field(
        100.0, ge=0, description="Fog-to-cloud one-way latency.", json_schema_extra={"x-unit": "ms", "x-advanced": True}
    )


def farm_topology(p: FarmTopologyParams | None = None) -> Topology:
    """Tree-shaped farm network: gateways -> farm edge nodes -> regional fog -> cloud.

    Farms are assigned to fog nodes round-robin. Every fog node connects to every cloud node.
    """
    p = p or FarmTopologyParams()
    nodes: list[NodeSpec] = []
    links: list[LinkSpec] = []
    clouds = [f"cloud-{i + 1}" for i in range(p.cloud_nodes)]
    fogs = [f"fog-{i + 1}" for i in range(p.fog_nodes)]
    for cid in clouds:
        nodes.append(NodeSpec(id=cid, name=cid, layer=Layer.CLOUD, **DEVICE_PRESETS["cloud"]))
    for fid in fogs:
        nodes.append(
            NodeSpec(id=fid, name=fid, layer=Layer.FOG, mtbf_s=p.mtbf_fog_s, mttr_s=p.mttr_s, **DEVICE_PRESETS["fog"])
        )
        for cid in clouds:
            links.append(
                LinkSpec(a=fid, b=cid, kind="wan", bandwidth_mbps=p.wan_bandwidth_mbps, latency_ms=p.wan_latency_ms)
            )
    for f in range(p.farms):
        fog = fogs[f % len(fogs)]
        edges = [f"farm{f + 1}-edge-{e + 1}" for e in range(p.edge_per_farm)]
        for eid in edges:
            nodes.append(
                NodeSpec(
                    id=eid, name=eid, layer=Layer.EDGE, mtbf_s=p.mtbf_edge_s, mttr_s=p.mttr_s, **DEVICE_PRESETS["edge"]
                )
            )
            links.append(LinkSpec(a=eid, b=fog, **LINK_PRESETS["edge_fog"]))  # type: ignore[arg-type]
        for g in range(p.gateways_per_farm):
            gid = f"farm{f + 1}-gw-{g + 1}"
            nodes.append(NodeSpec(id=gid, name=gid, layer=Layer.IOT, cores=0, mips=0, ram_mb=0))
            links.append(LinkSpec(a=gid, b=edges[g % len(edges)], **LINK_PRESETS["gateway_edge"]))  # type: ignore[arg-type]
    return Topology(name=f"farm-{p.farms}x{p.gateways_per_farm}", nodes=tuple(nodes), links=tuple(links))
