"""Reading, profiling and validating tabular datasets (CSV, Excel, JSON) without heavy dependencies.

A dataset becomes sensor streams through a *mapping*: which column holds the time, which (optional) column
identifies the sensor, and which columns hold which metric (wide format), or which columns hold the metric name
and the value (long format).
"""

from __future__ import annotations

import csv
import io
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from smartagri_core.retrieval.framework import RetrievalConfig, Stream

MAX_ROWS = 200_000
MAX_BYTES = 50 * 1024 * 1024

DATETIME_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
]

KNOWN_METRICS = {
    "soil_moisture_m3m3": "Soil moisture (m³/m³)",
    "air_temperature_c": "Air temperature (°C)",
    "relative_humidity_pct": "Relative humidity (%)",
    "rain_mm": "Rain (mm)",
}


@dataclass
class Table:
    columns: list[str]
    rows: list[list[Any]]
    format: str
    sheets: list[str] = field(default_factory=list)
    sheet: str | None = None
    warnings: list[str] = field(default_factory=list)


class TableError(ValueError):
    pass


def _clean_header(cols: list[Any]) -> list[str]:
    out, seen = [], Counter()
    for i, c in enumerate(cols):
        name = str(c).strip() if c not in (None, "") else f"column_{i + 1}"
        seen[name] += 1
        out.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return out


def read_table(content: bytes, filename: str, sheet: str | None = None) -> Table:
    if len(content) > MAX_BYTES:
        raise TableError(f"The file is larger than {MAX_BYTES // 1024 // 1024} MB")
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        return _read_xlsx(content, sheet)
    if name.endswith(".xls"):
        raise TableError("Old .xls files are not supported; save the file as .xlsx or CSV in Excel")
    if name.endswith(".json"):
        return _read_json(content)
    return _read_csv(content)


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise TableError("Could not read the text encoding")


def _read_csv(content: bytes) -> Table:
    text = _decode(content)
    if not text.strip():
        raise TableError("The file is empty")
    try:
        dialect = csv.Sniffer().sniff(text[:20_000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise TableError("No rows found")
    header, body = _clean_header(rows[0]), rows[1:]
    warnings = []
    if len(body) > MAX_ROWS:
        warnings.append(f"Only the first {MAX_ROWS:,} of {len(body):,} rows were kept")
        body = body[:MAX_ROWS]
    width = len(header)
    ragged = sum(1 for r in body if len(r) != width)
    if ragged:
        warnings.append(f"{ragged} rows had a different number of fields than the header and were padded or cut")
    body = [(r + [""] * width)[:width] for r in body]
    return Table(header, body, "csv", warnings=warnings)


def _read_xlsx(content: bytes, sheet: str | None) -> Table:
    from openpyxl import load_workbook  # imported lazily: only needed for Excel files

    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises several types for broken files
        raise TableError(f"Could not open the Excel file: {exc}") from None
    sheets = wb.sheetnames
    ws = wb[sheet] if sheet in sheets else wb[sheets[0]]
    rows, header, warnings = [], None, []
    for r in ws.iter_rows(values_only=True):
        if all(c in (None, "") for c in r):
            continue
        if header is None:
            header = _clean_header(list(r))
            continue
        if len(rows) >= MAX_ROWS:
            warnings.append(f"Only the first {MAX_ROWS:,} rows were kept")
            break
        rows.append(list(r))
    wb.close()
    if header is None:
        raise TableError(f"The sheet {ws.title!r} is empty")
    width = len(header)
    rows = [(r + [None] * width)[:width] for r in rows]
    if len(sheets) > 1:
        warnings.append(
            f"Read the sheet {ws.title!r}; the file also has {', '.join(s for s in sheets if s != ws.title)}"
        )
    return Table(header, rows, "xlsx", sheets, ws.title, warnings)


def _read_json(content: bytes) -> Table:
    try:
        data = json.loads(_decode(content))
    except json.JSONDecodeError as exc:
        raise TableError(f"Not valid JSON: {exc.msg} (line {exc.lineno})") from None
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        if all(isinstance(v, list) for v in data.values()) and len({len(v) for v in data.values()}) == 1:
            cols = _clean_header(list(data))
            return Table(cols, [list(r) for r in zip(*data.values(), strict=True)], "json")
        if len(lists) == 1 and lists[0] and isinstance(lists[0][0], dict):
            data = lists[0]
    if not isinstance(data, list) or not data or not all(isinstance(r, dict) for r in data):
        raise TableError(
            "JSON must be a list of records, an object with one list of records, or an object of equal-length arrays"
        )
    cols: list[str] = []
    for r in data[:MAX_ROWS]:
        for k in r:
            if k not in cols:
                cols.append(k)
    rows = [[r.get(c) for c in cols] for r in data[:MAX_ROWS]]
    warnings = [f"Only the first {MAX_ROWS:,} records were kept"] if len(data) > MAX_ROWS else []
    return Table(_clean_header(cols), rows, "json", warnings=warnings)


# --- parsing values ---------------------------------------------------------------------------------


def _missing(v: Any) -> bool:
    return (
        v is None
        or (isinstance(v, str) and v.strip().lower() in ("", "na", "n/a", "nan", "null", "-", "none"))
        or (isinstance(v, float) and math.isnan(v))
    )


def to_number(v: Any) -> float | None:
    if _missing(v) or isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    s = str(v).strip().replace(" ", "")
    # one comma and no point is a decimal comma; otherwise commas separate thousands
    s = s.replace(",", ".") if s.count(",") == 1 and "." not in s else s.replace(",", "")
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def detect_datetime_format(values: list[Any]) -> str | None:
    """The format that parses the most of the sample (datetime objects need none)."""
    strings = [str(v).strip() for v in values if not _missing(v) and not isinstance(v, datetime | date)]
    if not strings:
        return "native" if any(isinstance(v, datetime | date) for v in values) else None
    best, best_n = None, 0
    for fmt in DATETIME_FORMATS:
        n = 0
        for s in strings[:200]:
            try:
                datetime.strptime(s, fmt)
                n += 1
            except ValueError:
                pass
        if n > best_n:
            best, best_n = fmt, n
    return best if best_n >= 0.8 * min(len(strings), 200) else None


def to_datetime(v: Any, fmt: str | None) -> datetime | None:
    if _missing(v):
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time())
    if fmt is None or fmt == "native":
        return None
    try:
        d = datetime.strptime(str(v).strip(), fmt)
    except ValueError:
        return None
    return d.replace(tzinfo=None) if d.tzinfo is None else d.astimezone().replace(tzinfo=None)


# --- profiling --------------------------------------------------------------------------------------


def profile(table: Table) -> list[dict[str, Any]]:
    out = []
    n = len(table.rows)
    for j, col in enumerate(table.columns):
        values = [r[j] for r in table.rows]
        present = [v for v in values if not _missing(v)]
        info: dict[str, Any] = {"name": col, "missing": n - len(present), "count": len(present)}
        nums = [x for x in (to_number(v) for v in present) if x is not None]
        fmt = detect_datetime_format(present[:500])
        if not present:
            info["type"] = "empty"
        elif fmt:
            dts = [d for d in (to_datetime(v, fmt) for v in present) if d is not None]
            info |= {
                "type": "datetime",
                "format": fmt,
                "unparsed": len(present) - len(dts),
                "min": min(dts).isoformat() if dts else None,
                "max": max(dts).isoformat() if dts else None,
            }
        elif len(nums) >= 0.9 * len(present):
            info |= {
                "type": "number",
                "unparsed": len(present) - len(nums),
                "min": min(nums),
                "max": max(nums),
                "mean": statistics.fmean(nums),
                "std": statistics.pstdev(nums) if len(nums) > 1 else 0.0,
            }
        else:
            info["type"] = "text"
        uniques = Counter(str(v) for v in present[:5000])
        info["unique"] = len(uniques)
        info["examples"] = [str(v) for v, _ in uniques.most_common(3)]
        out.append(info)
    return out


def guess_mapping(prof: list[dict[str, Any]]) -> dict[str, Any]:
    """A first guess of the mapping from column names and types, for the user to confirm."""
    time_col = next((c["name"] for c in prof if c["type"] == "datetime"), None)
    source = next(
        (
            c["name"]
            for c in prof
            if c["type"] == "text"
            and any(k in c["name"].lower() for k in ("sensor", "device", "station", "node", "id", "probe", "field"))
        ),
        None,
    )
    hints = {
        "soil_moisture_m3m3": ("soil", "moist", "vwc", "theta", "sm"),
        "air_temperature_c": ("temp", "tair", "t_air", "temperature"),
        "relative_humidity_pct": ("humid", "rh"),
        "rain_mm": ("rain", "precip", "prcp"),
    }
    metrics = {}
    for c in prof:
        if c["type"] != "number":
            continue
        low = c["name"].lower()
        for metric, words in hints.items():
            if any(w in low for w in words) and metric not in metrics.values():
                metrics[c["name"]] = metric
                break
    return {
        "time_column": time_col,
        "source_column": source,
        "metrics": metrics,
        "metric_column": None,
        "value_column": None,
        "soil_stress_theta": None,
    }


# --- mapping, validation and streams ----------------------------------------------------------------


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_column: str | None = None
    source_column: str | None = Field(None, description="Column naming the sensor (several sensors in one file)")
    metrics: dict[str, str] = Field(default_factory=dict, description="Wide format: column -> metric")
    metric_column: str | None = Field(None, description="Long format: column holding the metric name")
    value_column: str | None = Field(None, description="Long format: column holding the value")
    soil_stress_theta: float | None = Field(None, ge=0, le=1, description="Soil moisture at which stress starts")


def _records(table: Table, m: Mapping) -> tuple[list[tuple[datetime, str, str, float | None]], list[str]]:
    """(time, source, metric, value) for every mapped cell, and the problems found while reading them."""
    cols = {c: i for i, c in enumerate(table.columns)}
    problems = []
    if not m.time_column or m.time_column not in cols:
        return [], ["Choose the column that holds the date and time"]
    for c in [m.source_column, m.metric_column, m.value_column, *m.metrics]:
        if c and c not in cols:
            problems.append(f"Column {c!r} is not in the file")
    if problems:
        return [], problems
    if not m.metrics and not (m.metric_column and m.value_column):
        return [], ["Map at least one column to a metric"]
    ti = cols[m.time_column]
    fmt = detect_datetime_format([r[ti] for r in table.rows[:500]])
    out: list[tuple[datetime, str, str, float | None]] = []
    bad_time = 0
    for r in table.rows:
        t = to_datetime(r[ti], fmt)
        if t is None:
            bad_time += 1
            continue
        src = str(r[cols[m.source_column]]).strip() if m.source_column else "dataset"
        if m.metric_column and m.value_column:
            metric = str(r[cols[m.metric_column]]).strip()
            out.append((t, src, metric, to_number(r[cols[m.value_column]])))
        for col, metric in m.metrics.items():
            out.append((t, src, metric, to_number(r[cols[col]])))
    if bad_time:
        problems.append(f"{bad_time} rows have a date and time that could not be read and were skipped")
    return out, problems


def validate(table: Table, m: Mapping, cfg: RetrievalConfig | None = None) -> dict[str, Any]:
    """Data-quality report for the mapped data: what a reviewer of the dataset would ask about."""
    cfg = cfg or RetrievalConfig()
    records, problems = _records(table, m)
    report: dict[str, Any] = {"ok": not problems and bool(records), "problems": problems, "series": []}
    dup_rows = len(table.rows) - len({tuple(map(str, r)) for r in table.rows})
    report["duplicate_rows"] = dup_rows
    by_series: dict[tuple[str, str], list[tuple[datetime, float | None]]] = defaultdict(list)
    for t, src, metric, v in records:
        by_series[(src, metric)].append((t, v))
    for (src, metric), pts in sorted(by_series.items()):
        pts.sort(key=lambda x: x[0])
        times = [t for t, _ in pts]
        values = [v for _, v in pts if v is not None]
        gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:], strict=False) if b > a]
        step = statistics.median(gaps) if gaps else None
        bounds = cfg.bounds.get(metric)
        out_of_range = sum(1 for v in values if bounds and not (bounds.low <= v <= bounds.high))
        report["series"].append(
            {
                "source": src,
                "metric": metric,
                "known_metric": metric in KNOWN_METRICS,
                "points": len(pts),
                "missing": len(pts) - len(values),
                "duplicate_times": len(times) - len(set(times)),
                "start": times[0].isoformat() if times else None,
                "end": times[-1].isoformat() if times else None,
                "interval_min": step,
                "gaps": sum(1 for g in gaps if step and g > 3 * step),
                "out_of_range": out_of_range,
                "min": min(values) if values else None,
                "max": max(values) if values else None,
            }
        )
    return report


def to_streams(table: Table, m: Mapping) -> tuple[list[Stream], dict[str, list[tuple[float, float | None]]], datetime]:
    """Streams for the retrieval framework; times in minutes from the earliest timestamp."""
    records, problems = _records(table, m)
    if not records:
        raise TableError("; ".join(problems) or "No data after mapping")
    start = min(t for t, _, _, _ in records)
    series: dict[tuple[str, str], list[tuple[float, float | None]]] = defaultdict(list)
    for t, src, metric, v in records:
        series[(src, metric)].append(((t - start).total_seconds() / 60, v))
    streams, samples = [], {}
    for (src, metric), pts in sorted(series.items()):
        pts.sort(key=lambda x: x[0])
        dedup: dict[float, float | None] = {}
        for t, v in pts:
            if t not in dedup or dedup[t] is None:
                dedup[t] = v
        key = f"{src}:{metric}"
        refs = {"stress_theta": m.soil_stress_theta} if m.soil_stress_theta is not None else {}
        streams.append(Stream(key, src, metric, src, refs))
        samples[key] = sorted(dedup.items())
    return streams, samples, start


def tidy_csv(table: Table, m: Mapping) -> str:
    """The mapped data in long format: time, source, metric, value."""
    records, _ = _records(table, m)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time", "source", "metric", "value"])
    for t, src, metric, v in sorted(records, key=lambda r: (r[1], r[2], r[0])):
        w.writerow([t.isoformat(), src, metric, "" if v is None else v])
    return buf.getvalue()
