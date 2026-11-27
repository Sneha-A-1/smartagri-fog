"""Reading, profiling, validating and streaming tabular datasets."""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta

import pytest
from openpyxl import Workbook
from smartagri_core.data.tables import (
    Mapping,
    TableError,
    guess_mapping,
    profile,
    read_table,
    tidy_csv,
    to_number,
    to_streams,
    validate,
)
from smartagri_core.retrieval.framework import RetrievalConfig, process_stream


def _csv(rows: list[list[str]], sep: str = ",") -> bytes:
    return "\n".join(sep.join(r) for r in rows).encode()


def test_csv_with_semicolons_decimal_commas_and_day_first_dates() -> None:
    body = [["Datum", "Sensor ID", "Soil moisture", "Temp"]]
    body += [[f"{d:02d}/03/2026 06:00", "P1", f"0,{20 + d}", f"{10 + d},5"] for d in range(1, 15)]
    t = read_table(_csv(body, ";"), "station.csv")
    assert t.columns == ["Datum", "Sensor ID", "Soil moisture", "Temp"] and len(t.rows) == 14
    prof = {c["name"]: c for c in profile(t)}
    assert prof["Datum"]["type"] == "datetime" and prof["Datum"]["format"] == "%d/%m/%Y %H:%M"
    assert prof["Soil moisture"]["type"] == "number" and prof["Soil moisture"]["max"] == pytest.approx(0.34)
    assert prof["Sensor ID"]["type"] == "text"
    m = guess_mapping(profile(t))
    assert m["time_column"] == "Datum" and m["source_column"] == "Sensor ID"
    assert m["metrics"] == {"Soil moisture": "soil_moisture_m3m3", "Temp": "air_temperature_c"}


def test_excel_and_json_inputs() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "readings"
    ws.append(["time", "rh"])
    start = datetime(2026, 1, 1)
    for i in range(10):
        ws.append([start + timedelta(hours=i), 60 + i])
    wb.create_sheet("notes").append(["ignore me"])
    buf = io.BytesIO()
    wb.save(buf)
    t = read_table(buf.getvalue(), "data.xlsx")
    assert t.format == "xlsx" and t.sheet == "readings" and t.sheets == ["readings", "notes"] and len(t.rows) == 10
    assert profile(t)[0]["type"] == "datetime" and "notes" in t.warnings[0]
    assert read_table(buf.getvalue(), "data.xlsx", sheet="notes").columns == ["ignore me"]

    records = [{"ts": f"2026-01-01T0{i}:00:00", "temp": 10 + i} for i in range(5)]
    assert len(read_table(json.dumps(records).encode(), "a.json").rows) == 5
    wrapped = read_table(json.dumps({"meta": {"x": 1}, "data": records}).encode(), "b.json")
    assert wrapped.columns == ["ts", "temp"]
    columnar = read_table(json.dumps({"ts": ["2026-01-01", "2026-01-02"], "v": [1, 2]}).encode(), "c.json")
    assert columnar.rows == [["2026-01-01", 1], ["2026-01-02", 2]]
    with pytest.raises(TableError):
        read_table(b"{not json", "d.json")
    with pytest.raises(TableError, match="xls"):
        read_table(b"x", "old.xls")


def test_numbers() -> None:
    assert to_number("1,5") == 1.5 and to_number("1,234.5") == 1234.5 and to_number("NA") is None
    assert to_number(True) is None and to_number("abc") is None and to_number(3) == 3.0


def test_validation_report_and_streams() -> None:
    rows = [["time", "probe", "vwc"]]
    t0 = datetime(2026, 2, 1)
    for i in range(48):
        if i == 20:
            continue  # a gap
        rows.append([(t0 + timedelta(minutes=30 * i)).isoformat(), "A", str(0.25 if i != 30 else 1.7)])
    rows.append(rows[5])  # a duplicate row
    for i in range(10):
        rows.append([(t0 + timedelta(minutes=30 * i)).isoformat(), "B", ""])
    table = read_table(_csv(rows), "x.csv")
    m = Mapping(time_column="time", source_column="probe", metrics={"vwc": "soil_moisture_m3m3"}, soil_stress_theta=0.2)
    rep = validate(table, m)
    assert rep["ok"] and rep["duplicate_rows"] == 1
    a = next(s for s in rep["series"] if s["source"] == "A")
    b = next(s for s in rep["series"] if s["source"] == "B")
    assert a["interval_min"] == 30 and a["gaps"] == 0 and a["out_of_range"] == 1 and a["duplicate_times"] == 1
    assert b["missing"] == 10
    streams, samples, start = to_streams(table, m)
    assert start == t0 and [s.key for s in streams] == ["A:soil_moisture_m3m3", "B:soil_moisture_m3m3"]
    assert streams[0].refs == {"stress_theta": 0.2} and len(samples["A:soil_moisture_m3m3"]) == 47
    res = process_stream(streams[0], samples["A:soil_moisture_m3m3"], RetrievalConfig())
    assert res.status.count("range") == 1
    assert tidy_csv(table, m).splitlines()[0] == "time,source,metric,value"
    assert not validate(table, Mapping(time_column="time"))["ok"]
    assert not validate(table, Mapping(time_column="nope", metrics={"vwc": "x"}))["ok"]


def test_long_format() -> None:
    rows = [["when", "station", "variable", "reading"]]
    for i in range(6):
        ts = f"2026-03-01 0{i}:00"
        rows += [[ts, "S1", "air_temperature_c", str(5 - i)], [ts, "S1", "relative_humidity_pct", "80"]]
    table = read_table(_csv(rows), "long.csv")
    m = Mapping(time_column="when", source_column="station", metric_column="variable", value_column="reading")
    streams, samples, _ = to_streams(table, m)
    assert {s.metric for s in streams} == {"air_temperature_c", "relative_humidity_pct"}
    assert samples["S1:air_temperature_c"][-1] == (300.0, 0.0)
