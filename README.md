# SmartAgri-Fog

**Intelligent Cloud-Enabled Framework for Smart Agriculture**: a research platform for designing, simulating,
comparing and evaluating cloud–fog–edge computing strategies for agriculture.

Developed for the PhD research *"Design and Development of an Efficient Cloud-Enabled Framework for Smart
Agriculture."*

> **Status: Phase 1 in progress (1a simulator, 1b experiments and 1c network designer done).** Every feature carries an explicit status: *Implemented*, *Simulated*,
> *Needs integration* or *Planned*. Planned features are listed with the phase they arrive in and never
> produce results. Synthetic data is always labelled as synthetic.

## Quick start (Windows, PowerShell)

```powershell
cd D:\dev\smartagri-fog
.\scripts\setup.ps1     # install everything and build the interface
.\scripts\start.ps1     # start the platform; rebuilds the interface automatically after git pull
```

Full instructions: [docs/getting-started.md](docs/getting-started.md).

## What works so far

| Area | What works |
| --- | --- |
| Web interface | Grouped navigation for all 27 planned pages, light/dark themes, English/Hindi, beginner and researcher modes, Ctrl+K search |
| Algorithm catalogue | 74 entries (51 implemented) with status badges and roadmap phases; forms generated from parameter schemas |
| Jobs | Background execution in worker processes, live progress over WebSocket, cancellation, results on disk |
| Data | SQLite database with automatic migrations; projects; per-user settings; audit log |
| Access | Local single-user mode; roles and permissions (admin, researcher, farmer, expert) for shared deployments |
| Demo | A synthetic soil-moisture generator that exercises the whole pipeline |
| Simulator (Phase 1a) | Discrete-event simulation of farm IoT-edge-fog-cloud networks; 22 placement policies and 6 queue disciplines; replicated comparisons with 95% confidence intervals; validated against M/M/1 queueing theory. See [docs/simulation-model.md](docs/simulation-model.md) |
| Experiments (Phase 1b) | Saved, frozen experiment definitions; 30-replication runs with Friedman, Nemenyi, Holm-corrected Wilcoxon and A12 effect sizes; CSV, LaTeX and YAML exports. See [docs/experiments.md](docs/experiments.md) |
| Network designer (Phase 1c) | Drag-and-drop topology designer (Cytoscape.js) with generator, validation and JSON import/export; workload editor with load preview; simulations and experiments on saved designs with per-device results. See [docs/designing-networks.md](docs/designing-networks.md) |
| Literature review (Phase 1d) | Import BibTeX or CSL JSON from Zotero and databases with duplicate detection; PRISMA 2020 screening with live flow counts; tagging by layer, technique, metric, domain and evaluation; research-gap matrix; BibTeX, CSV and LaTeX exports. See [docs/literature-review.md](docs/literature-review.md) |
| iFogSim reproduction (Phase 1e) | Module-based simulator following iFogSim's model; the paper's EEG game case study with results next to the published figures, including the parts that don't match. See [docs/ifogsim-reproduction.md](docs/ifogsim-reproduction.md) |
| Task-graph scheduling | HEFT and CPOP, validated against the published example (schedule lengths 80 and 86); seeded random-graph experiments with significance tests. See [docs/dag-scheduling.md](docs/dag-scheduling.md) |
| Farms and irrigation (Phase 2a) | Farms and fields drawn on a satellite map; daily weather from Open-Meteo, station CSV or a synthetic generator; FAO-56 ET₀ and soil-water balance with irrigation advice, validated against FAO-56 worked examples. See [docs/farms-and-irrigation.md](docs/farms-and-irrigation.md) |
| Devices and digital twin (Phase 2b) | Simulated and real soil-moisture sensors, weather stations, valves and gateways; token-based HTTP ingestion; sensor-corrected FAO-56 balance; a digital-twin map of field water status; a closed-loop experiment comparing model-only, sensor and Kalman-filter irrigation. See [docs/devices-and-twin.md](docs/devices-and-twin.md) |
| Data retrieval framework (Phase 3a) | Edge processing of sensor streams: validation (range, Hampel spikes, stuck), smoothing, alerts with persistence, hysteresis and cool-down, trend-based early warnings, send-on-delta, and task emission for the scheduler; ground-truth scenarios and an experiment comparing cloud and edge architectures. See [docs/retrieval-framework.md](docs/retrieval-framework.md) |
| Data acquisition (Phase 3b) | Upload CSV, Excel or JSON datasets with declared origin and source; column profiling, mapping to sensor metrics, data-quality report, tidy export, and processing by the retrieval framework. See [docs/data-acquisition.md](docs/data-acquisition.md) |
| Metaheuristic schedulers (Phase 4a) | GA, PSO, ACO, Grey Wolf, Whale and NSGA-II (plus random search) as batch schedulers with an equal evaluation budget, validated against brute force; a benchmark on frozen scheduling windows with convergence curves, a Pareto front and statistics; the Optimization lab page. See [docs/optimisation.md](docs/optimisation.md) |
| Learned scheduler (Phase 4b) | A Deep Q-Network online scheduler in numpy (no GPU), trained on fresh simulated workloads and tested on held-out ones against MCT, edge-ward, least-loaded and random placement, with learning curves and statistics. See [docs/optimisation.md](docs/optimisation.md) |
| Stress scenarios (Phase 4c) | Data age and freshness bounds (AoI) on tasks; monsoon-burst and heat-wave surges with imperfect early warnings; scheduled cloud disconnection and fog failure; metrics for stale decisions, decision value and autonomy; a Scenario choice on every simulation form. See [docs/scenarios.md](docs/scenarios.md) |
| AURA, the proposed scheduler (Phase 4d) | Two tiers (online urgent placement by AoI-aware decision value; NSGA-II for strategic tasks), anticipatory reservation from early warnings, replication of critical tasks; five ablations; a Performance evaluation page that runs AURA against the baselines on every scenario and checks hypotheses H1 to H4. See [docs/aura.md](docs/aura.md) |
| Reports and exports (Phase 5a) | For any finished job: a PDF report, LaTeX tables and vector figures for Overleaf, an Excel workbook, and a reproducibility bundle with data, versions and the re-run command; also `smartagri report` on the command line. See [docs/reports.md](docs/reports.md) |
| Command line | `uv run smartagri plugins list`, `uv run smartagri experiment run experiments/rural-baseline.yaml --out results/x`, `uv run smartagri plugins run simulation:ifogsim_eeg --out results/eeg` |

## Architecture

```text
apps/web            React + TypeScript interface
apps/api            FastAPI: routes, database, jobs (thin layer)
packages/core       smartagri_core: all science, no web code
packages/proposed   the proposed AURA algorithm (separate package)
docs/               guides and architecture decision records
```

Design decisions are recorded in [docs/adr](docs/adr). To add an algorithm, see
[docs/adding-an-algorithm.md](docs/adding-an-algorithm.md).
