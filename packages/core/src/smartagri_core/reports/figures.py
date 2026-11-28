"""Publication figures with matplotlib: vector PDF and SVG, plus 300-dpi PNG.

Sized for a two-column paper (one column = 3.5 in, two columns = 7.16 in), Times-like STIX fonts at 8 pt,
thin marks and a colour-vision-deficiency-checked palette. The proposed method keeps the first colour in every
figure; other series follow in a fixed order, with markers or hatching so the figures also work in greyscale.
"""

from __future__ import annotations

import io
from pathlib import Path

from smartagri_core.reports.model import Figure

# Same categorical palette as the web app (validated for colour-vision deficiency), then neutral greys.
PALETTE = ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6b7280", "#9ca3af", "#374151"]
MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*", "h"]
HATCHES = ["", "///", "...", "xx", "\\\\", "++", "--", "oo", "**"]
SINGLE, DOUBLE = 3.5, 7.16


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["STIXGeneral", "Times New Roman", "DejaVu Serif"],
            "mathtext.fontset": "stix",
            "font.size": 8,
            "axes.titlesize": 8,
            "axes.labelsize": 8,
            "legend.fontsize": 7,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "axes.linewidth": 0.6,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "lines.linewidth": 1.2,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "figure.dpi": 100,
            "svg.hashsalt": "smartagri-fog",  # stable element ids, so SVG output is reproducible
        }
    )
    return plt


def _colors(fig: Figure) -> list[str]:
    """Emphasised series take the first colour; the rest keep their order in the remaining colours."""
    out, rest = [], iter(PALETTE[1:] + PALETTE[1:])
    for s in fig.series:
        out.append(PALETTE[0] if s.emphasis else next(rest))
    if not any(s.emphasis for s in fig.series) and fig.series:
        out = [PALETTE[i % len(PALETTE)] for i in range(len(fig.series))]
    return out


def _clean(v):
    return float("nan") if v is None else v


def draw(fig: Figure):
    plt = _plt()
    colors = _colors(fig)
    if fig.kind == "dotwhisker":
        n = len(fig.labels)
        f, ax = plt.subplots(figsize=(SINGLE, max(1.2, 0.22 * n + 0.6)))
        s = fig.series[0]
        ys = list(range(n))[::-1]
        for i, y in enumerate(ys):
            m, lo, hi = s.y[i], (s.low or [None] * n)[i], (s.high or [None] * n)[i]
            if m is None:
                continue
            emph = fig.note and fig.labels[i] == fig.note
            c = PALETTE[0] if emph or not fig.note else "#374151"
            if lo is not None and hi is not None:
                ax.plot([lo, hi], [y, y], color=c, lw=1.2, solid_capstyle="butt")
            ax.plot([m], [y], "o", color=c, ms=4)
        ax.set_yticks(ys, fig.labels)
        ax.set_xlabel(fig.xlabel)
        ax.grid(axis="x", color="#e5e7eb", lw=0.5)
        ax.set_axisbelow(True)
    elif fig.kind == "bars":
        ncat, nser = len(fig.labels), len(fig.series)
        width_in = SINGLE if ncat * nser <= 14 else DOUBLE
        f, ax = plt.subplots(figsize=(width_in, 2.3))
        w = 0.8 / max(nser, 1)
        for j, s in enumerate(fig.series):
            xs = [i - 0.4 + w * (j + 0.5) for i in range(ncat)]
            ys = [_clean(v) for v in s.y]
            err = None
            if s.low and s.high:
                err = [
                    [max(0.0, (y - lo)) if lo is not None and y == y else 0 for y, lo in zip(ys, s.low, strict=False)],
                    [max(0.0, (hi - y)) if hi is not None and y == y else 0 for y, hi in zip(ys, s.high, strict=False)],
                ]
            ax.bar(
                xs,
                ys,
                w * 0.92,
                color=colors[j],
                edgecolor="white",
                linewidth=0.4,
                hatch=HATCHES[j % len(HATCHES)],
                label=s.name,
                yerr=err,
                error_kw={"elinewidth": 0.6, "capsize": 1.5, "ecolor": "#374151"},
            )
        ax.set_xticks(range(ncat), fig.labels)
        # Rotate category labels only when they would not fit side by side (about 4 pt per character at 7 pt).
        if max(len(lab) for lab in fig.labels) * 4.0 > width_in * 72 * 0.8 / ncat:
            plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
        ax.set_ylabel(fig.ylabel)
        ax.grid(axis="y", color="#e5e7eb", lw=0.5)
        ax.set_axisbelow(True)
        longest = max(len(x.name) for x in fig.series) * 4.3 + 22  # legend entry width in points
        ncol = max(1, min(nser, int(width_in * 72 * 0.95 // longest)))
        ax.legend(frameon=False, ncol=ncol, loc="lower center", bbox_to_anchor=(0.5, 1.0), borderaxespad=0.2)
    else:
        f, ax = plt.subplots(figsize=(SINGLE, 2.3))
        for x0, x1, label in fig.shading:
            ax.axvspan(x0, x1, color="#f47230", alpha=0.12, lw=0)
            ax.text(
                (x0 + x1) / 2,
                1.0,
                label,
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="bottom",
                fontsize=6.5,
                color="#6b7280",
            )
        for j, s in enumerate(fig.series):
            ys = [_clean(v) for v in s.y]
            if fig.kind == "scatter":
                ax.scatter(
                    s.x,
                    ys,
                    s=22 if s.emphasis else 12,
                    color="#111827" if s.emphasis else colors[j],
                    marker="x" if s.emphasis else MARKERS[j % len(MARKERS)],
                    label=s.name,
                    linewidths=0.9,
                )
            else:
                every = max(1, len(s.x) // 8)
                ax.plot(
                    s.x,
                    ys,
                    color=colors[j],
                    marker=MARKERS[j % len(MARKERS)],
                    markevery=every,
                    ms=3,
                    label=s.name,
                    lw=1.6 if s.emphasis else 1.1,
                )
                if s.low and s.high:
                    ax.fill_between(
                        s.x, [_clean(v) for v in s.low], [_clean(v) for v in s.high], color=colors[j], alpha=0.15, lw=0
                    )
        ax.set_xlabel(fig.xlabel)
        ax.set_ylabel(fig.ylabel)
        ax.grid(color="#e5e7eb", lw=0.5)
        ax.set_axisbelow(True)
        if len(fig.series) > 4:  # many lines: legend below the plot so it never covers data
            f.set_size_inches(SINGLE, 2.3 + 0.12 * ((len(fig.series) + 1) // 2))
            ax.legend(frameon=False, fontsize=6.5, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.22))
        elif len(fig.series) > 1:
            ax.legend(frameon=False, fontsize=6.5)
    if fig.log_y:
        from matplotlib.ticker import LogLocator, NullFormatter, ScalarFormatter

        ax.set_yscale("log")
        ax.yaxis.set_major_locator(LogLocator(subs=(1.0, 2.0, 5.0)))
        ax.yaxis.set_major_formatter(ScalarFormatter())
        ax.yaxis.set_minor_formatter(NullFormatter())
    f.tight_layout()
    return f


def render(fig: Figure, out_dir: Path, formats: tuple[str, ...] = ("pdf", "svg", "png")) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    plt = _plt()
    f = draw(fig)
    paths = {}
    for ext in formats:
        path = out_dir / f"{fig.key}.{ext}"
        f.savefig(path, dpi=300 if ext == "png" else None, bbox_inches="tight", metadata=_meta(ext))
        paths[ext] = path
    plt.close(f)
    return paths


def to_bytes(fig: Figure, ext: str = "svg") -> bytes:
    plt = _plt()
    f = draw(fig)
    buf = io.BytesIO()
    f.savefig(buf, format=ext, dpi=200 if ext == "png" else None, bbox_inches="tight", metadata=_meta(ext))
    plt.close(f)
    return buf.getvalue()


def _meta(ext: str) -> dict | None:
    # Fixed metadata so the same result always gives byte-identical vector files.
    if ext == "pdf":
        return {"Creator": "SmartAgri-Fog", "Producer": "SmartAgri-Fog", "CreationDate": None}
    if ext == "svg":
        return {"Date": None, "Creator": "SmartAgri-Fog"}
    return None
