# Simulation model (version 1, Phase 1a)

This document is the reference for the simulator in `packages/core/src/smartagri_core/sim`. It is written so
that it can be adapted into the methodology chapter of the thesis and the papers. Every number that affects
results is a parameter; defaults are illustrative and are recorded with every run.

## 1. Entities and units

| Entity | Attributes | Units |
| --- | --- | --- |
| Node | layer (iot, edge, fog, cloud), cores *k*, speed *μ* per core, RAM, idle and peak power, cost per busy core-second, MTBF, MTTR | MIPS, MB, W, $/core·s, s |
| Link | endpoints, kind, bandwidth *B*, one-way latency *d* | Mbit/s, ms |
| Task | class, priority, source gateway, arrival time *a*, length *L*, input and output size, RAM, relative deadline *D* | MI, bytes, s |

IoT gateways (layer `iot`) have no compute. Tasks originate there, and results that drive actuators return there.

## 2. Workload

For each gateway and task class, arrivals form a Poisson process with rate *λ = rate × intensity*. Lengths are
fixed, uniform (±spread) or exponential around the class mean. The full trace is generated once per seed from a
dedicated random stream and fingerprinted (SHA-256). **Every algorithm in a replication replays the same trace**
(common random numbers), so differences between algorithms are not caused by different workloads.

The default agricultural task mix (`AGRI_TASK_CLASSES`): irrigation decisions (critical, 2 s deadline), soil
analysis (high, 10 s), leaf-disease detection (high, 30 s), sensor aggregation (medium, 60 s) and yield prediction
(low, 600 s). **Its sizes and lengths are placeholders**, to be replaced in Phase 1b by values profiled from real
implementations on laptop and Raspberry-Pi-class hardware.

## 3. Network

Routes are minimum-latency paths (Dijkstra). Transferring *S* bytes over a route takes

```latex
T(S) = \sum_{h \in \text{route}} \left( \frac{8S}{B_h} + d_h \right)
```

Transfers on the same node take zero time. **Limitation (v1):** concurrent transfers do not share bandwidth
(no link contention or queueing). This favours data-heavy placements far from the source, and is listed for
Phase 1b.

Network usage follows iFogSim's definition: the sum over transfers and hops of latency × bytes, divided by
the simulated time.

## 4. Computation

Each node has *k* identical cores and is space-shared: a task occupies one core for *L / μ* seconds, without
preemption. Waiting tasks are ordered by the node's queue discipline:

| Discipline | Order |
| --- | --- |
| FCFS | Arrival time at the node |
| EDF | Absolute deadline *a + D* |
| Priority | Class (critical, high, medium, low), then arrival |
| SJF | Length *L* |

## 5. Energy and cost

While a node is up, its power is linear in utilisation (the model used by CloudSim and iFogSim):

```latex
P(t) = P_{idle} + (P_{max} - P_{idle}) \cdot \frac{\text{busy cores}(t)}{k}
```

Energy is the integral of *P(t)*. **Dynamic energy** (the second term only) is reported separately, because
idle energy depends on how long the run lasts and is the same for every algorithm. Optional transmission energy
per MB per hop is 0 by default (not modelled). Cloud cost is busy core-seconds × price.

## 6. Failures

When enabled, each computing node fails after an exponentially distributed time with mean MTBF and is repaired
after an exponential time with mean MTTR, drawn from a dedicated random stream. Tasks queued or running on a node
that fails are re-dispatched (up to `max_attempts`) or marked failed. Link failures are not modelled in v1.

## 7. Placement policies

Policies see the system only through a read-only view. They use the node backlog *W* = committed work (queued,
running and in transit) / (*k μ*), and the estimated delivery time *T_in + W + L/μ + T_out*.

| Policy | Decision |
| --- | --- |
| Random | A uniformly random eligible node (sanity lower bound) |
| Round Robin | Eligible nodes in cyclic order |
| Least Loaded | Smallest backlog *W* |
| Minimum Completion Time (MCT) | Smallest estimated delivery time |
| Cloud-only | The least-loaded cloud node (iFogSim baseline) |
| Edge-ward | First node on the route from the source to the nearest cloud with *W* ≤ threshold; the cloud otherwise. iFogSim places application modules this way at deployment time; here the rule is applied to each task. |
| Min-Min / Max-Min | Batch: every window, repeatedly assign the task whose best estimated completion is smallest (Min-Min) or largest (Max-Min), updating node backlogs as tasks are assigned |

Eligible nodes are up, can compute, have enough RAM and are reachable from the source.

Batch policies wait for the window to close, so tasks with deadlines shorter than the window can miss them
regardless of placement quality. This is a real property of batch scheduling, not a simulator artefact.

## 8. Metrics

Response time is from arrival at the gateway to delivery of the result (or to completion when there is no
result to return). A deadline is met when response time ≤ *D*; failed tasks count as missed.

Reported: completion rate, deadline success rate (all tasks and urgent tasks), mean and 95th-percentile response
time, mean queueing, execution and transfer time, total, dynamic and per-layer energy, energy per completed task,
data transferred (total and to or from the cloud), network usage, cloud cost, per-layer utilisation, load
imbalance (coefficient of variation of node utilisation), share of tasks per layer, mean scheduler decision time,
makespan and node failures.

Scheduler decision time is wall-clock time measured around each policy call. It is the only metric that is not
reproducible bit for bit. It is not added to simulated time unless `inject_overhead` is enabled.

## 9. Reproducibility

The workload, failures and randomised policies use separate streams derived from the run seed
(`numpy.random.SeedSequence`). The event queue breaks ties by insertion order. The same parameters and seed give
identical metrics and identical topology and trace fingerprints (tested).

## 10. Validation

| Check | Result |
| --- | --- |
| M/M/1 queue (λ = 0.6/s, μ = 1/s, FCFS, 4 runs of 100,000 s) | Mean response time within 4% of 1/(μ−λ) = 2.5 s and mean queueing time within 6% of ρ/(μ−λ) = 1.5 s (automated test) |
| M/M/1 at λ = 0.7/s (10 runs of 200,000 s, exploratory) | 3.358 ± 0.020 s against 3.333 s theoretical (1.3 standard errors) |
| Transfer-time formula | Exact on a two-hop example (automated test) |
| Invariants over random policies, loads, seeds and failures | Event order a ≤ arrival at node ≤ start ≤ finish ≤ delivery; execution time = L/μ; no core over-use; non-negative energy; every task completes or fails (property-based test) |
| EDF vs FCFS on an overloaded node | EDF meets more urgent deadlines (automated test) |
| Cross-simulator check against iFogSim's EEG case study | Planned for Phase 1b |

## 11. Default device and link presets

| Preset | Values | Basis |
| --- | --- | --- |
| Edge device | 4 cores × 1,000 MIPS, 4 GB, 2.7 W idle, 6.4 W peak | Raspberry-Pi-4-class device; commonly reported idle and load power. To be measured. |
| Fog server | 8 cores × 2,800 MIPS, 16 GB, 83.4 W idle, 107.3 W peak | Power values from the iFogSim case study (Gupta et al., Table II); MIPS of the same order as iFogSim examples |
| Cloud server | 32 cores × 4,480 MIPS, 128 GB, same power model, $1.2×10⁻⁵ per core-second | Illustrative |
| Gateway–edge link | Wi-Fi, 20 Mbit/s, 6 ms | Latency from iFogSim Table VI (sensor to phone) |
| Edge–fog link | Ethernet, 100 Mbit/s, 4 ms | Latency from iFogSim Table VI (gateway to ISP) |
| Fog–cloud link | WAN, 50 Mbit/s, 100 ms (configurable) | Latency from iFogSim Table VI (ISP to cloud) |

Rural connectivity in Indian farming regions may be much slower and less reliable than these defaults. The WAN
bandwidth and latency are scenario parameters precisely so that realistic values from measurement studies can be
used. Choosing and citing them is a Phase 1b task.

## 12. Known limitations of version 1

1. No bandwidth contention on links.
2. Tasks are independent: no workflow DAGs (needed for HEFT and for reproducing iFogSim's application model).
3. Nodes fail; links do not (cloud disconnection scenarios need link failures).
4. Execution time is deterministic per node (no performance interference between co-located tasks).
5. The backlog-based wait estimate used by policies is a fluid approximation.
6. Energy is linear in utilisation and ignores DVFS and sleep states.

Each limitation is a parameter or model to add in a later phase, not hidden behaviour.
