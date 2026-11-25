"""Discrete-event simulator for agricultural IoT-edge-fog-cloud systems.

The models are documented in ``docs/simulation-model.md``. Every assumption that affects results is a
parameter, and every stochastic process draws from its own seeded stream so that comparisons between
algorithms use common random numbers.
"""

from smartagri_core.sim.engine import SimSettings, Simulator, simulate
from smartagri_core.sim.topology import Layer, LinkSpec, NodeSpec, Topology, farm_topology
from smartagri_core.sim.workload import Task, TaskClass, WorkloadSpec, generate_trace

__all__ = [
    "Layer",
    "LinkSpec",
    "NodeSpec",
    "SimSettings",
    "Simulator",
    "Task",
    "TaskClass",
    "Topology",
    "WorkloadSpec",
    "farm_topology",
    "generate_trace",
    "simulate",
]
