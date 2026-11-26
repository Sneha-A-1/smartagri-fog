# Task-graph scheduling: HEFT and CPOP

Some agricultural workloads are workflows: a drone image is tiled, each tile is classified, and the results are
merged into a field map. Each step depends on earlier ones. Scheduling such a workflow on heterogeneous devices
(phone, gateway, fog server, cloud) is the classic task-graph (DAG) scheduling problem.

SmartAgri-Fog implements, in `smartagri_core.sched.dag`:

| Algorithm | Plugin | Idea |
| --- | --- | --- |
| HEFT | `scheduler:heft` | Order tasks by upward rank (mean cost plus the longest path to the exit); put each on the processor where it finishes earliest, using idle gaps |
| CPOP | `scheduler:cpop` | Put every critical-path task on the one processor that runs them fastest; other tasks where they finish earliest |
| Random | baseline | Each task on a random processor, in dependency order |

Both follow H. Topcuoglu, S. Hariri, M.-Y. Wu, *Performance-effective and low-complexity task scheduling for
heterogeneous computing*, IEEE TPDS 13(3):260–274, 2002.

## Validation

The tests (`packages/core/tests/test_dag_scheduling.py`) check the paper's worked example of 10 tasks on 3
processors:

- **Upward ranks** are 108, 77, 80, 80, 69, 63.33, 42.67, 35.67, 44.33 and 14.67, as published.
- **HEFT** produces the published schedule, of length 80.
- **CPOP** produces length 86, as published.

Every schedule is also checked for overlaps on a processor, and for tasks starting before their inputs arrive.

## Run it

- **One schedule:** Algorithm catalogue → *HEFT* (or *CPOP*) → Start job. The default is the paper's example; choose
  *random* for a generated graph. The job page shows a timeline per processor and the other schedulers' results on
  the same graph.
- **Experiment:** Algorithm catalogue → *Experiment: compare DAG schedulers*. Every algorithm schedules the same
  random graphs (30 by default). The page reports means with 95% confidence intervals, a Friedman test,
  Holm-corrected Wilcoxon pairs and A12 effect sizes, for SLR, speedup, makespan and efficiency.
- **Command line:** `uv run smartagri plugins run simulation:dag_comparison --set graphs=100 --set ccr=5 --out results\dag-ccr5`

## Random graphs

The generator follows Section 5.1 of the paper:

| Parameter | Meaning |
| --- | --- |
| `tasks` | Number of tasks |
| `alpha` | Shape: about √tasks / α levels. Small values give long chains; large values give wide, parallel graphs |
| `out_degree` | Successors per task |
| `ccr` | Communication-to-computation ratio. Above 1, moving data costs more than processing it |
| `beta` | Processor heterogeneity: each task's run time varies by ±β/2 around its mean across processors |

The same seed always gives the same graph.

## Metrics

| Metric | Definition |
| --- | --- |
| Makespan | Finish time of the last task |
| SLR | Makespan ÷ the critical path using each task's fastest processor, without communication. Never below 1 |
| Speedup | Best single-processor time ÷ makespan |
| Efficiency | Speedup ÷ number of processors |

With the defaults (50 tasks, 4 processors, CCR 1), HEFT has the lowest SLR, then CPOP, then random, as in the
paper. These graphs and costs are synthetic; mapping real farm workflows onto real devices comes with the
scheduling phase (Phase 4).
