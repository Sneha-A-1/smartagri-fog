# Stress scenarios, data freshness and the new metrics (Phase 4c)

AURA is designed for situations that ordinary load does not create: data that goes stale, correlated
emergencies that can be partly predicted, and losing the cloud or a fog server. This phase adds those
situations to the simulator so that every scheduler, not only AURA, can be evaluated in them. All of it is
implemented and runs on synthetic workloads (`DataOrigin.SYNTHETIC`). The event timings and rates below are
**modelling assumptions**. They are recorded with every result.

## Choosing a scenario

Every simulation form (single run, policy comparison, Experiments) now has a **Scenario** field. On the
command line it is called `stress`:

```powershell
uv run smartagri plugins run simulation:comparison --set stress=monsoon_burst --set intensity=100 --out results\monsoon
```

| Scenario | What changes |
| --- | --- |
| `none` (default) | The original workload, without data timestamps. Earlier results reproduce exactly: the default trace still has the same SHA-256 hash. |
| `normal` | Same arrivals, but every task carries the age of its input data and a freshness bound (table below). |
| `monsoon_burst` | Urgent tasks arrive 6× faster for up to 20 minutes, starting at 40% of the run, on half of the gateways (one area). Early warnings: 60% of affected gateways warned 5 to 30 minutes ahead, 39% of all warnings true. |
| `heat_wave` | Urgent tasks arrive 2.5× faster on every gateway for the middle half of the run. A forecast warns 90% of gateways 10 to 30 minutes ahead and is right 80% of the time. |
| `cloud_disconnection` | The cloud is unreachable for 30 minutes (or half the run, if shorter), starting at 25% of the run. |
| `fog_failure` | The first fog server is down for 20 minutes (or a third of the run), starting at 30% of the run. |

All scenarios except `none` include the data-freshness bounds. Event times are fractions of the run's length,
so a scenario works for any duration.

The warning accuracy of the monsoon burst is taken from the data retrieval framework's own measured results
(60% of events warned early, 39% of warnings true; see [retrieval-framework.md](retrieval-framework.md)). The
heat-wave forecast accuracy is an assumption.

### Data freshness (Age of Information)

| Task class | Input age when the task arrives | Freshness bound |
| --- | --- | --- |
| Irrigation decision (critical, 2 s deadline) | 0–30 s (soil probe reports every 30 s) | 30 s |
| Soil moisture analysis (high, 10 s) | 0–60 s | 60 s |
| Leaf disease detection (high, 30 s) | 0–120 s (camera uploads up to 2 min after capture) | 120 s |
| Sensor aggregation (medium, 60 s) | 0–300 s | 300 s |
| Yield prediction (low, 600 s) | historical data | none |

A task's **effective deadline** is the earlier of its stated deadline and the moment its input data becomes
too old: D = min(arrival + deadline, data time + freshness bound). This is AURA's D_i.

## What the simulator gained

- **Tasks** carry `data_time_s` and `freshness_s`. They have the properties `effective_deadline` and `stale_at`.
- **Surges** (`WorkloadSpec.surges`) add extra arrivals for chosen priorities in a time window, at a seeded share
  of the gateways. They use their own random stream, so the normal arrivals are identical with or without a surge.
- **Early warnings** (`WorkloadSpec.warnings`, `Trace.signals`): true warnings for a share (recall) of affected
  gateways, ahead of the surge, plus false alarms so that the stated share of warnings is true (precision).
  Schedulers see a warning only once it has been issued (`ClusterView.signals_until_now()`). Each warning
  records whether it was true, for evaluation only; schedulers must not use that.
- **Scheduled outages** (`SimSettings.outages`): a node, or every node of a layer, is unavailable for a fixed
  time. Work in progress there is lost and retried, like a failure. A cloud outage stands in for losing the
  farm's internet link. This is a simplification: in reality cloud work in progress would finish, but its
  results could not come back until the link returned.
  Scheduled outages combine safely with random (MTBF) failures.
- **Saved topologies and workloads** in Experiments get the scenario applied to them, rather than to the
  generated network.

## New metrics

| Metric | Meaning |
| --- | --- |
| Effective deadlines met | Share of tasks delivered by their effective deadline. |
| Stale decisions (AoI violations) | Share of tasks with a freshness bound whose result came after the data went stale, or never came. Also reported for urgent tasks only. |
| Decision value delivered | Value delivered ÷ maximum possible value. Each task is worth its priority weight (critical 4, high 2, medium 1, low 0.5) by its effective deadline. After that its value halves every deadline-length, and it is worth nothing after three. |
| Autonomy ratio | Share of urgent tasks completed on edge or fog nodes, without the cloud. |

For stress scenarios, the comparison view shows these next to the usual headline metrics, together with a
timeline of the scenario's events.

## Baselines under the scenarios

Default network (4 farms, 8 gateways, 4 edge devices, 2 fog servers, 1 cloud). Intensity **100** ("busy
season"; at the default intensity of 20, no scenario stresses this network enough to separate the policies).
30 simulated minutes, EDF queues, 5 replications on identical workloads. Values are mean ± 95% CI.

| Scenario | Policy | Deadlines met | Urgent deadlines met | Stale decisions | Decision value | Autonomy | 95th pct response (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Normal | MCT | 99.99% | 99.99% | 2.7% | 99.8% | 99.8% | 8.4 |
| | Edge-ward | 100% | 100% | 1.0% | 99.95% | 13.9% | 4.6 |
| | Cloud-only | 100% | 100% | 1.0% | 99.96% | 0% | 4.6 |
| | Least loaded | 99.95% | 99.95% | 1.3% | 99.9% | 26.5% | 5.2 |
| | Min-Min (batch) | 80.1% | 77.4% | 7.4% | 85.9% | 99.3% | 9.6 |
| Monsoon burst | MCT | 72.9% ± 8.6 | 71.2% | 12.3% | 76.0% | 92.0% | 22.0 |
| | Edge-ward | 99.7% ± 0.6 | 99.6% | 2.1% | 99.7% | 10.4% | 11.8 |
| | Cloud-only | 85.6% ± 17 | 85.0% | 6.6% | 91.2% | 0% | 22.7 |
| | Least loaded | 98.4% ± 2.0 | 98.4% | 2.3% | 99.2% | 26.0% | 9.1 |
| | Min-Min (batch) | 62.0% ± 7.8 | 59.2% | 13.7% | 71.5% | 91.8% | 18.9 |
| Heat wave | MCT | 70.5% ± 2.2 | 68.3% | 9.5% | 78.4% | 94.7% | 20.7 |
| | Edge-ward | 99.99% | 99.99% | 1.4% | 99.9% | 11.1% | 6.7 |
| | Cloud-only | 99.8% | 99.8% | 2.0% | 99.8% | 0% | 13.2 |
| | Least loaded | 99.8% | 99.8% | 1.6% | 99.8% | 24.3% | 5.4 |
| | Min-Min (batch) | 64.2% ± 2.5 | 61.4% | 11.7% | 75.2% | 95.4% | 17.0 |
| Cloud disconnection | MCT | 56.5% ± 1.0 | 56.1% | 41.7% | 57.9% | 75.7% | 424 |
| | Edge-ward | 66.3% ± 4.3 | 65.9% | 20.9% | 73.6% | 53.9% | 103 |
| | Cloud-only | 49.8% ± 0.4 | 49.8% | 50.7% | 49.7% | 0% | 4.5 |
| | Least loaded | 68.3% ± 3.5 | 68.0% | 19.2% | 75.9% | 57.4% | 98 |
| | Min-Min (batch) | 45.0% ± 0.8 | 42.9% | 45.1% | 49.3% | 75.4% | 423 |
| Fog failure | MCT | 99.93% | 99.95% | 3.2% | 99.7% | 99.0% | 13.1 |
| | Edge-ward | 100% | 100% | 1.0% | 99.95% | 12.4% | 4.6 |
| | Cloud-only | 100% | 100% | 1.0% | 99.96% | 0% | 4.6 |
| | Least loaded | 99.94% | 99.94% | 1.4% | 99.9% | 23.8% | 5.3 |
| | Min-Min (batch) | 79.3% | 76.6% | 8.0% | 85.0% | 98.5% | 10.9 |

What this shows:

- **Cloud disconnection is the hardest scenario.** Edge and fog alone cannot carry busy-season load, so every
  policy loses a third or more of its deadlines, and up to half of decisions are made on stale data.
  Cloud-only simply fails while the cloud is gone (15 minutes here: half of the 30-minute run).
- **Bursts** hurt MCT and Min-Min badly. The likely reason: their queue estimate spreads work evenly over a node's cores. Leaf
  disease detection runs for 20 seconds on an edge core, so that estimate badly underestimates waits on busy
  edge devices. Cloud-only also suffers in the monsoon burst: the cloud saturates when one area sends six times
  more image analyses.
- **One fog server failing** barely matters in this network, because the cloud absorbs the work.
- **Without stress, about 1% of decisions are stale anyway.** Those tasks arrived with data that was already
  nearly too old.
- Edge-ward keeps urgent deadlines in most scenarios because it sends most work to the cloud. It therefore has
  a low autonomy ratio, and it fails when the cloud is unreachable.

These are the conditions AURA is evaluated in (Phase 4d).

## Tests

`packages/core/tests/test_scenarios.py` checks:

- the original trace hash is unchanged;
- data ages and effective deadlines;
- surge extra arrivals only inside their window and on the right share of gateways;
- warning precision, and that warnings are never visible early;
- cloud outages stop cloud work and are reproducible;
- outages combine with random failures;
- the decision-value function;
- scenario events in comparison results.
