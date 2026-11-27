# Data retrieval framework

The data retrieval framework (DRF) is what an edge node, such as a farm gateway, does with raw sensor streams before
anything reaches the cloud or the scheduler. It is the bridge between the devices of Phase 2 and the scheduling
of Phase 4: its alerts become AURA's urgent tasks, and its trend predictions drive AURA's capacity reservation.

Code: `packages/core/src/smartagri_core/retrieval/`. Page: **Data → Data retrieval framework**. Experiment:
**Experiment: data retrieval architectures**.

## The pipeline

Each stream (one metric from one sensor) is processed reading by reading, in five stages:

| Stage | What it does | Main settings |
| --- | --- | --- |
| 1. Validate | Physical range check; spike detection with a Hampel filter (deviation from the median of the last 7 readings, in scaled median absolute deviations, at least 0.03 m³/m³ or 3 °C); stuck-sensor detection (no change for 3 hours). Rejected readings are not used or sent. A range or stuck fault raises one maintenance event per episode. | `spike_sigmas`, `stuck_minutes` |
| 2. Smooth and detect | Slow signals are smoothed with a moving median (soil moisture, 60 min). Threshold rules then need several consecutive readings (persistence), re-arm only after the value moves back past the threshold by a margin (hysteresis), and do not repeat within a cool-down (soil 12 h, frost and heat 3 h). Thresholds can be per field, for example the soil moisture at which the field's crop starts water stress. | `persistence`, `smooth_min`, rules |
| 3. Predict | A least-squares trend over the last 4 hours estimates when an armed rule will be breached. A crossing within the horizon (6 h) raises an early warning. | `predict`, `horizon_min` |
| 4. Reduce | Send-on-delta: a valid reading goes upstream only if it differs from the last sent value by the dead band (soil 0.01 m³/m³, temperature 0.5 °C), if the heartbeat (2 h) has passed, or if it caused an alert. | `deadband`, `heartbeat_min` |
| 5. Emit tasks | Each alert becomes a task for the scheduler with a class (frost: critical; soil stress, heat: high), a deadline, a freshness bound, and the timestamp of its newest reading, for Age of Information. Sensor faults become medium maintenance tasks; hourly aggregation of the data sent becomes low (strategic) tasks. | task profiles |

The defaults are reasoned choices rather than tuned values. Smoothing and the cool-down exist because soil moisture
changes by about 0.003 m³/m³ a day while a probe's noise is about 0.01 m³/m³. The task classes, deadlines and
freshness bounds follow AURA's task model.

## The page

Choose **Synthetic scenario** or **My devices**, adjust the framework, and click **Run the framework**. For each
stream the chart shows:
- valid readings (grey) and rejected readings (red);
- what was sent upstream (blue step line) and the true signal (dashed, scenarios only);
- the threshold (dashed red);
- alerts, early warnings and faults (vertical lines).

Below the chart are the events and the tasks handed to the scheduler, which you can download as JSON. With a
scenario, the page also checks the run against the ground truth.

## Ground-truth scenarios

`retrieval/scenario.py` builds farms where the truth is known:
- **Soil moisture:** each field's true value comes from its FAO-56 water balance, irrigated late so that stress
  episodes happen.
- **Temperature:** follows a daily cycle from synthetic weather, with frost nights and heat days injected.
- **Sensor faults:** noise, spikes, 6-hour stuck episodes and missing readings.

Everything is seeded, so the same seed gives the same scenario.

## The evaluation

**Experiment: data retrieval architectures** compares four architectures on the same seeded scenarios:

| Architecture | Where processing happens | Validation, persistence, prediction, cool-down | Data sent |
| --- | --- | --- | --- |
| Cloud raw | Cloud, after batched upload every 15 min | Yes | Every reading |
| Cloud duty-cycled | Cloud; sensors read 4 times less often | Yes | Every reading taken |
| Edge send-on-delta | Gateway, immediately | No (a typical "smart gateway") | Changes only |
| Edge DRF | Gateway, immediately | Yes | Changes only, smoothed |

The cloud architectures run the same detection logic as the DRF. The comparison therefore isolates where it
runs (latency, data volume, freshness) from what it does (the edge send-on-delta baseline).

### Metrics

| Metric | Definition |
| --- | --- |
| Alert precision | Share of alerts within a true event's window (from 2 days before onset for soil stress, 1 hour for frost and heat, to 1 hour after the end) |
| Event recall | Share of true events with at least one alert |
| False alarms per day | Alerts outside every event window |
| Time to detect frost and heat | Decision time (sample time plus upload delay) minus true onset |
| Early warnings | Share of events with a prediction before onset |
| Stuck sensors detected | Share of stuck episodes flagged |
| Age of data at the scheduler | For urgent tasks: arrival minus the time of the newest reading used |
| Readings transmitted | Share of raw readings sent upstream |
| Soil reconstruction error | RMSE of the transmitted soil series (held between transmissions) against the truth |

Precision counts every alert, so several alerts during one real event all count as correct. The cool-down removes
those duplicates, which lowers false alarms per day but can lower precision too. Report both.

### Default result

10 scenarios of 20 days, 10 soil probes and a weather station read every 15 minutes, about 11 events each. Means
are listed below; the job page shows the 95% CIs and Friedman/Wilcoxon tests (all differences significant except
recall).

| | Cloud raw | Cloud duty-cycled | Edge send-on-delta | Edge DRF |
| --- | --- | --- | --- | --- |
| Alert F1 | 0.79 | 0.89 | 0.66 | 0.79 |
| False alarms per day | 0.73 | 0.47 | 15.6 | 0.73 |
| Time to detect frost and heat (min) | 34 | 115 | 8.5 | 19 |
| Events with early warning | 60% | 0% | 0% | 60% |
| Stuck sensors detected | 100% | 100% | 0% | 100% |
| Age of data at the scheduler (min) | 15.3 | 15.3 | 0.02 | 0.02 |
| Readings transmitted | 98% | 25% | 48% | 19% |
| Soil reconstruction error (m³/m³) | 0.015 | 0.015 | 0.015 | 0.006 |

How to read it:
- **Edge DRF vs cloud raw:** the same detection quality, but data that is 15 minutes fresher at the scheduler,
  frost and heat detected about 15 minutes sooner, five times less data sent, and a more accurate reconstruction.
- **Edge DRF vs the naive gateway:** validation, persistence and the cool-down cut false alarms from 15.6 to 0.7
  per day and catch every stuck sensor. Persistence costs about 10 minutes of detection delay.
- **Duty cycling** has the best F1, because fewer readings give noise fewer chances to cause false alarms. But it
  detects frost and heat about 2 hours late, gives no early warnings, and its data is 15 minutes old.
- **Soil-stress alerts** come on average about a day before the true onset in every architecture: probe noise
  crosses a slow-moving threshold early. For irrigation that is useful, but it means time to detect is not a
  meaningful measure for slow processes.

These results come from synthetic scenarios and depend on the parameters, which the experiment exposes.
