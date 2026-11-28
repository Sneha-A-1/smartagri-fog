"""Excel workbook: a summary sheet, one sheet per table (means and CI half-widths in separate numeric columns),
the raw runs when the result has them, and the parameters."""

from __future__ import annotations

import io
import json
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from smartagri_core.reports.model import CI, Report

HEADER = PatternFill("solid", fgColor="E8EEF5")


def _sheet_name(name: str, used: set[str]) -> str:
    base = "".join(c for c in name if c not in r"[]:*?/\\")[:28] or "Sheet"
    out, i = base, 2
    while out.lower() in used:
        out, i = f"{base[:25]} {i}", i + 1
    used.add(out.lower())
    return out


def workbook_bytes(report: Report, result: dict[str, Any]) -> bytes:
    wb = Workbook()
    used: set[str] = set()
    ws = wb.active
    ws.title = _sheet_name("Summary", used)
    ws["A1"] = report.title
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Data origin: {report.data_origin}"
    r = 4
    for para in report.summary + [f"Caveat: {c}" for c in report.caveats]:
        ws.cell(r, 1, para).alignment = Alignment(wrap_text=True, vertical="top")
        r += 1
    ws.column_dimensions["A"].width = 120

    for t in report.tables:
        sh = wb.create_sheet(_sheet_name(t.key.replace("_", " ").title(), used))
        sh["A1"] = t.caption
        sh["A1"].font = Font(italic=True)
        headers: list[str] = []
        for c in t.columns:
            if c.kind == "ci":
                headers += [f"{c.header} mean", f"{c.header} ±95% CI", f"{c.header} vs reference"]
            else:
                headers.append(c.header)
        for j, h in enumerate(headers, 1):
            cell = sh.cell(3, j, h)
            cell.font, cell.fill = Font(bold=True), HEADER
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            sh.column_dimensions[get_column_letter(j)].width = 16 if j > 1 else 34
        for i, row in enumerate(t.rows, 4):
            j = 1
            for v, c in zip(row, t.columns, strict=True):
                if c.kind == "ci":
                    ci = v if isinstance(v, CI) else CI(None)
                    sh.cell(i, j, ci.mean)
                    sh.cell(i, j + 1, ci.half_width)
                    sh.cell(i, j + 2, {"better": "reference better", "worse": "reference worse"}.get(ci.mark, ""))
                    j += 3
                else:
                    sh.cell(i, j, v)
                    j += 1
            if t.highlight_row == i - 4:
                for k in range(1, j):
                    sh.cell(i, k).font = Font(bold=True)
        if t.notes:
            sh.cell(len(t.rows) + 5, 1, t.notes).font = Font(italic=True)
        sh.freeze_panes = "B4"

    runs = result.get("runs")
    if isinstance(runs, list) and runs and isinstance(runs[0], dict):
        sh = wb.create_sheet(_sheet_name("Runs", used))
        flat = [_flatten(x) for x in runs]
        cols = list(dict.fromkeys(k for row in flat for k in row))
        for j, k in enumerate(cols, 1):
            sh.cell(1, j, k).font = Font(bold=True)
        for i, row in enumerate(flat, 2):
            for j, k in enumerate(cols, 1):
                sh.cell(i, j, row.get(k))
        sh.freeze_panes = "A2"

    sh = wb.create_sheet(_sheet_name("Parameters", used))
    sh["A1"], sh["B1"] = "Parameter", "Value"
    sh["A1"].font = sh["B1"].font = Font(bold=True)
    for i, (k, v) in enumerate(_flatten({"params": report.params, "provenance": report.provenance}).items(), 2):
        sh.cell(i, 1, k)
        sh.cell(i, 2, v)
    sh.column_dimensions["A"].width, sh.column_dimensions["B"].width = 40, 60

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        elif isinstance(v, (list, tuple)):
            out[key] = json.dumps(v) if v and not isinstance(v[0], (int, float, str)) else ", ".join(map(str, v))
        else:
            out[key] = v
    return out
