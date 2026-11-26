# Reproducing the iFogSim EEG case study

SmartAgri-Fog includes a module-based simulator that follows the application model of iFogSim, and a
reproduction of the first case study of the iFogSim paper:

> H. Gupta, A. V. Dastjerdi, S. K. Ghosh, R. Buyya. iFogSim: A toolkit for modeling and simulation of resource
> management techniques in the Internet of Things, Edge and Fog computing environments. *Software: Practice and
> Experience* 47(9):1275–1296, 2017. doi:10.1002/spe.2509

Reproducing a published result is how the platform earns trust before it is used for new results. This page
records what matches, what doesn't, and why, so you can cite it in your methodology chapter.

## Run it

- **Interface:** Simulation → *Open the iFogSim reproduction* (or Algorithm catalogue → *Case study: iFogSim EEG
  Tractor Beam game*), then **Start job**. The default run (5 configurations × 2 headsets × 2 placements × 3 seeds,
  10 simulated seconds each) takes about a minute.
- **Command line:** `uv run smartagri plugins run simulation:ifogsim_eeg --out results\ifogsim-eeg`

The job page shows the paper's findings with *Reproduced* or *Not reproduced* next to each, both figures with the
paper's values marked on every bar, and a table of every cell.

## The model

The EEG Tractor Beam game has three modules: **client** (on the player's smartphone), **concentration
calculator** and **connector** (the coordinator). The control loop of interest is
EEG → client → concentration calculator → client → display. Each WiFi gateway serves 4 smartphones; Configs 1–5 have
1, 2, 4, 8 and 16 gateways under one ISP gateway (proxy) and the cloud.

The simulator (`smartagri_core.sim.dataflow`) implements iFogSim's semantics:

| Aspect | Model |
| --- | --- |
| Topology | Tree of devices; tuples travel hop by hop along it |
| Links | One FIFO uplink and one FIFO downlink queue per device: size / bandwidth transmission, plus latency |
| CPU | Processor sharing: all tuples on a device share its MIPS equally (iFogSim's time-shared schedulers) |
| Modules | Tuple mappings with selectivity; periodic edges; one shared copy per hosting device |
| Loop delay | From sensor emission to actuator receipt, as iFogSim measures it |
| Network usage | iFogSim's data rate × delay product: Σ latency × size over device-to-device transfers, ÷ time, in KB |
| Energy | Linear power between idle and busy; a device is busy while it executes any tuple |
| Cloud-only placement | Client on each smartphone, other modules in the cloud |
| Edge-ward placement | iFogSim's Algorithm 1: lowest device on the path that has CPU for the module's expected load |

Two textbook checks guard the engine (`packages/core/tests/test_dataflow.py`): a processor-shared queue with
Poisson arrivals gives a mean time in system of S / (1 − ρ) (2.00 ms at ρ = 0.5), and cloud-only network usage
matches its closed form within 2%.

### Where the parameters come from

The paper's tables give tuple sizes, headsets, latencies and power. Values the paper does not give are taken from
the authors' example code, `org.fog.test.perfeval.VRGameFog` in iFogSim 1.0. The job page lists every
parameter with its source. Notably:

- Device MIPS (cloud 44 800, gateways 2 800, phone 1 000) and bandwidths come from the code; the paper gives only GHz.
- Cloud power (16 × 103 W busy, 16 × 83.25 W idle) comes from the code. The paper's Table II lists 107 W, but its
  Figure 13 data-centre energy is only consistent with the code's values.
- In cloud-only placement the client stays on the smartphone, as in the code. With the client in the cloud, network
  usage would roughly double and no longer match Figure 12.

### Reading the paper's values

The paper prints its results only as bar charts. Values were measured from Figures 11 and 12 by pixel analysis, to
about ±10 ms and ±3 KB. Edge-ward latency bars are only a few pixels tall, so those values are approximate.

## Results

Default run (3 seeds × 10 simulated seconds per cell). Seed-to-seed variation is below 0.1%, because the headsets
emit at fixed intervals and only the 0.9 selectivity is random.

| Config | Phones | Headset | Placement | Loop delay (ms) | Paper (ms) | Network (KB) | Paper (KB) | Calculator on |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 4 | A | cloud-only | 221.6 | 229 | 42.5 | 41 | cloud |
| 2 | 8 | A | cloud-only | 221.8 | 229 | 84.8 | 84 | cloud |
| 3 | 16 | A | cloud-only | 222.2 | 229 | 169.8 | 186 | cloud |
| 4 | 32 | A | cloud-only | 222.9 | 906 | 339.4 | 415 | cloud |
| 5 | 64 | A | cloud-only | 224.5 | 4064 | 678.6 | 709 | cloud |
| 1 | 4 | B | cloud-only | 222.1 | 219 | 80.5 | 78 | cloud |
| 2 | 8 | B | cloud-only | 222.3 | 219 | 161.3 | 163 | cloud |
| 3 | 16 | B | cloud-only | 222.7 | 219 | 322.3 | 357 | cloud |
| 4 | 32 | B | cloud-only | 223.5 | 2958 | 644.3 | 697 | cloud |
| 5 | 64 | B | cloud-only | 225.4 | 4582 | 1289.7 | 1278 | cloud |
| 1 | 4 | A | edge-ward | 12.6 | 20 | 8.5 | not readable | smartphones |
| 2 | 8 | A | edge-ward | 12.6 | 20 | 17.1 | 9 | smartphones |
| 3 | 16 | A | edge-ward | 12.6 | 30 | 34.1 | 17 | smartphones |
| 4 | 32 | A | edge-ward | 12.6 | 30 | 68.2 | 35 | smartphones |
| 5 | 64 | A | edge-ward | 12.6 | 20 | 136.4 | 70 | smartphones |
| 1 | 4 | B | edge-ward | 18.6 | 30 | 6.8 | 9 | WiFi gateway |
| 2 | 8 | B | edge-ward | 18.6 | 20 | 13.5 | 17 | WiFi gateways |
| 3 | 16 | B | edge-ward | 18.5 | 30 | 27.1 | 35 | WiFi gateways |
| 4 | 32 | B | edge-ward | 18.4 | 30 | 54.1 | 64 | WiFi gateways |
| 5 | 64 | B | edge-ward | 18.5 | 20 | 108.2 | 128 | WiFi gateways |

### What is reproduced

- **Edge-ward beats cloud-only** on control-loop delay (12–19 ms against about 222 ms) and on network usage, in every
  configuration (Figures 11 and 12).
- **Cloud-only delay for Configs 1–3** is within 3% of the paper (222 ms against 219–229 ms). It is almost entirely
  link latency: 6 + 2 + 4 + 100 ms up and 100 + 4 + 2 + 1 ms down.
- **Cloud-only network usage** is within 10% of the paper for Configs 1, 2, 3 and 5, and 8–18% below it at Config 4.
  It grows linearly with the number of smartphones, as in Figure 12.
- **Energy (Figure 13):** at 32 smartphones, the projected 3-hour energy is 14.4 MJ (edge-ward) against 15.2–15.9 MJ
  (cloud-only) for the data centre, and about 29 MJ for the smartphones. The paper shows about 13.5 against 15, and
  28 MJ. The paper does not say which configuration Figure 13 uses; the smartphone energy points to Config 4.

### What is not reproduced

1. **The sharp rise in cloud-only delay at Configs 4–5** (906–4582 ms in the paper). Here the delay stays at
   223–225 ms. With the published capacities, the busiest device at Config 5 (the cloud, headset B) runs at 90%
   CPU and the busiest link (cloud downlink) 64%, so this model has no queue that could grow that much. The paper does not report
   utilisation, so the cause can't be checked. Possible explanations include iFogSim 1.0 implementation details
   (its schedulers and event handling) and parameters that differ from the published example code. The automatic
   check reports this as *Not reproduced*; no parameter was tuned to force a match.
2. **Edge-ward network usage** is about twice the paper's for headset A and 15–25% below it for headset B. For
   headset A, iFogSim's load rule fits the concentration calculator on each smartphone (client 211 + calculator
   315 MI/ms ≤ 1000 MIPS), so every phone sends game state to the cloud every 100 ms. The paper's lower values
   suggest a different placement in the authors' runs. For headset B, the calculator moves to the WiFi gateways.
3. **Edge-ward delay** is 12.6 ms (A) and 18.5 ms (B) against bars of about 20–30 ms. That is the same order of
   magnitude, but the published bars are too small to compare more precisely.

### How to describe this in a paper

A fair summary: *"Our simulator reproduces the qualitative findings of the iFogSim EEG case study and matches the
published cloud-only latency (within 3%, Configs 1–3) and network usage (within 18%, all configurations).
It does not reproduce the latency increase reported for the largest cloud-only configurations, which the
published parameters cannot account for."* Cite the paper, this platform's version (shown on the Overview page)
and the job parameters (saved with every job).
