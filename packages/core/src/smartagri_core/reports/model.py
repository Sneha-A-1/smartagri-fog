"""The report model: what every export format (PDF, Excel, LaTeX, figures, bundle) is built from.

An extractor turns one job result into a :class:`Report`. It states only facts that are in the result (numbers,
test outcomes, settings); it does not interpret them. Interpretation belongs in the paper.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class CI:
    """A mean with the half-width of its 95% confidence interval, and an optional significance mark."""

    mean: float | None
    half_width: float | None = None
    mark: str = ""  # "better" / "worse": significantly better or worse than the reference (shown as symbols)


@dataclass
class Column:
    name: str
    unit: str = ""
    kind: Literal["text", "num", "ci"] = "num"
    decimals: int | None = None  # None: chosen from the magnitude

    @property
    def header(self) -> str:
        return f"{self.name} ({self.unit})" if self.unit and self.unit != "share" else self.name


@dataclass
class Table:
    key: str
    caption: str
    columns: list[Column]
    rows: list[list[Any]]
    notes: str = ""
    highlight_row: int | None = None  # the proposed method's row, set in bold


@dataclass
class Series:
    name: str
    x: list[float]
    y: list[float | None]
    low: list[float | None] | None = None  # lower CI bound (optional band or error bar)
    high: list[float | None] | None = None
    emphasis: bool = False  # the proposed method


@dataclass
class Figure:
    key: str
    caption: str
    kind: Literal["dotwhisker", "lines", "bars", "scatter"]
    xlabel: str = ""
    ylabel: str = ""
    # dotwhisker: labels + one Series whose x are positions; bars: categories + series; lines/scatter: series
    labels: list[str] = field(default_factory=list)
    series: list[Series] = field(default_factory=list)
    log_y: bool = False
    note: str = ""
    shading: list[tuple[float, float, str]] = field(default_factory=list)  # (x0, x1, label): event periods


@dataclass
class Report:
    title: str
    subtitle: str
    data_origin: str
    summary: list[str]
    tables: list[Table] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)
    kind: str = ""


def fmt_num(v: Any, decimals: int | None = None) -> str:
    """Numbers for tables: magnitude-aware decimals, a proper minus sign avoided for LaTeX safety."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "–"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if not isinstance(v, (int, float)):
        return str(v)
    if decimals is None:
        a = abs(v)
        if a == 0:
            return "0"
        if a >= 1000:
            decimals = 0
        elif a >= 100:
            decimals = 1
        elif a >= 1:
            decimals = 2
        elif a >= 0.01:
            decimals = 3
        else:
            return f"{v:.2e}"
    return f"{v:,.{decimals}f}"


def _decimals_for(v: float) -> int | None:
    a = abs(v)
    if a >= 1000:
        return 0
    if a >= 100:
        return 1
    if a >= 1:
        return 2
    if a >= 0.01:
        return 3
    return None


def fmt_ci(c: CI, decimals: int | None = None) -> str:
    """Mean ± half-width, both with the decimals that suit the mean (so 99.95 ± 0.01, not 99.95 ± 6.40e-03)."""
    if c.mean is None:
        return "–"
    if c.half_width is None or c.half_width == 0:
        return fmt_num(c.mean, decimals)
    d = decimals if decimals is not None else _decimals_for(c.mean)
    if d is None:  # tiny means keep scientific notation for both
        return f"{fmt_num(c.mean)} ± {fmt_num(c.half_width)}"
    return f"{fmt_num(c.mean, d)} ± {fmt_num(c.half_width, d)}"


def summary_to_ci(s: dict[str, Any] | None, mark: str = "") -> CI:
    if not s:
        return CI(None)
    return CI(s.get("mean"), s.get("half_width"), mark)
