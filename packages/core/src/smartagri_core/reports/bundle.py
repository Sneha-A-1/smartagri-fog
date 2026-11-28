"""Exports of one job result: PDF, Excel, LaTeX, figures, or everything as a reproducibility bundle."""

from __future__ import annotations

import contextlib
import io
import json
import platform
import subprocess
import tempfile
import zipfile
from importlib import metadata
from pathlib import Path
from typing import Any

from smartagri_core.reports.excel import workbook_bytes
from smartagri_core.reports.extract import build_report
from smartagri_core.reports.figures import render, to_bytes
from smartagri_core.reports.latex import main_tex, table_tex
from smartagri_core.reports.model import Report
from smartagri_core.reports.pdf import pdf_bytes

FORMATS: dict[str, tuple[str, str]] = {
    "pdf": ("application/pdf", "report.pdf"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "tables.xlsx"),
    "latex": ("application/zip", "latex.zip"),
    "figures": ("application/zip", "figures.zip"),
    "bundle": ("application/zip", "bundle.zip"),
}
_EPOCH = (1980, 1, 1, 0, 0, 0)  # fixed timestamps inside zips, so the same result gives the same archive


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, files[name])
    return buf.getvalue()


def _wide(report: Report) -> set[str]:
    return {f.key for f in report.figures if f.kind == "bars" and len(f.labels) * len(f.series) > 14}


def figure_files(report: Report) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for f in report.figures:
            for ext, path in render(f, Path(tmp)).items():
                out[f"{f.key}.{ext}"] = path.read_bytes()
    return out


def latex_files(report: Report, figs: dict[str, bytes]) -> dict[str, bytes]:
    files = {"main.tex": main_tex(report, _wide(report)).encode()}
    for t in report.tables:
        files[f"tables/{t.key}.tex"] = table_tex(t).encode()
    for name, data in figs.items():
        if name.endswith(".pdf"):
            files[f"figures/{name}"] = data
    files["README.txt"] = (
        b"Upload this folder to Overleaf (New project > Upload project) and compile main.tex with pdfLaTeX.\n"
        b"Each table is a separate file in tables/ and each figure a vector PDF in figures/, so you can copy them\n"
        b"into your paper's template with \\input{tables/...} and \\includegraphics{figures/...}.\n"
        b"Packages used: booktabs, tabularx, graphicx, amssymb\n"
        b"(main.tex also uses mathptmx, a standard Times font package).\n"
    )
    return files


def environment() -> dict[str, Any]:
    env: dict[str, Any] = {"python": platform.python_version(), "platform": platform.platform(), "packages": {}}
    for pkg in ("smartagri-core", "smartagri-proposed", "numpy", "scipy", "matplotlib", "reportlab", "openpyxl"):
        with contextlib.suppress(metadata.PackageNotFoundError):
            env["packages"][pkg] = metadata.version(pkg)
    try:
        here = Path(__file__).resolve().parent
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=here, capture_output=True, text=True, timeout=5)
        if commit.returncode == 0:
            env["git_commit"] = commit.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return env


def _reproduce(plugin_id: str | None, params: dict[str, Any]) -> dict[str, bytes]:
    if not plugin_id:
        return {}
    ps = (
        "# Re-run this job from the project folder (for example D:\\dev\\smartagri-fog) in PowerShell.\n"
        "# Same parameters and seeds give the same results (wall-clock run times excepted).\n"
        f"uv run smartagri plugins run {plugin_id} --params data\\params.json --out results\\reproduced\n"
    )
    sh = f"#!/bin/sh\nuv run smartagri plugins run {plugin_id} --params data/params.json --out results/reproduced\n"
    return {
        "reproduce.ps1": ps.encode(),
        "reproduce.sh": sh.encode(),
        "data/params.json": json.dumps(params, indent=1, default=str).encode(),
    }


def export(
    result: dict[str, Any], fmt: str, plugin_id: str | None = None, params: dict[str, Any] | None = None
) -> tuple[bytes, str, str]:
    """Build one export. Returns (bytes, media type, file name)."""
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format {fmt!r}; use one of {', '.join(FORMATS)}")
    report = build_report(result)
    media, name = FORMATS[fmt]
    if fmt == "xlsx":
        return workbook_bytes(report, result), media, name
    figs = figure_files(report) if report.figures else {}
    pngs = {k[:-4]: v for k, v in figs.items() if k.endswith(".png")}
    if fmt == "pdf":
        return pdf_bytes(report, pngs), media, name
    if fmt == "figures":
        return _zip(figs), media, name
    if fmt == "latex":
        return _zip(latex_files(report, figs)), media, name
    files: dict[str, bytes] = {
        "report.pdf": pdf_bytes(report, pngs),
        "tables.xlsx": workbook_bytes(report, result),
        "data/result.json": json.dumps(result, indent=1, default=str).encode(),
        "environment.json": json.dumps(environment(), indent=1).encode(),
    }
    files.update({f"latex/{k}": v for k, v in latex_files(report, figs).items()})
    files.update({f"figures/{k}": v for k, v in figs.items()})
    params = params if params is not None else dict(result.get("params") or {})
    files.update(_reproduce(plugin_id, params))
    files["README.md"] = _readme(report, plugin_id, sorted(files)).encode()
    return _zip(files), media, name


def figure_svg(result: dict[str, Any], key: str) -> bytes:
    report = build_report(result)
    for f in report.figures:
        if f.key == key:
            return to_bytes(f, "svg")
    raise KeyError(key)


def _readme(report: Report, plugin_id: str | None, names: list[str]) -> str:
    lines = [
        f"# {report.title}",
        "",
        f"Data origin: **{report.data_origin}**. Generated by SmartAgri-Fog.",
        "",
        "## Contents",
        "",
        "- `report.pdf`: summary, tables, figures and parameters.",
        "- `tables.xlsx`: every table, with means and 95% CI half-widths in separate columns, plus raw runs.",
        "- `latex/`: `main.tex`, one `.tex` file per table (booktabs) and vector figures; uploads to Overleaf as is.",
        "- `figures/`: each figure as PDF and SVG (vector) and 300-dpi PNG.",
        "- `data/result.json`: the complete job result; `data/params.json`: the parameters it ran with.",
        "- `environment.json`: Python and package versions (and the git commit, when available).",
    ]
    if plugin_id:
        lines += [
            "- `reproduce.ps1` / `reproduce.sh`: the command that re-runs the job.",
            "",
            "## Reproduce",
            "",
            "From the project folder:",
            "",
            "```powershell",
            f"uv run smartagri plugins run {plugin_id} --params data\\params.json --out results\\reproduced",
            "```",
            "",
            "The same parameters and seeds give the same results; only wall-clock run times differ.",
        ]
    if report.caveats:
        lines += ["", "## Caveats", ""] + [f"- {c}" for c in report.caveats]
    lines += ["", "## Files", ""] + [f"- {n}" for n in names]
    return "\n".join(lines) + "\n"
