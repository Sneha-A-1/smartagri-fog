"""Reports: every export format from real results, determinism, LaTeX that compiles, and the generic fallback."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
import smartagri_core.plugins  # noqa: F401
from openpyxl import load_workbook
from smartagri_core.registry import get_registry
from smartagri_core.reports import build_report, export, figure_svg, supported
from smartagri_core.reports.latex import esc
from smartagri_core.reports.model import CI, fmt_ci


@pytest.fixture(scope="module")
def results() -> dict[str, dict]:
    reg = get_registry()
    runs = {
        "comparison": (
            "simulation:comparison",
            {"duration_s": 120, "replications": 2, "placements": ["mct", "edge_ward"], "stress": "fog_failure"},
        ),
        "optimizer": (
            "simulation:optimizer_benchmark",
            {
                "duration_s": 120,
                "instances": 2,
                "replications": 2,
                "budget": 40,
                "pop_size": 8,
                "algorithms": ["ga", "nsga2"],
            },
        ),
        "dqn": (
            "simulation:dqn_training",
            {
                "duration_s": 120,
                "episodes": 2,
                "episode_s": 120,
                "updates_per_episode": 10,
                "buffer": 2000,
                "evaluation_replications": 2,
            },
        ),
    }
    return {k: reg.create(pid, params).run() for k, (pid, params) in runs.items()}


@pytest.mark.parametrize("name", ["comparison", "optimizer", "dqn"])
def test_every_format_is_valid(results, name):
    r = results[name]
    assert supported(r["kind"])
    report = build_report(r)
    assert report.tables and report.figures
    assert any("synthetic" in c for c in report.caveats)

    pdf, media, fname = export(r, "pdf")
    assert pdf.startswith(b"%PDF") and media == "application/pdf" and fname == "report.pdf"

    wb = load_workbook(io.BytesIO(export(r, "xlsx")[0]))
    assert "Summary" in wb.sheetnames and "Parameters" in wb.sheetnames and len(wb.sheetnames) >= 3

    latex = zipfile.ZipFile(io.BytesIO(export(r, "latex")[0]))
    names = latex.namelist()
    assert "main.tex" in names and any(n.startswith("tables/") for n in names)
    assert sum(n.startswith("figures/") and n.endswith(".pdf") for n in names) == len(report.figures)

    figs = zipfile.ZipFile(io.BytesIO(export(r, "figures")[0])).namelist()
    for f in report.figures:
        assert {f"{f.key}.pdf", f"{f.key}.svg", f"{f.key}.png"} <= set(figs)
    assert figure_svg(r, report.figures[0].key).lstrip().startswith(b"<?xml")

    bundle = zipfile.ZipFile(io.BytesIO(export(r, "bundle", plugin_id="simulation:x", params={"a": 1})[0]))
    bn = set(bundle.namelist())
    assert {
        "README.md",
        "report.pdf",
        "tables.xlsx",
        "data/result.json",
        "data/params.json",
        "environment.json",
        "reproduce.ps1",
        "latex/main.tex",
    } <= bn
    assert "simulation:x" in bundle.read("reproduce.ps1").decode()
    assert json.loads(bundle.read("data/params.json")) == {"a": 1}


def test_latex_and_figures_are_reproducible(results):
    r = results["comparison"]
    assert export(r, "latex")[0] == export(r, "latex")[0]
    assert export(r, "figures")[0] == export(r, "figures")[0]


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_latex_compiles(results, tmp_path: Path):
    zipfile.ZipFile(io.BytesIO(export(results["optimizer"], "latex")[0])).extractall(tmp_path)
    run = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout[-2000:]
    assert (tmp_path / "main.pdf").exists()


def test_unknown_kinds_still_export():
    r = {
        "kind": "something.new",
        "data_origin": "synthetic",
        "summary": {"tasks": 5, "label": "x"},
        "metrics": {"completion_rate": 99.5},
        "metric_info": {"completion_rate": ["Completed", "%", True]},
    }
    report = build_report(r)
    assert not supported("something.new") and report.tables[0].rows[0] == ["tasks", 5]
    assert export(r, "pdf")[0].startswith(b"%PDF")
    assert "data/result.json" in zipfile.ZipFile(io.BytesIO(export(r, "bundle")[0])).namelist()
    with pytest.raises(ValueError, match="Unknown format"):
        export(r, "docx")


def test_formatting_helpers():
    assert fmt_ci(CI(99.95, 0.0064)) == "99.95 ± 0.01"
    assert fmt_ci(CI(95075.0, 1383.2)) == "95,075 ± 1,383"
    assert fmt_ci(CI(None)) == "–"
    assert esc("50% of a_b & c ± d ▼") == r"50\% of a\_b \& c $\pm$ d $^{\blacktriangledown}$"


def test_experiment_results_export():
    from smartagri_core.experiment import AlgorithmSpec, ExperimentSpec, run_experiment
    from smartagri_core.sim.runner import ScenarioParams

    spec = ExperimentSpec(
        name="Report test",
        scenario=ScenarioParams(duration_s=120),
        algorithms=[AlgorithmSpec(placement="mct"), AlgorithmSpec(placement="edge_ward")],
        replications=3,
        metrics=["deadline_success_rate", "mean_response_s"],
    )
    r = run_experiment(spec)
    report = build_report(r)
    assert report.title == "Experiment" and len(report.figures) == 2
    assert report.tables[0].rows[0][0] == "mct/fcfs"
    assert export(r, "pdf")[0].startswith(b"%PDF")
