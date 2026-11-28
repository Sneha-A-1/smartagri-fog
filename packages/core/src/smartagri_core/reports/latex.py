"""LaTeX output: booktabs tables, figure includes and a main.tex that compiles on Overleaf as it is."""

from __future__ import annotations

from smartagri_core.reports.model import CI, Report, Table, fmt_ci, fmt_num

_UNICODE = {
    "±": r"$\pm$",
    "–": "--",
    "—": "---",
    "×": r"$\times$",
    "µ": r"$\mu$",
    "α": r"$\alpha$",
    "κ": r"$\kappa$",
    "≥": r"$\geq$",
    "≤": r"$\leq$",
    "→": r"$\rightarrow$",
    "▼": r"$^{\blacktriangledown}$",
    "▲": r"$^{\blacktriangle}$",
    "°": r"$^{\circ}$",
    "³": r"$^{3}$",
    "²": r"$^{2}$",
    "’": "'",
    "“": "``",
    "”": "''",
    "·": r"$\cdot$",
}
_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def esc(text: object) -> str:
    out = []
    for ch in str(text):
        if ch in _SPECIAL:
            out.append(_SPECIAL[ch])
        elif ch in _UNICODE:
            out.append(_UNICODE[ch])
        elif ord(ch) < 128:
            out.append(ch)
        else:
            out.append("?")  # anything else would break pdflatex
    return "".join(out)


def _cell(v: object, decimals: int | None) -> str:
    if isinstance(v, CI):
        mark = {"better": "▼", "worse": "▲"}.get(v.mark, "")
        return esc(fmt_ci(v, decimals)) + esc(mark)
    return esc(fmt_num(v, decimals) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)


def table_tex(t: Table, label_prefix: str = "tab") -> str:
    # Long text columns wrap (tabularx X columns); everything else stays on one line.
    long_text = [
        c.kind == "text" and max((len(str(r[i])) for r in t.rows), default=0) > 40 for i, c in enumerate(t.columns)
    ]
    align = "".join(
        "X" if lt else ("l" if c.kind == "text" else "r") for c, lt in zip(t.columns, long_text, strict=True)
    )
    wide = len(t.columns) > 5
    tab_begin = "\\begin{tabularx}{\\linewidth}" if any(long_text) else "\\begin{tabular}"
    tab_end = "\\end{tabularx}" if any(long_text) else "\\end{tabular}"
    env = "table*" if wide else "table"
    lines = [
        f"\\begin{{{env}}}[t]",
        "\\centering",
        "\\footnotesize" if wide else "\\small",
        f"\\caption{{{esc(t.caption)}}}",
        f"\\label{{{label_prefix}:{t.key}}}",
        "\\resizebox{\\linewidth}{!}{%" if wide else "",
        f"{tab_begin}{{{align}}}",
        "\\toprule",
        " & ".join(esc(c.header) for c in t.columns) + r" \\",
        "\\midrule",
    ]
    for i, row in enumerate(t.rows):
        cells = [_cell(v, c.decimals) for v, c in zip(row, t.columns, strict=True)]
        if t.highlight_row == i:
            cells = [f"\\textbf{{{c}}}" for c in cells]
        lines.append(" & ".join(cells) + r" \\")
    lines += ["\\bottomrule", tab_end]
    if wide:
        lines.append("}")
    if t.notes:
        lines.append(f"\\par\\smallskip{{\\scriptsize {esc(t.notes)}}}")
    lines.append(f"\\end{{{env}}}")
    return "\n".join(x for x in lines if x != "") + "\n"


def figure_tex(key: str, caption: str, wide: bool = False) -> str:
    env = "figure*" if wide else "figure"
    return (
        f"\\begin{{{env}}}[t]\n\\centering\n\\includegraphics[width=\\linewidth]{{figures/{key}.pdf}}\n"
        f"\\caption{{{esc(caption)}}}\n\\label{{fig:{key}}}\n\\end{{{env}}}\n"
    )


def main_tex(report: Report, wide_figures: set[str]) -> str:
    """A standalone document; copy the table and figure blocks into the paper's template."""
    parts = [
        r"\documentclass[10pt,twocolumn]{article}",
        r"\usepackage[margin=2cm]{geometry}",
        r"\usepackage{booktabs,tabularx,graphicx,amssymb}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage{mathptmx}",
        f"\\title{{{esc(report.title)}}}",
        f"\\author{{SmartAgri-Fog report ({esc(report.data_origin)} data)}}",
        r"\date{}",
        r"\begin{document}",
        r"\maketitle",
        r"\section*{Summary}",
    ]
    parts += [esc(p) + "\n" for p in report.summary if p]
    if report.caveats:
        parts += (
            [r"\paragraph{Caveats}", r"\begin{itemize}"]
            + [f"\\item {esc(c)}" for c in report.caveats]
            + [r"\end{itemize}"]
        )
    for t in report.tables:
        parts.append(f"\\input{{tables/{t.key}.tex}}")
    for f in report.figures:
        parts.append(figure_tex(f.key, f.caption, f.key in wide_figures))
    parts += [
        r"\section*{Reproducibility}",
        "Parameters, the full result and the command to re-run this job are in the report bundle "
        "(data/params.json, data/result.json, reproduce.ps1).",
        r"\end{document}",
    ]
    return "\n".join(parts) + "\n"
