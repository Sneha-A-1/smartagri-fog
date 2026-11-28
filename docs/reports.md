# Reports and exports (Phase 5a)

Any finished job can be turned into material for a paper. Go to **Platform → Reports & export**, or press
**Export report** on a finished job. You can download:

| Download | What you get |
| --- | --- |
| PDF report | Title, summary, caveats, every table, every figure, and the parameters and provenance. Wide tables go on landscape pages. |
| LaTeX for Overleaf | `main.tex`, plus one booktabs table per file in `tables/` and vector figures in `figures/`. Upload the zip to Overleaf (New project → Upload project) and it compiles with pdfLaTeX. |
| Excel workbook | A summary sheet; one sheet per table, with the mean, the 95% CI half-width and the significance mark in separate numeric columns; the raw runs; the parameters. |
| Figures | Every figure as vector PDF and SVG, and as a 300-dpi PNG. |
| Reproducibility bundle | All of the above, plus `data/result.json`, `data/params.json`, `environment.json` (Python and package versions, git commit) and `reproduce.ps1`, which re-runs the job with the same parameters. |

## What the reports say

A report restates the job's own numbers, test outcomes and settings. It does not interpret them; that belongs in
your paper. Every report built from simulated or synthetic data says so in its caveats. Reports for AURA also
state what is not implemented: preemption and light task variants.

These job types have dedicated layouts:

- **AURA evaluation**:
  - tables: hypotheses with verdicts, one results table per scenario (with ▼ / ▲ significance marks), run times;
  - figures: AURA against the baselines and against its ablations by scenario, and the reservation timeline per scenario.
- **Experiments**: results with CIs, Friedman outcomes and one CI figure per metric.
- **Placement policy comparison**: results with CIs, the scenario's events and CI figures.
- **Optimiser benchmark**: the results table, convergence curves, final fitness and the NSGA-II Pareto front.
- **DQN training**: the held-out comparison, the learning curves and the held-out CI figures.
- **Strategy comparisons** (data retrieval architectures, irrigation strategies): results and the highlighted metrics.
- **iFogSim EEG validation**: simulated values next to the paper's, the reproduced and not-reproduced findings, and delay and network-usage figures per configuration.

Every other job gets a basic layout (its summary values, plus the full result in the bundle).

## Figure style

- **Size:** one paper column (3.5 in), or two columns (7.16 in) for wide grouped bars.
- **Fonts:** Times-like STIX at 8 pt.
- **Colours:** the same colour-vision-deficiency-checked palette as the app. The proposed method always gets the first colour.
- **Greyscale:** bars are hatched and lines carry markers, so figures still read in greyscale print.
- **Confidence intervals** are shown as error bars or whiskers.

Vector files have fixed metadata, so the same result always produces byte-identical figures and LaTeX.

## Command line

For results produced from PowerShell (for example the overnight AURA evaluation):

```powershell
cd D:\dev\smartagri-fog
uv run smartagri report results\aura-normal --format all
```

This writes `report.pdf`, `tables.xlsx`, `latex.zip`, `figures.zip` and `bundle.zip` into
`results\aura-normal\report`. `plugins run` now also saves a `run.json` next to `result.json`, so the bundle's
re-run command names the right plugin. For older folders, add `--plugin simulation:aura_evaluation`.

## Notes

- **Wide tables in LaTeX** (for example AURA's ten metrics) are scaled to the page width. For the paper, delete
  the columns you do not need from the `.tex` file.
- **Excel files** contain the time they were saved, so they are not byte-identical between downloads. Their
  contents are.
