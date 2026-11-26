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
| Algorithm catalogue | 43 entries with status badges and roadmap phases; forms generated from parameter schemas |
| Jobs | Background execution in worker processes, live progress over WebSocket, cancellation, results on disk |
| Data | SQLite database with automatic migrations; projects; per-user settings; audit log |
| Access | Local single-user mode; roles and permissions (admin, researcher, farmer, expert) for shared deployments |
| Demo | A synthetic soil-moisture generator that exercises the whole pipeline |
| Simulator (Phase 1a) | Discrete-event simulation of farm IoT-edge-fog-cloud networks; 8 placement policies and 4 queue disciplines; replicated comparisons with 95% confidence intervals; validated against M/M/1 queueing theory. See [docs/simulation-model.md](docs/simulation-model.md) |
| Experiments (Phase 1b) | Saved, frozen experiment definitions; 30-replication runs with Friedman, Nemenyi, Holm-corrected Wilcoxon and A12 effect sizes; CSV, LaTeX and YAML exports. See [docs/experiments.md](docs/experiments.md) |
| Network designer (Phase 1c) | Drag-and-drop topology designer (Cytoscape.js) with generator, validation and JSON import/export; workload editor with load preview; simulations and experiments on saved designs with per-device results. See [docs/designing-networks.md](docs/designing-networks.md) |
| Literature review (Phase 1d) | Import BibTeX or CSL JSON from Zotero and databases with duplicate detection; PRISMA 2020 screening with live flow counts; tagging by layer, technique, metric, domain and evaluation; research-gap matrix; BibTeX, CSV and LaTeX exports. See [docs/literature-review.md](docs/literature-review.md) |
| iFogSim reproduction (Phase 1e) | Module-based simulator following iFogSim's model; the paper's EEG game case study with results next to the published figures, including the parts that don't match. See [docs/ifogsim-reproduction.md](docs/ifogsim-reproduction.md) |
| Task-graph scheduling | HEFT and CPOP, validated against the published example (schedule lengths 80 and 86); seeded random-graph experiments with significance tests. See [docs/dag-scheduling.md](docs/dag-scheduling.md) |
| Farms and irrigation (Phase 2a) | Farms and fields drawn on a satellite map; daily weather from Open-Meteo, station CSV or a synthetic generator; FAO-56 ET₀ and soil-water balance with irrigation advice, validated against FAO-56 worked examples. See [docs/farms-and-irrigation.md](docs/farms-and-irrigation.md) |
| Devices and digital twin (Phase 2b) | Simulated and real soil-moisture sensors, weather stations, valves and gateways; token-based HTTP ingestion; sensor-corrected FAO-56 balance; a digital-twin map of field water status; a closed-loop experiment comparing model-only, sensor and Kalman-filter irrigation. See [docs/devices-and-twin.md](docs/devices-and-twin.md) |
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
