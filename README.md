# SmartAgri-Fog

**Intelligent Cloud-Enabled Framework for Smart Agriculture**: a research platform for designing, simulating,
comparing and evaluating cloud–fog–edge computing strategies for agriculture.

Developed for the PhD research *"Design and Development of an Efficient Cloud-Enabled Framework for Smart
Agriculture."*

> **Status: Phase 1 in progress (1a simulator and 1b experiments done).** Every feature carries an explicit status: *Implemented*, *Simulated*,
> *Needs integration* or *Planned*. Planned features are listed with the phase they arrive in and never
> produce results. Synthetic data is always labelled as synthetic.

## Quick start (Windows, PowerShell)

```powershell
cd D:\dev\smartagri-fog
.\scripts\setup.ps1     # install everything and build the interface
.\scripts\start.ps1     # start the platform; opens http://127.0.0.1:8000
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
| Command line | `uv run smartagri plugins list`, `uv run smartagri experiment run experiments/rural-baseline.yaml --out results/x` |

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
