# Metaheuristic schedulers and the Optimization lab (Phase 4a)

This phase adds six population-based optimisers and a random-search baseline as batch schedulers, a benchmark
that compares them fairly, and the **Optimization lab** page. Everything here is implemented and runs; all
results come from simulation with synthetic workloads (`DataOrigin.SYNTHETIC`).

## The problem they solve

A batch scheduler collects the tasks that arrive during a window (5 s by default) and then assigns each one
to a node. One such decision is frozen as a `BatchProblem` (`smartagri_core.sched.batchopt`):

- **Decision:** for every task, one of its eligible nodes (up, enough memory, reachable). Each solution is
  feasible by construction: gene *i* is an index into task *i*'s list of eligible nodes.
- **Estimated finish time** of a task on a node: upload time + wait + execution + time to return the result.
  The wait uses the same fluid model as `ClusterView.estimate_finish`: the work already committed to the node,
  plus the work of tasks placed earlier in the same batch, divided by the node's total capacity.
- **Four objectives, all minimised:**

  | Objective | Meaning |
  | --- | --- |
  | Priority-weighted deadline misses | Share of tasks expected to miss their deadline, weighted critical 4, high 2, medium 1, low 0.5 |
  | Mean estimated response time | From arrival to result delivery, in seconds |
  | Dynamic energy | (P_max − P_idle) / cores × execution time, summed over tasks, in joules |
  | Cloud cost | Cost per core-second × execution time, in dollars |

- **Scalar fitness** used by the single-objective methods (and to pick one answer from NSGA-II's front):
  `1.0 × misses + 0.1 × (response / lower bound − 1) + 0.05 × energy scaled to [0, 1] + 0.05 × cost scaled to [0, 1]`.
  The weights are parameters (`w_deadline`, `w_response`, `w_energy`, `w_cost`).

These are the scheduler's **estimates**. The simulator measures what actually happens separately.

## The optimisers

All of them stop after exactly the same number of objective evaluations (the budget), use the random generator
they are given, and can start from the Min-Min and greedy MCT solutions (`seed_heuristics`, on by default).

| Key | Method | Settings |
| --- | --- | --- |
| `ga` | Genetic Algorithm | Binary tournament, uniform crossover (0.9), mutation 1/n per gene, 2 elites |
| `pso` | Particle Swarm Optimisation | Random keys, inertia 0.9 → 0.4, c1 = c2 = 2, velocity limit 0.5 |
| `aco` | Ant Colony Optimisation | MAX-MIN ant system, heuristic 1/standalone time, α = 1, β = 2, ρ = 0.1 |
| `gwo` | Grey Wolf Optimizer | Random keys, a falls from 2 to 0 over the budget |
| `woa` | Whale Optimization Algorithm | Random keys, encircling / random search / spiral (b = 1) |
| `nsga2` | NSGA-II | Non-dominated sorting and crowding over the four objectives; external archive of the front |
| `random_search` | Random search | Same budget, no learning (sanity lower bound) |

PSO, GWO and WOA are continuous methods. They search keys in [0, 1) and a key becomes a node with
`floor(key × number of eligible nodes)`. PSO uses the standard decreasing-inertia variant because the
constant-inertia version converged early on this problem (mean gap to the optimum 0.019 against 0.004 on the
brute-force test below).

Each optimiser is registered twice: as `optimizer:<key>` (the solver) and as `placement:<key>` (a batch
placement policy you can choose in Simulation and Experiments). Neither is a job on its own; the plugin page
says so instead of offering a Start button.

## Checks (tests in `packages/core/tests/test_batchopt.py`)

- Same seed gives the same mapping, for every optimiser; the budget is spent exactly; best-so-far never worsens.
- With heuristic seeding, no optimiser returns anything worse than Min-Min or greedy MCT.
- On 4-node, 7-task problems (16,384 mappings) the exact optimum is found by enumeration. With 500 evaluations
  and random starts, GA found it in 15 of 20 problems, ACO 14, NSGA-II 12, PSO 6, GWO 4, WOA 0 and random
  search 0. The test requires GA and ACO to find it in at least 6 of 10 and to beat random search on average.
- The queue model matches `ClusterView.estimate_finish` for the first task of a real captured window.
- NSGA-II's reported front contains no dominated member.
- Placements are reproducible inside the simulator; the benchmark is deterministic apart from run times.

## The benchmark (`simulation:optimizer_benchmark`)

1. The scenario is simulated once under Min-Min, and every batch decision is frozen.
2. `instances` windows with at least `min_tasks` tasks, evenly spaced through the run, become the problems.
3. Each optimiser runs on each window `replications` times with seeds derived from (seed, window, run,
   optimiser). Min-Min and greedy MCT are evaluated as fixed reference points.
4. Final fitness is compared with Friedman, Holm-corrected Wilcoxon and Vargha-Delaney A12, blocking on
   (window, run), also for misses and energy alone.

The result shows convergence curves, final fitness with 95% confidence intervals, a table per optimiser, the
NSGA-II front of the first window with every method's answer, the statistics and the windows used.

### Default results

Default farm network (4 farms, 8 gateways, 4 edge devices, 2 fog servers, 1 cloud), intensity 20, 5 s window,
one simulated hour, 6 windows of 21–28 tasks (10¹⁸ to 10²⁴ possible mappings), 10 runs each, budget 1000,
population 20, seed 1.

With heuristic seeding:

| Method | Fitness (mean ± 95% CI) | Mean rank | Gain over Min-Min | Runs better than Min-Min | Weighted misses | Energy (J) |
| --- | --- | --- | --- | --- | --- | --- |
| Min-Min | 0.357 ± 0.025 | 8.03 | – | – | 30.1% | 41.9 |
| Greedy MCT | 0.368 ± 0.030 | 7.19 | −2.3% | 50% | 31.2% | 53.8 |
| Random search | 0.346 ± 0.027 | 5.98 | 4.1% | 72% | 28.6% | 47.2 |
| GA | 0.332 ± 0.031 | 2.17 | 9.6% | 100% | 27.8% | 44.1 |
| PSO | 0.333 ± 0.031 | 4.13 | 9.4% | 83% | 27.8% | 44.1 |
| ACO | 0.332 ± 0.031 | 2.57 | 9.7% | 100% | 27.8% | 41.8 |
| GWO | 0.334 ± 0.031 | 5.26 | 9.2% | 83% | 27.8% | 44.5 |
| WOA | 0.335 ± 0.031 | 5.14 | 8.9% | 83% | 27.8% | 44.4 |
| NSGA-II | 0.333 ± 0.031 | 4.53 | 9.4% | 83% | 27.8% | 43.8 |

Friedman p < 0.001. Every optimiser, random search included, beats Min-Min significantly (Holm p < 0.001,
small effect, A12 ≈ 0.39–0.42). GA and ACO do not differ significantly from each other (p = 0.38), nor do PSO
and NSGA-II, nor GWO and WOA. Most of the gain comes in the first 100–200 evaluations.

With random starting populations (`seed_heuristics = false`), which judges the search itself: ACO ranks first
(mean rank 1.36, better than Min-Min in 98% of runs), then GA (3.13). PSO, GWO and NSGA-II beat Min-Min in only
about a third of runs, and WOA (0.1% mean gain) and random search (0.4%) barely improve on it. ACO's advantage
comes from its speed heuristic, which the other methods do not have.

Run times per decision on the development server were about 8–17 ms for the single-objective methods and
27–64 ms for NSGA-II at this budget. They depend on the computer and on what else it is doing.

### What these numbers do and don't show

- **About 28% of the priority-weighted tasks could not meet their deadline on any node** (from 7% to 45% per
  window). The cause is the batch window, not the optimiser: critical irrigation decisions have a 2-second
  deadline and wait up to 5 seconds before a batch scheduler even sees them. No batch method can fix that.
- The gains are on the scheduler's estimate. End to end they mostly disappear (next section).

## End to end in the simulator

Policy comparison, same scenario, EDF queues, 10 replications on identical workloads, optimisers at their
placement defaults (budget 400, population 20, seeded):

| Policy | Deadlines met | Urgent deadlines met | Mean response (s) | Dynamic energy (kJ) | Decision time |
| --- | --- | --- | --- | --- | --- |
| MCT (online) | 100% | 100% | 1.22 | 31.9 | 18 µs |
| Edge-ward (online) | 100% | 100% | 1.78 | 40.0 | 7 µs |
| Min-Min (batch) | 82.5% ± 0.2 | 80.2% | 3.66 | 29.4 | 4.3 ms |
| GA (batch) | 82.3% ± 0.2 | 79.9% | 3.72 | 29.2 | 5.0 ms |
| ACO (batch) | 82.4% ± 0.2 | 80.0% | 3.68 | 28.3 | 4.5 ms |
| NSGA-II (batch) | 82.3% ± 0.2 | 79.9% | 3.74 | 29.4 | 21.5 ms |

- At this load the network has spare capacity, so the simple online policies meet every deadline and every
  batch policy loses about 17% of deadlines to the window delay.
- The optimisers do **not** meet more deadlines than Min-Min end to end; their deadline rates are slightly
  lower. ACO uses about 4% less dynamic energy. The model ignores the nodes' EDF reordering and future arrivals,
  so a better estimate within one window does not guarantee a better outcome.
- The same pattern held with three times the load and a 1-second window (2 replications; online and batch
  policies all above 99.9%).

These results motivate the proposed AURA design: urgent tasks need an online path that does not wait for a
window, and batch optimisation is worth its cost only for the remaining tasks and only when nodes are congested
or objectives such as energy matter. The scenarios that create congestion (fog failure, monsoon bursts) and AURA
itself come next.

## Using it

- **Optimization lab** (Research → Optimization lab): set the scenario, optimisers, budget, windows and runs,
  then Run benchmark. Progress shows on the page; finished benchmarks can be reopened from the list.
- **Experiments**: choose `ga`, `pso`, `aco`, `gwo`, `woa`, `nsga2` or `random_search` as placements to compare
  them end to end with significance tests.
- **Command line**:

  ```powershell
  uv run smartagri plugins run simulation:optimizer_benchmark --out results\optimisers
  uv run smartagri plugins run simulation:optimizer_benchmark --set seed_heuristics=false --set replications=30 --out results\optimisers-unseeded
  ```

## Still planned

- DQN and PPO learned schedulers (catalogue entries `optimizer:dqn` and `optimizer:ppo`, Phase 4b).
- AURA, its scenarios and ablations (Phase 4c).

## References

- Holland, *Adaptation in Natural and Artificial Systems*, 1975; Goldberg, *Genetic Algorithms*, 1989.
- Kennedy and Eberhart, Particle swarm optimization, Proc. ICNN, 1995; Shi and Eberhart, A modified particle
  swarm optimizer, Proc. IEEE CEC, 1998.
- Stützle and Hoos, MAX-MIN Ant System, *Future Generation Computer Systems* 16(8), 2000.
- Mirjalili, Mirjalili and Lewis, Grey Wolf Optimizer, *Advances in Engineering Software* 69, 2014.
- Mirjalili and Lewis, The Whale Optimization Algorithm, *Advances in Engineering Software* 95, 2016.
- Deb, Pratap, Agarwal and Meyarivan, A fast and elitist multiobjective genetic algorithm: NSGA-II,
  *IEEE Transactions on Evolutionary Computation* 6(2), 2002.
- Bergstra and Bengio, Random search for hyper-parameter optimization, *JMLR* 13, 2012.
