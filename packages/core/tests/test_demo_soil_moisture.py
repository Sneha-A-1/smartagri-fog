import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from smartagri_core import get_registry
from smartagri_core.cli import main as cli_main

PLUGIN = "data_generator:soil_moisture_demo"


def _run(**params):
    params.setdefault("demo_delay_ms", 0)
    return get_registry().create(PLUGIN, params).run()


def test_same_seed_gives_identical_series() -> None:
    assert _run(seed=7, days=10) == _run(seed=7, days=10)
    assert _run(seed=7, days=10)["measured_moisture"] != _run(seed=8, days=10)["measured_moisture"]


def test_output_is_labelled_synthetic_and_sized() -> None:
    out = _run(days=5, samples_per_day=12)
    assert out["data_origin"] == "synthetic"
    assert out["summary"]["n_readings"] == 60 == len(out["hours"])


@settings(max_examples=40, deadline=None)
@given(seed=st.integers(0, 10_000), rain=st.floats(0, 1), days=st.integers(1, 20))
def test_true_moisture_stays_within_physical_bounds(seed: int, rain: float, days: int) -> None:
    out = _run(seed=seed, rain_probability=rain, days=days, samples_per_day=6)
    assert all(0.12 - 1e-9 <= v <= 0.32 + 1e-9 for v in out["true_moisture"])


def test_progress_is_monotonic_and_ends_at_one() -> None:
    seen: list[float] = []
    get_registry().create(PLUGIN, {"days": 8, "demo_delay_ms": 0}).run(lambda f, m="": seen.append(f))
    assert seen == sorted(seen) and seen[-1] == pytest.approx(1.0)


def test_invalid_ranges_rejected() -> None:
    with pytest.raises(ValueError):
        get_registry().create(PLUGIN, {"wilting_point": 0.3, "field_capacity": 0.2})


def test_cli_lists_plugins(capsys) -> None:
    assert cli_main(["plugins", "list", "--kind", "scheduler"]) == 0
    out = capsys.readouterr().out
    assert "scheduler:heft" in out and "planned" in out
