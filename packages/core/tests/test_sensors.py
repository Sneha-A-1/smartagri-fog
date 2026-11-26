"""Simulated devices, sensor assimilation and the closed-loop irrigation experiment."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from smartagri_core.agro.fao56 import CROPS, SOILS, DayWeather, IrrigationPolicy, water_balance
from smartagri_core.agro.sensors import (
    SensorModel,
    closed_loop_season,
    daily_depletion_observations,
    depletion_from_theta,
    soil_moisture_readings,
    theta_from_depletion,
    true_balance,
    valve_readings,
)
from smartagri_core.registry import get_registry

WHEAT, LOAM = CROPS["wheat"], SOILS["loam"]
SOWING = date(2025, 11, 15)
WEATHER = [DayWeather(SOWING + timedelta(days=i), 4.0, 15.0 if i % 23 == 5 else 0.0) for i in range(125)]


def test_theta_depletion_round_trip() -> None:
    zr = 1.5
    assert theta_from_depletion(0, LOAM, zr) == LOAM.field_capacity
    taw = LOAM.taw_per_m * zr
    assert theta_from_depletion(taw, LOAM, zr) == pytest.approx(LOAM.wilting_point)
    assert depletion_from_theta(theta_from_depletion(40, LOAM, zr), LOAM, zr) == pytest.approx(40)
    assert depletion_from_theta(0.9, LOAM, zr) == 0 and depletion_from_theta(0.0, LOAM, zr) == pytest.approx(taw)


def test_noise_free_sensor_reports_the_truth_and_is_deterministic() -> None:
    model = SensorModel(noise_sd=0.0, et_multiplier=1.0)
    truth = true_balance(WEATHER, WHEAT, LOAM, SOWING, 1.5, IrrigationPolicy(), model)
    start = datetime(2025, 11, 15, tzinfo=UTC)
    readings = soil_moisture_readings(truth, LOAM, 1.5, start, start + timedelta(days=30), 30, model, "dev1")
    assert len(readings) == 30 * 48 + 1 - 0  # every 30 minutes, both ends included
    obs = daily_depletion_observations(readings, LOAM, 1.5)
    by_day = {d.day: d.depletion for d in truth}
    day = SOWING + timedelta(days=20)
    assert obs[day] == pytest.approx(by_day[day], abs=1.0)  # late-evening mean is close to the end-of-day value
    noisy = SensorModel(noise_sd=0.02, dropout=0.2)
    a = soil_moisture_readings(truth, LOAM, 1.5, start, start + timedelta(days=3), 30, noisy, "dev1")
    assert a == soil_moisture_readings(truth, LOAM, 1.5, start, start + timedelta(days=3), 30, noisy, "dev1")
    assert a != soil_moisture_readings(truth, LOAM, 1.5, start, start + timedelta(days=3), 30, noisy, "dev2")
    assert 0.6 * 3 * 48 < len(a) < 0.95 * 3 * 48


def test_valve_opens_on_irrigation_days() -> None:
    truth = true_balance(WEATHER, WHEAT, LOAM, SOWING, 1.5, IrrigationPolicy(), SensorModel(et_multiplier=1.0))
    irrigated = next(d for d in truth if d.irrigation_gross > 0)
    start = datetime.combine(irrigated.day, datetime.min.time(), tzinfo=UTC)
    states = dict(valve_readings(truth, start, start + timedelta(hours=71)))
    assert states[start.replace(hour=5)] == 0 and states[start.replace(hour=6)] == 1
    assert sum(states.values()) == pytest.approx(irrigated.irrigation_gross / 5.0, abs=1)  # continues past midnight


def test_observations_replace_the_model_and_are_accounted_for() -> None:
    base = water_balance(WEATHER, WHEAT, LOAM, SOWING)
    day = SOWING + timedelta(days=30)
    model_value = next(d.depletion for d in base.days if d.day == day)
    res = water_balance(WEATHER, WHEAT, LOAM, SOWING, observations={day: model_value + 25})
    d = next(x for x in res.days if x.day == day)
    assert d.depletion == pytest.approx(model_value + 25) and d.correction == pytest.approx(25)
    assert d.model_depletion == pytest.approx(model_value)
    inflow = sum(x.effective_rain + x.irrigation_net for x in res.days)
    outflow = sum(x.etc_adj + x.deep_percolation for x in res.days)
    assert res.days[-1].depletion == pytest.approx(outflow - inflow + sum(x.correction for x in res.days), abs=1e-9)
    assert res.summary(WHEAT)["sensor_days"] == 1


def test_closed_loop_strategies() -> None:
    pol = IrrigationPolicy()
    exact = SensorModel(noise_sd=0.0, dropout=0.0, et_multiplier=1.0)
    runs = {
        s: closed_loop_season(WEATHER, WHEAT, LOAM, SOWING, 1.5, pol, exact, s, "k")
        for s in ("model", "sensor", "fused", "oracle")
    }
    assert runs["oracle"]["belief_error_mm"] == 0
    assert runs["model"] == pytest.approx(runs["oracle"])  # a perfect model needs no sensor
    assert runs["sensor"] == pytest.approx(runs["oracle"])  # a perfect sensor is the truth
    biased = SensorModel(noise_sd=0.01, dropout=0.0, et_multiplier=1.3)
    model = closed_loop_season(WEATHER, WHEAT, LOAM, SOWING, 1.5, pol, biased, "model", "k")
    sensor = closed_loop_season(WEATHER, WHEAT, LOAM, SOWING, 1.5, pol, biased, "sensor", "k")
    assert sensor["stress_days"] < model["stress_days"] and sensor["belief_error_mm"] < model["belief_error_mm"]
    with pytest.raises(ValueError):
        closed_loop_season(WEATHER, WHEAT, LOAM, SOWING, 1.5, pol, biased, "magic", "k")


def test_experiment_plugin() -> None:
    reg = get_registry()
    reg.ensure_loaded()
    out = reg.create("simulation:sensor_irrigation", {"seasons": 6}).run()
    assert out["kind"] == "simulation.strategy_comparison" and set(out["labels"]) == {
        "model",
        "sensor",
        "fused",
        "oracle",
    }
    assert out["tests"]["stress_days"]["omnibus"]["test"] == "friedman"
    again = reg.create("simulation:sensor_irrigation", {"seasons": 6}).run()
    assert again["samples"] == out["samples"]
