# AURA: the proposed scheduler (Phase 4d)

AURA (*Age- and Urgency-aware Reliable Allocation*, working name) is the scheduler proposed in this thesis. This
page explains what is implemented, how it is evaluated, and what the evaluation found. Everything here runs in
the platform's simulator on synthetic workloads (`DataOrigin.SYNTHETIC`). The design and the hypotheses come
from the project document (tab "Proposed algorithm: AURA").

Code: `packages/proposed/src/smartagri_proposed/aura.py` (algorithm) and `evaluation.py` (experiment).
Results file: [data/aura-evaluation-phase4d.json](data/aura-evaluation-phase4d.json).

## What AURA does

**Tier 1, urgent tasks (online, on arrival).** Critical and high-priority tasks are placed the moment they arrive.

- For every eligible node, AURA estimates the finish time F. It adds up four parts:
  - upload time;
  - the wait for a free core;
  - urgent work already queued there (urgent tasks overtake queued strategic ones);
  - execution, plus the return to the actuator.
- It scores each node with p · V(F) − α·w·E/E_max − β·w·C/C_max:
  - p is the probability the placement succeeds. It comes from failures observed so far, starting from an assumed one failure per day.
  - V is the decision value of finishing at F.
  - E and C are the placement's energy and cloud cost; α = β = 0.02.
- The decision value V uses the **effective deadline** D = min(deadline, data time + freshness bound). A task is worth its full weight w if it finishes by D (critical 4, high 2, medium 1, low 0.5). After D its value halves every deadline-length, and it is worth nothing after three deadline-lengths.
- **Replication.** A critical task is replicated when its best placement has p < 0.95. The second copy goes to the best node on another layer. Whichever copy delivers first counts, and the other copy is cancelled.

**Tier 2, strategic tasks (every 5-second window).** Medium and low-priority tasks wait for the window.

- NSGA-II maps them (300 evaluations, population 20), seeded with Min-Min, greedy MCT and edge-ward solutions.
- Energy and cost count more than in Tier 1 (weights 0.3 each).
- The planner only uses capacity not reserved for urgent work: a node with share r reserved looks 1 − r as fast to it.
- Tasks with no reachable node wait for the next window while their deadline allows (store and forward).

**Anticipatory reservation (every 60 s).** For each farm region, meaning an edge device and its gateways:

- demand = smoothed urgent arrival rate × (1 + κ × share of the region's gateways under an active early warning) × mean urgent task length, with κ = 3;
- the edge device reserves that share of its capacity, between 0 and 60%;
- demand beyond that is reserved on the region's fog server.

**Queue discipline** (`queue_discipline:aura`): urgent tasks before strategic ones, then earliest effective deadline.

Each decision records its score terms. The evaluation page shows sample decisions ("why this node?") and the
reservation timeline.

**Not implemented** (so not claimed): preempting a running strategic task, and switching to a registered light
variant of a task. Urgent tasks overtake *queued* strategic work through the queue discipline instead.

### Ablations

| Placement key | What is removed |
| --- | --- |
| `aura_noaoi` | Effective deadline uses the stated deadline only (queue `urgent_edf`). |
| `aura_noreserve` | No reservation. |
| `aura_staticreserve` | A fixed 30% reservation; early warnings ignored. |
| `aura_noreliability` | p = 1 and no replication. |
| `aura_singletier` | Tier 1 places every task; no NSGA-II tier. |

To check that AURA's gains are not only its queue discipline, the evaluation also runs **MCT with AURA's
queue** (`mct@aura`).

## Engine additions this needed

- **Hybrid placement.** A policy can place some tasks online and defer others to the batch window (`Placement.defer`).
- **Store and forward.** A batch policy can return `DEFER` to keep a task waiting.
- **Replication.** `place` may return several nodes. The first copy to deliver completes the task, the others are cancelled, and only original tasks count in the metrics. The new metric "replicated tasks" counts the copies.
- **New information for policies.** Policies can now see the urgent backlog per node, the time until a core is free, and the failures observed per node.

Existing policies give bit-for-bit identical results after these changes (checked with failures and outages).

## How it was evaluated

`simulation:aura_evaluation`, default settings:

- the default farm network: 4 farms, 8 gateways, 4 edge devices, 2 fog servers, 1 cloud;
- intensity 100 (busy season) and 30 simulated minutes per run;
- **10 seeded workloads per scenario**, the same for every algorithm;
- 13 algorithms × 5 scenarios = **650 simulations**.

Each other algorithm is compared with AURA by a paired Wilcoxon signed-rank test, Holm-corrected over the 12
comparisons, with the Vargha–Delaney A12 effect size. In the tables:

- ▼ means AURA is significantly better than that algorithm on that metric;
- ▲ means that algorithm is significantly better than AURA.

Values are mean ± 95% confidence interval.

### Normal load with data freshness

| Algorithm | Urgent deadlines met (%) | Stale decisions (%) | Decision value (%) | 95th pct response (s) | Dynamic energy (kJ) | Cloud cost ($) | Autonomy (%) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **AURA (proposed)** | 99.95 ± 0.03 | 1.03 ± 0.02 | 99.96 ± 0.00 | 8.01 ± 0.11 | 95.08 ± 1.38 | 0.233 ± 0.011 | 73.15 ± 0.59 |
| AURA without AoI | 99.96 ± 0.02 | 1.91 ± 0.05 ▼ | 99.85 ± 0.01 ▼ | 8.39 ± 0.12 ▼ | 99.86 ± 1.50 ▼ | 0.219 ± 0.010 ▲ | 75.58 ± 0.56 ▲ |
| AURA without reservation | 99.97 ± 0.02 | 1.04 ± 0.02 | 99.96 ± 0.00 | 8.06 ± 0.07 | 94.51 ± 1.24 ▲ | 0.236 ± 0.011 ▼ | 73.30 ± 0.58 |
| AURA with static reservation | 99.94 ± 0.03 | 1.03 ± 0.03 | 99.96 ± 0.00 | 8.06 ± 0.09 | 95.01 ± 1.30 | 0.234 ± 0.011 | 73.11 ± 0.46 |
| AURA without reliability | 99.93 ± 0.03 | 1.03 ± 0.02 | 99.96 ± 0.00 | 8.03 ± 0.07 | 95.29 ± 1.40 | 0.233 ± 0.011 | 73.18 ± 0.49 |
| AURA single tier | 97.41 ± 0.24 ▼ | 1.25 ± 0.07 ▼ | 99.50 ± 0.08 ▼ | 14.08 ± 0.54 ▼ | 145.7 ± 1.9 ▼ | 0.077 ± 0.010 ▲ | 49.51 ± 0.83 ▼ |
| MCT | 99.99 ± 0.01 | 2.67 ± 0.07 ▼ | 99.78 ± 0.01 ▼ | 8.37 ± 0.18 ▼ | 99.05 ± 1.46 ▼ | 0.219 ± 0.010 ▲ | 99.83 ± 0.04 ▲ |
| MCT + AURA queue | 99.98 ± 0.01 | 2.02 ± 0.04 ▼ | 99.85 ± 0.00 ▼ | 8.30 ± 0.16 ▼ | 99.06 ± 1.46 ▼ | 0.219 ± 0.010 ▲ | 99.83 ± 0.04 ▲ |
| Edge-ward | 100.0 ± 0.0 ▲ | 1.00 ± 0.03 ▲ | 99.95 ± 0.00 ▼ | 4.65 ± 0.04 ▲ | 47.10 ± 0.67 ▲ | 0.382 ± 0.012 ▼ | 14.19 ± 0.85 ▼ |
| Cloud-only | 100.0 ± 0.0 ▲ | 0.93 ± 0.03 ▲ | 99.96 ± 0.00 ▲ | 4.57 ± 0.04 ▲ | 27.62 ± 0.75 ▲ | 0.444 ± 0.012 ▼ | 0.00 ± 0.00 ▼ |
| Least loaded | 99.94 ± 0.02 | 1.34 ± 0.04 ▼ | 99.90 ± 0.01 ▼ | 5.28 ± 0.07 ▲ | 65.37 ± 1.45 ▲ | 0.326 ± 0.011 ▼ | 26.71 ± 0.96 ▼ |
| Min-Min (batch) | 77.37 ± 0.21 ▼ | 7.39 ± 0.10 ▼ | 85.86 ± 0.12 ▼ | 9.67 ± 0.25 ▼ | 98.06 ± 1.67 ▼ | 0.227 ± 0.010 ▲ | 99.31 ± 0.10 ▲ |
| NSGA-II (batch) | 76.55 ± 0.30 ▼ | 7.70 ± 0.15 ▼ | 85.07 ± 0.23 ▼ | 9.87 ± 0.28 ▼ | 97.15 ± 1.58 ▼ | 0.229 ± 0.010 ▲ | 99.07 ± 0.12 ▲ |

### Monsoon burst

| Algorithm | Urgent deadlines met (%) | Stale decisions (%) | Decision value (%) | 95th pct response (s) | Dynamic energy (kJ) | Cloud cost ($) | Autonomy (%) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **AURA (proposed)** | 99.78 ± 0.24 | 1.12 ± 0.10 | 99.79 ± 0.26 | 8.78 ± 1.25 | 110.2 ± 1.3 | 0.338 ± 0.012 | 36.51 ± 0.36 |
| AURA without AoI | 99.80 ± 0.26 | 1.94 ± 0.16 ▼ | 99.64 ± 0.30 ▼ | 9.70 ± 2.01 ▼ | 113.6 ± 1.3 ▼ | 0.328 ± 0.012 ▲ | 37.32 ± 0.32 ▲ |
| AURA without reservation | 99.88 ± 0.06 | 1.15 ± 0.08 | 99.89 ± 0.06 | 8.65 ± 0.80 | 110.4 ± 1.3 | 0.338 ± 0.012 | 36.24 ± 0.34 |
| AURA with static reservation | 99.87 ± 0.13 | 1.11 ± 0.06 | 99.89 ± 0.11 | 8.55 ± 0.88 | 110.3 ± 1.3 | 0.338 ± 0.012 | 36.36 ± 0.39 |
| AURA without reliability | 99.80 ± 0.26 | 1.11 ± 0.09 | 99.82 ± 0.26 | 8.81 ± 1.31 | 110.2 ± 1.2 | 0.338 ± 0.012 | 36.56 ± 0.41 |
| AURA single tier | 98.68 ± 0.14 ▼ | 1.12 ± 0.03 | 99.72 ± 0.04 | 10.85 ± 0.53 ▼ | 154.5 ± 1.1 ▼ | 0.202 ± 0.013 ▲ | 25.21 ± 1.00 ▼ |
| MCT | 71.11 ± 4.13 ▼ | 12.25 ± 2.51 ▼ | 75.90 ± 2.48 ▼ | 22.27 ± 3.59 ▼ | 113.2 ± 1.3 ▼ | 0.328 ± 0.012 ▲ | 91.65 ± 0.77 ▲ |
| MCT + AURA queue | 77.84 ± 1.12 ▼ | 8.80 ± 1.85 ▼ | 79.85 ± 2.02 ▼ | 19.88 ± 3.62 ▼ | 113.2 ± 1.3 ▼ | 0.328 ± 0.012 ▲ | 91.66 ± 0.65 ▲ |
| Edge-ward | 99.64 ± 0.30 | 2.00 ± 0.31 ▼ | 99.68 ± 0.19 | 12.05 ± 1.92 ▼ | 56.01 ± 0.89 ▲ | 0.506 ± 0.013 ▼ | 10.73 ± 0.54 ▼ |
| Cloud-only | 76.99 ± 9.72 ▼ | 8.39 ± 2.59 ▼ | 87.22 ± 5.33 ▼ | 26.36 ± 4.59 ▼ | 35.52 ± 0.83 ▲ | 0.571 ± 0.013 ▼ | 0.00 ± 0.00 ▼ |
| Least loaded | 98.48 ± 0.89 ▼ | 2.37 ± 0.28 ▼ | 99.24 ± 0.40 ▼ | 9.77 ± 1.89 | 83.28 ± 1.80 ▲ | 0.423 ± 0.011 ▼ | 25.66 ± 1.07 ▼ |
| Min-Min (batch) | 59.26 ± 3.83 ▼ | 13.81 ± 2.04 ▼ | 71.04 ± 3.01 ▼ | 19.18 ± 3.22 ▼ | 112.3 ± 1.4 ▼ | 0.334 ± 0.012 ▲ | 91.59 ± 0.84 ▲ |
| NSGA-II (batch) | 59.17 ± 4.06 ▼ | 14.05 ± 2.38 ▼ | 71.42 ± 3.73 ▼ | 19.13 ± 3.64 ▼ | 111.2 ± 1.8 ▼ | 0.336 ± 0.011 | 90.37 ± 0.66 ▲ |

### Heat wave

| Algorithm | Urgent deadlines met (%) | Stale decisions (%) | Decision value (%) | 95th pct response (s) | Dynamic energy (kJ) | Cloud cost ($) | Autonomy (%) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **AURA (proposed)** | 99.94 ± 0.02 | 1.05 ± 0.02 | 99.95 ± 0.01 | 8.31 ± 0.14 | 117.7 ± 1.1 | 0.344 ± 0.011 | 28.38 ± 0.53 |
| AURA without AoI | 99.97 ± 0.01 | 1.80 ± 0.05 ▼ | 99.83 ± 0.01 ▼ | 9.26 ± 0.27 ▼ | 120.1 ± 1.1 ▼ | 0.336 ± 0.011 ▲ | 26.67 ± 0.25 ▼ |
| AURA without reservation | 99.83 ± 0.05 ▼ | 1.27 ± 0.06 ▼ | 99.85 ± 0.02 ▼ | 9.66 ± 0.59 ▼ | 118.4 ± 1.2 ▼ | 0.342 ± 0.010 ▲ | 27.19 ± 0.57 ▼ |
| AURA with static reservation | 99.88 ± 0.03 ▼ | 1.15 ± 0.05 ▼ | 99.90 ± 0.01 ▼ | 8.78 ± 0.21 ▼ | 118.1 ± 1.1 ▼ | 0.343 ± 0.011 ▲ | 27.67 ± 0.55 ▼ |
| AURA without reliability | 99.92 ± 0.04 | 1.05 ± 0.03 | 99.94 ± 0.01 | 8.36 ± 0.16 | 117.7 ± 1.1 | 0.344 ± 0.011 | 28.38 ± 0.55 |
| AURA single tier | 99.03 ± 0.16 ▼ | 1.08 ± 0.05 | 99.79 ± 0.04 ▼ | 12.30 ± 0.50 ▼ | 156.0 ± 1.1 ▼ | 0.226 ± 0.011 ▲ | 18.85 ± 0.57 ▼ |
| MCT | 68.10 ± 1.10 ▼ | 9.86 ± 0.63 ▼ | 77.47 ± 1.58 ▼ | 21.22 ± 1.57 ▼ | 120.0 ± 1.1 ▼ | 0.336 ± 0.011 ▲ | 94.43 ± 0.44 ▲ |
| MCT + AURA queue | 81.29 ± 2.10 ▼ | 5.99 ± 0.45 ▼ | 89.60 ± 1.50 ▼ | 17.00 ± 0.89 ▼ | 120.0 ± 1.1 ▼ | 0.336 ± 0.011 ▲ | 94.36 ± 0.43 ▲ |
| Edge-ward | 99.99 ± 0.02 ▲ | 1.40 ± 0.19 ▼ | 99.92 ± 0.03 ▼ | 6.46 ± 1.61 | 57.87 ± 0.68 ▲ | 0.529 ± 0.012 ▼ | 10.68 ± 0.54 ▼ |
| Cloud-only | 99.90 ± 0.16 | 1.91 ± 0.11 ▼ | 99.85 ± 0.04 ▼ | 12.34 ± 1.24 ▼ | 37.02 ± 0.72 ▲ | 0.595 ± 0.012 ▼ | 0.00 ± 0.00 ▼ |
| Least loaded | 99.79 ± 0.06 ▼ | 1.57 ± 0.06 ▼ | 99.82 ± 0.03 ▼ | 5.44 ± 0.10 ▲ | 83.31 ± 1.20 ▲ | 0.451 ± 0.012 ▼ | 24.04 ± 1.06 ▼ |
| Min-Min (batch) | 60.69 ± 1.28 ▼ | 11.95 ± 0.58 ▼ | 74.61 ± 1.50 ▼ | 17.53 ± 1.37 ▼ | 118.9 ± 1.3 ▼ | 0.342 ± 0.010 ▲ | 95.35 ± 0.22 ▲ |
| NSGA-II (batch) | 66.90 ± 1.66 ▼ | 11.25 ± 0.50 ▼ | 76.95 ± 1.34 ▼ | 16.54 ± 1.20 ▼ | 117.0 ± 1.3 | 0.348 ± 0.011 ▼ | 92.85 ± 0.66 ▲ |

### Cloud disconnection

| Algorithm | Urgent deadlines met (%) | Stale decisions (%) | Decision value (%) | 95th pct response (s) | Dynamic energy (kJ) | Cloud cost ($) | Autonomy (%) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **AURA (proposed)** | 94.45 ± 1.04 | 4.27 ± 0.65 | 95.39 ± 0.96 | 45.42 ± 5.90 | 129.0 ± 2.7 | 0.125 ± 0.006 | 83.25 ± 0.83 |
| AURA without AoI | 95.79 ± 1.01 | 4.88 ± 0.53 | 96.08 ± 1.14 | 45.45 ± 5.28 | 131.1 ± 2.8 ▼ | 0.118 ± 0.006 ▲ | 83.86 ± 0.57 |
| AURA without reservation | 95.19 ± 1.22 | 4.12 ± 0.88 | 95.84 ± 1.43 | 43.74 ± 8.09 | 129.4 ± 2.7 | 0.123 ± 0.006 | 83.72 ± 0.77 |
| AURA with static reservation | 93.88 ± 1.25 | 4.53 ± 0.65 | 94.72 ± 0.98 | 42.61 ± 3.92 | 129.3 ± 2.7 | 0.124 ± 0.006 | 83.40 ± 0.84 |
| AURA without reliability | 94.46 ± 1.23 | 4.05 ± 0.59 | 95.62 ± 1.05 | 43.72 ± 5.46 | 128.9 ± 2.8 | 0.125 ± 0.006 | 82.78 ± 0.72 |
| AURA single tier | 85.60 ± 1.38 ▼ | 9.43 ± 0.64 ▼ | 90.32 ± 1.19 ▼ | 192.2 ± 59.2 ▼ | 148.4 ± 2.0 ▼ | 0.069 ± 0.009 ▲ | 77.87 ± 1.22 ▼ |
| MCT | 56.21 ± 0.46 ▼ | 41.77 ± 0.48 ▼ | 57.86 ± 0.37 ▼ | 427.1 ± 37.2 ▼ | 118.4 ± 3.1 ▲ | 0.164 ± 0.006 ▼ | 75.45 ± 0.44 ▼ |
| MCT + AURA queue | 55.93 ± 0.27 ▼ | 42.10 ± 0.54 ▼ | 57.46 ± 0.36 ▼ | 365.8 ± 101.1 ▼ | 118.4 ± 3.0 ▲ | 0.164 ± 0.006 ▼ | 75.49 ± 0.47 ▼ |
| Edge-ward | 65.76 ± 2.16 ▼ | 20.90 ± 1.39 ▼ | 73.32 ± 2.02 ▼ | 94.82 ± 12.51 ▼ | 105.7 ± 2.9 ▲ | 0.204 ± 0.007 ▼ | 53.79 ± 0.32 ▼ |
| Cloud-only | 49.96 ± 0.21 ▼ | 50.53 ± 0.22 ▼ | 49.91 ± 0.23 ▼ | 4.55 ± 0.05 ▲ | 13.70 ± 0.40 ▲ | 0.220 ± 0.006 ▼ | 0.00 ± 0.00 ▼ |
| Least loaded | 67.71 ± 1.69 ▼ | 19.63 ± 1.22 ▼ | 75.21 ± 1.78 ▼ | 92.94 ± 11.36 ▼ | 110.6 ± 2.9 ▲ | 0.189 ± 0.007 ▼ | 57.41 ± 0.67 ▼ |
| Min-Min (batch) | 43.10 ± 0.43 ▼ | 44.78 ± 0.46 ▼ | 49.52 ± 0.37 ▼ | 422.3 ± 33.9 ▼ | 117.8 ± 3.1 ▲ | 0.167 ± 0.006 ▼ | 75.09 ± 0.61 ▼ |
| NSGA-II (batch) | 48.03 ± 3.02 ▼ | 25.41 ± 2.25 ▼ | 61.50 ± 3.07 ▼ | 74.05 ± 9.48 ▼ | 121.1 ± 2.4 ▲ | 0.153 ± 0.007 ▼ | 81.95 ± 1.48 |

### Fog server failure

| Algorithm | Urgent deadlines met (%) | Stale decisions (%) | Decision value (%) | 95th pct response (s) | Dynamic energy (kJ) | Cloud cost ($) | Autonomy (%) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **AURA (proposed)** | 99.90 ± 0.03 | 1.04 ± 0.03 | 99.95 ± 0.01 | 8.94 ± 0.17 | 92.20 ± 1.20 | 0.242 ± 0.011 | 73.16 ± 0.94 |
| AURA without AoI | 99.90 ± 0.05 | 2.24 ± 0.06 ▼ | 99.78 ± 0.01 ▼ | 10.82 ± 0.42 ▼ | 95.19 ± 1.28 ▼ | 0.233 ± 0.011 ▲ | 72.13 ± 1.10 ▼ |
| AURA without reservation | 99.73 ± 0.07 ▼ | 1.48 ± 0.08 ▼ | 99.74 ± 0.03 ▼ | 10.83 ± 0.39 ▼ | 92.94 ± 1.17 ▼ | 0.239 ± 0.011 ▲ | 72.06 ± 1.19 ▼ |
| AURA with static reservation | 99.78 ± 0.07 ▼ | 1.23 ± 0.06 ▼ | 99.85 ± 0.02 ▼ | 10.04 ± 0.26 ▼ | 92.68 ± 1.16 ▼ | 0.240 ± 0.011 ▲ | 72.54 ± 1.02 ▼ |
| AURA without reliability | 99.87 ± 0.04 | 1.05 ± 0.02 ▼ | 99.95 ± 0.01 | 8.51 ± 0.15 ▲ | 91.41 ± 1.28 ▲ | 0.244 ± 0.011 ▼ | 65.16 ± 0.79 ▼ |
| AURA single tier | 93.24 ± 0.73 ▼ | 2.24 ± 0.30 ▼ | 98.13 ± 0.40 ▼ | 19.47 ± 1.93 ▼ | 125.9 ± 0.9 ▼ | 0.137 ± 0.012 ▲ | 47.31 ± 1.04 ▼ |
| MCT | 99.95 ± 0.04 | 3.15 ± 0.15 ▼ | 99.72 ± 0.02 ▼ | 13.14 ± 1.47 ▼ | 94.38 ± 1.23 ▼ | 0.233 ± 0.011 ▲ | 98.99 ± 0.12 ▲ |
| MCT + AURA queue | 99.98 ± 0.01 ▲ | 2.18 ± 0.07 ▼ | 99.82 ± 0.02 ▼ | 12.28 ± 1.53 ▼ | 94.39 ± 1.24 ▼ | 0.233 ± 0.011 ▲ | 99.00 ± 0.11 ▲ |
| Edge-ward | 100.0 ± 0.0 ▲ | 0.99 ± 0.03 ▲ | 99.95 ± 0.00 | 4.64 ± 0.04 ▲ | 44.98 ± 0.68 ▲ | 0.389 ± 0.012 ▼ | 12.74 ± 0.82 ▼ |
| Cloud-only | 100.0 ± 0.0 ▲ | 0.93 ± 0.03 ▲ | 99.96 ± 0.00 ▲ | 4.57 ± 0.04 ▲ | 27.62 ± 0.75 ▲ | 0.444 ± 0.012 ▼ | 0.00 ± 0.00 ▼ |
| Least loaded | 99.91 ± 0.04 | 1.35 ± 0.05 ▼ | 99.88 ± 0.01 ▼ | 5.27 ± 0.06 ▲ | 61.26 ± 1.35 ▲ | 0.339 ± 0.013 ▼ | 23.99 ± 1.73 ▼ |
| Min-Min (batch) | 76.49 ± 0.34 ▼ | 8.01 ± 0.15 ▼ | 84.99 ± 0.24 ▼ | 11.00 ± 0.46 ▼ | 92.58 ± 1.53 | 0.242 ± 0.010 | 98.57 ± 0.08 ▲ |
| NSGA-II (batch) | 75.02 ± 0.75 ▼ | 8.38 ± 0.20 ▼ | 83.82 ± 0.40 ▼ | 11.06 ± 0.48 ▼ | 91.33 ± 1.26 ▲ | 0.245 ± 0.011 ▼ | 97.67 ± 0.38 ▲ |

## What the evaluation shows

**H1: AURA raises urgent deadline success and freshness compliance over the baselines under burst and failure scenarios.**
Verdict: **mixed.**

- **Cloud disconnection: supported.** AURA met 94.5% of urgent deadlines. The best baseline, least-loaded, met 67.7%. Stale decisions fell from 19.6% to 4.3%, and AURA was significantly better than every baseline on both.
- **Monsoon burst: partly supported.** AURA was significantly better than every baseline except edge-ward on urgent deadlines (no significant difference, 99.8% against 99.6%). It had half of edge-ward's stale decisions.
- **Heat wave: not supported.** Edge-ward met slightly more urgent deadlines (99.99% against 99.94%, significant).
- **Fog failure: not supported.** Edge-ward and cloud-only met all urgent deadlines and had slightly fewer stale decisions. MCT with AURA's queue also met slightly more urgent deadlines. In this network the cloud absorbs the lost fog capacity easily.
- **The cost of those gains** is that AURA uses about twice the dynamic energy of edge-ward, which runs most work in the more efficient cloud. On the other hand, AURA's cloud cost is 35–40% lower.

**H2: anticipatory reservation beats static reservation during surges.** Verdict: **mixed.**

- **Heat wave: supported.** AURA beat AURA with static reservation on urgent deadlines (A12 0.90) and decision value (A12 0.99).
- **Monsoon burst: inconclusive.** There was no significant difference.
- **Caution in interpreting this.** The reservation timeline shows AURA's reservation reaches its 60% ceiling on edge devices from the start, and on fog servers within minutes, in every scenario. Urgent demand at this load already exceeds edge capacity. So the heat-wave result may come from reserving *more*, not from reserving *earlier*. A static reservation at 60% would separate the two; it has not been run yet. Until it is, the anticipation claim is not established.

**H3: under cloud disconnection AURA completes more urgent work locally.** Verdict: **partly supported.**

- AURA's autonomy ratio was 83.3%, significantly higher than every baseline except NSGA-II (82.0%, no significant difference).
- In AURA, that local work also met its deadlines (94.5%). NSGA-II met only 48%.

**H4: the strategic tier lowers energy and cost compared with single-tier AURA and edge-ward placement without hurting urgent deadlines.** Verdict: **not supported** as stated.

- Against single-tier AURA, the strategic tier cut energy by 13–35% and *raised* urgent deadline success in every scenario (by up to 9 points under cloud disconnection). However, it raised cloud cost by 50% to 200%, because the reservation pushes strategic work to the cloud.
- Against edge-ward, AURA uses more energy but has lower cost.
- So the tier trades cloud cost for energy and urgent performance, rather than lowering both.

**Other findings**

- **Data freshness matters.** Without the AoI term, AURA made 70–115% more stale decisions in the normal, heat-wave, monsoon and fog-failure scenarios, with lower decision value. All of those differences are significant. Under cloud disconnection the difference was not significant.
- **AURA's queue alone is not enough.** MCT with AURA's queue improved on plain MCT in the heat wave (68% → 81% urgent deadlines) but stayed far below AURA. The placement rule carries most of the gain.
- **Reliability weighting mattered only after a failure.** In the fog-failure scenario, AURA without reliability kept 8 points less urgent work local. Elsewhere it made no difference. No task was ever replicated: with an assumed one failure per day and second-long tasks, success probability never fell below 0.95. Replication is implemented and tested, but these scenarios do not exercise it.
- **Batch schedulers fail urgent work at this load.** Min-Min and NSGA-II met only 59–77% of urgent deadlines even under normal load: the 5-second window delays tasks with 2-second deadlines.
- **Run time per 30-minute simulation** on the development server: AURA 6.8 s, MCT 1.6 s, edge-ward 1.1 s, NSGA-II (batch) 20 s, Min-Min 56 s. AURA's mean scheduling decision (both tiers, per task or window) takes 95–145 µs, against 15 µs for MCT.

## Limitations

- **All workloads are synthetic.** Task sizes, freshness bounds, surge shapes and warning accuracy are assumptions (see [scenarios.md](scenarios.md)).
- **One network and one load level (intensity 100).** Results at other sizes and loads may differ.
- **Reservation saturates at its 60% ceiling at this load**, so this evaluation cannot separate anticipation from reservation level (see H2).
- **Ten workloads per scenario.** That is enough for the large differences, but use 30 for the paper.
- **Some components are not exercised or not built.** Replication was never triggered, and preemption and light variants are not implemented.
- **α and β are design choices.** α = β = 0.02 makes cloud cost and local energy weigh the same relative to the most expensive candidate. Other weights would move AURA along the energy–cost trade-off.

## Running it yourself

- **In the platform:** go to **Research → Performance evaluation**, choose scenarios and algorithms, and click Run evaluation. With the defaults it takes roughly 30–60 minutes on a laptop.
- **For the paper (30 workloads):** run it overnight from PowerShell, one scenario at a time, so a restart loses little:

```powershell
cd D:\dev\smartagri-fog
foreach ($s in "normal","monsoon_burst","heat_wave","cloud_disconnection","fog_failure") {
  Set-Content -Path "aura-$s.json" -Value ('{"replications": 30, "scenarios": ["' + $s + '"]}')
  uv run smartagri plugins run simulation:aura_evaluation --params "aura-$s.json" --out "results\aura-$s"
}
```

Each folder then holds a `result.json` with the tables, tests, hypothesis verdicts and AURA's internal log.
