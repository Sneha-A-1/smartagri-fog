"""FAO-56 evapotranspiration and water balance, and weather parsing."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from smartagri_core.agro.fao56 import (
    CROPS,
    SOILS,
    DayWeather,
    IrrigationPolicy,
    et0_penman_monteith,
    extraterrestrial_radiation,
    recommendation,
    water_balance,
    wind_at_2m,
)
from smartagri_core.agro.weather import (
    open_meteo_url,
    parse_open_meteo,
    parse_weather_csv,
    synthetic_weather,
    to_balance_weather,
)


def test_fao56_example_18_brussels() -> None:
    """FAO-56 Example 18: Uccle (Brussels), 6 July; published ET0 = 3.9 mm/day."""
    u2 = wind_at_2m(10 / 3.6, 10)
    r = et0_penman_monteith(
        tmax=21.5, tmin=12.3, lat_deg=50.8, elevation_m=100, doy=187, u2=u2, sunshine_hours=9.25, rh_min=63, rh_max=84
    )
    assert u2 == pytest.approx(2.078, abs=1e-3)
    assert r.ra == pytest.approx(41.09, abs=0.05) and r.rs == pytest.approx(22.07, abs=0.05)
    assert r.rn == pytest.approx(13.28, abs=0.05)
    assert r.es == pytest.approx(1.997, abs=1e-3) and r.ea == pytest.approx(1.409, abs=1e-3)
    assert r.gamma == pytest.approx(0.0666, abs=1e-4) and r.delta == pytest.approx(0.122, abs=1e-3)
    assert r.et0 == pytest.approx(3.9, abs=0.05)


def test_fao56_example_8_extraterrestrial_radiation() -> None:
    """FAO-56 Example 8: 20 deg S on 3 September, Ra = 32.2 MJ/m2/day, N = 11.7 h (Example 9)."""
    ra, n = extraterrestrial_radiation(-20, 246)
    assert ra == pytest.approx(32.2, abs=0.1) and n == pytest.approx(11.7, abs=0.1)


def test_missing_radiation_uses_hargreaves_estimate() -> None:
    r = et0_penman_monteith(tmax=35, tmin=20, lat_deg=28.6, elevation_m=216, doy=120, rh_mean=40)
    assert r.rs_estimated and 4 < r.et0 < 10


def test_kc_curve_follows_the_stages() -> None:
    wheat = CROPS["wheat"]
    ini, dev, mid, late = wheat.stages
    assert wheat.kc(0) == wheat.kc_ini and wheat.kc(ini + dev) == wheat.kc_mid
    assert wheat.kc(ini + dev // 2) == pytest.approx((wheat.kc_ini + wheat.kc_mid) / 2, abs=0.03)
    assert wheat.kc(wheat.season_days - 1) == pytest.approx(wheat.kc_end)


def _season(et0: float, rain_every: int | None, days: int = 120) -> list[DayWeather]:
    start = date(2025, 11, 15)
    return [
        DayWeather(start + timedelta(days=i), et0, 20.0 if rain_every and i % rain_every == 0 else 0.0)
        for i in range(days)
    ]


def test_water_balance_conserves_water_and_avoids_stress_when_irrigated() -> None:
    wheat, loam = CROPS["wheat"], SOILS["loam"]
    weather = _season(4.0, rain_every=17)
    res = water_balance(weather, wheat, loam, date(2025, 11, 15), initial_depletion=10)
    d0, last = 10, res.days[-1]
    inflow = sum(d.effective_rain + d.irrigation_net for d in res.days)
    outflow = sum(d.etc_adj + d.deep_percolation for d in res.days)
    assert last.depletion - d0 == pytest.approx(outflow - inflow, abs=1e-9)  # FAO-56 eq. 85 summed over the season
    assert all(d.ks == 1.0 for d in res.days)  # irrigating at the p threshold avoids stress
    assert res.summary(wheat)["irrigation_events"] > 0 and res.summary(wheat)["relative_yield"] == pytest.approx(1.0)


def test_rainfed_field_suffers_stress_and_yield_loss() -> None:
    wheat, sand = CROPS["wheat"], SOILS["sand"]
    res = water_balance(_season(5.0, None), wheat, sand, date(2025, 11, 15), policy=IrrigationPolicy(rainfed=True))
    s = res.summary(wheat)
    assert s["irrigation_events"] == 0 and s["stress_days"] > 30
    assert s["eta_mm"] < s["etc_mm"] and s["relative_yield"] < 0.8


def test_recommendation_uses_forecast() -> None:
    wheat, loam = CROPS["wheat"], SOILS["loam"]
    start = date(2025, 11, 15)
    weather = [DayWeather(start + timedelta(days=i), 4.0, 0.0, forecast=i >= 30) for i in range(40)]
    res = water_balance(weather, wheat, loam, start, policy=IrrigationPolicy(rainfed=False))
    rec = recommendation(res)
    assert rec["action"] in {"irrigate", "wait"} and "text" in rec


# Shaped like an Open-Meteo response (hand-written for the test, not real observations)
OPEN_METEO_FORMAT = {
    "latitude": 28.6,
    "longitude": 77.2,
    "timezone": "Asia/Kolkata",
    "daily": {
        "time": ["2025-05-01", "2025-05-02"],
        "temperature_2m_max": [39.0, 40.5],
        "temperature_2m_min": [24.0, 25.5],
        "precipitation_sum": [0.0, 2.4],
        "shortwave_radiation_sum": [25.1, 24.0],
        "et0_fao_evapotranspiration": [7.1, 6.9],
    },
    "hourly": {
        "time": [f"2025-05-0{d}T{h:02d}:00" for d in (1, 2) for h in range(24)],
        "relative_humidity_2m": [30 + (h % 24) for h in range(48)],
        "wind_speed_10m": [3.0] * 48,
    },
}


def test_open_meteo_parsing_and_url() -> None:
    days = parse_open_meteo(OPEN_METEO_FORMAT, today=date(2025, 5, 1))
    assert len(days) == 2 and days[0].rh_min == 30 and days[0].rh_max == 53
    assert days[0].wind_2m == pytest.approx(wind_at_2m(3.0, 10)) and days[1].forecast and not days[0].forecast
    assert days[1].rain == 2.4 and days[0].et0_reference == 7.1
    assert "archive-api" in open_meteo_url(28.6, 77.2, date(2020, 1, 1), date(2020, 2, 1), today=date(2025, 5, 1))
    assert "api.open-meteo.com/v1/forecast" in open_meteo_url(
        28.6, 77.2, date(2025, 4, 1), date(2025, 5, 10), today=date(2025, 5, 1)
    )
    with pytest.raises(ValueError, match="limit"):
        parse_open_meteo({"error": True, "reason": "Daily API request limit exceeded"})


def test_csv_parsing_reports_bad_rows() -> None:
    text = "date,tmax,tmin,rain,rh_mean,wind_10m\n2025-01-01,22,8,0,60,3\n2025-01-02,10,12,0,,\nbad,1,1,,,\n"
    days, errors = parse_weather_csv(text)
    assert len(days) == 1 and days[0].wind_2m == pytest.approx(wind_at_2m(3, 10)) and len(errors) == 2
    with pytest.raises(ValueError, match="header"):
        parse_weather_csv("a,b\n1,2\n")


def test_synthetic_weather_is_seeded_and_gives_sensible_et0() -> None:
    a = synthetic_weather(28.6, date(2025, 1, 1), date(2025, 12, 31), seed=3)
    assert a == synthetic_weather(28.6, date(2025, 1, 1), date(2025, 12, 31), seed=3)
    assert a != synthetic_weather(28.6, date(2025, 1, 1), date(2025, 12, 31), seed=4)
    et0 = [d.et0 for d in to_balance_weather(a, 28.6, 216)]
    assert 600 < sum(et0) < 2500 and all(x >= 0 for x in et0)
    july = sum(d.rain for d in a if d.day.month in (7, 8))
    january = sum(d.rain for d in a if d.day.month in (1, 2))
    assert july > january
