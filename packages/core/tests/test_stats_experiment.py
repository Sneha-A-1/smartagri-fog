from __future__ import annotations

import numpy as np
import pytest
import yaml
from smartagri_core.cli import EXPERIMENT_TEMPLATE
from smartagri_core.experiment import AlgorithmSpec, ExperimentSpec, latex_tables, run_experiment, runs_to_csv
from smartagri_core.stats import a12, a12_magnitude, compare, holm, nemenyi_cd, summarize, wilcoxon_paired


def test_holm_matches_hand_calculation() -> None:
    # sorted: 0.01*3 = 0.03, 0.03*2 = 0.06, 0.04*1 = 0.04 -> monotone max -> 0.06
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_nemenyi_cd_matches_demsar_table() -> None:
    # Demšar (2006): q_0.05 = 2.343 for k = 3; CD = q * sqrt(k(k+1) / 6N)
    assert nemenyi_cd(3, 30) == pytest.approx(2.343 * np.sqrt(12 / 180), rel=1e-3)
    assert nemenyi_cd(5, 10) == pytest.approx(2.728 * np.sqrt(30 / 60), rel=1e-3)


def test_a12_direction_and_magnitude() -> None:
    assert a12([1, 2, 3], [1, 2, 3], True) == 0.5
    assert a12([4, 5, 6], [1, 2, 3], True) == 1.0
    assert a12([4, 5, 6], [1, 2, 3], False) == 0.0
    assert [a12_magnitude(v) for v in (0.52, 0.6, 0.68, 0.9, 0.1)] == [
        "negligible",
        "small",
        "medium",
        "large",
        "large",
    ]


def test_summarize_ci() -> None:
    s = summarize([1.0, 2.0, 3.0, 4.0, 5.0])
    assert s["mean"] == 3.0 and s["ci_low"] < 3.0 < s["ci_high"]
    assert summarize([])["n"] == 0


def test_wilcoxon_identical_is_one() -> None:
    assert wilcoxon_paired([1, 2, 3], [1, 2, 3]) == 1.0


def test_compare_detects_clear_difference_and_ranks_correctly() -> None:
    rng = np.random.default_rng(0)
    base = rng.normal(10, 1, 30)
    samples = {"slow": base + 3, "medium": base + 1.5, "fast": base}
    out = compare(samples, higher_is_better=False)
    assert out["significant"] and out["omnibus"]["p_value"] < 0.001
    assert out["rank_order"] == ["fast", "medium", "slow"]
    assert all(p["significant"] for p in out["pairwise"])
    fast_vs_slow = next(p for p in out["pairwise"] if {p["a"], p["b"]} == {"fast", "slow"})
    assert fast_vs_slow["better"] == "fast" and fast_vs_slow["magnitude"] == "large"


def test_compare_reports_no_difference_for_identical_algorithms() -> None:
    values = list(np.linspace(1, 2, 20))
    out = compare({"a": values, "b": values, "c": values}, higher_is_better=True)
    assert not out["significant"] and out["verdict"].startswith("No statistically significant")


def test_two_algorithms_use_wilcoxon() -> None:
    rng = np.random.default_rng(1)
    base = rng.normal(5, 1, 25)
    out = compare({"a": base, "b": base + 2}, higher_is_better=True)
    assert out["omnibus"]["test"] is None and out["significant"] and out["pairwise"][0]["better"] == "b"


def _spec(**kw) -> ExperimentSpec:
    defaults = dict(
        name="t",
        scenario={"duration_s": 600, "farms": 2},
        replications=3,
        algorithms=[AlgorithmSpec(placement="cloud_only"), AlgorithmSpec(placement="mct")],
    )
    defaults.update(kw)
    return ExperimentSpec(**defaults)


def test_spec_rejects_duplicate_algorithms_and_unknown_metrics() -> None:
    with pytest.raises(ValueError, match="distinct"):
        _spec(algorithms=[AlgorithmSpec(placement="mct"), AlgorithmSpec(placement="mct")])
    with pytest.raises(ValueError, match="Unknown metrics"):
        _spec(metrics=["happiness"])


def test_experiment_is_reproducible_and_exports() -> None:
    a, b = run_experiment(_spec()), run_experiment(_spec())
    strip = lambda r: [{k: v for k, v in run["metrics"].items() if k != "scheduling_overhead_us"} for run in r["runs"]]  # noqa: E731
    assert strip(a) == strip(b) and a["spec_sha256"] == b["spec_sha256"]
    assert a["data_origin"] == "synthetic" and len(a["runs"]) == 6
    csv_text = runs_to_csv(a)
    assert csv_text.count("\n") == 7 and csv_text.startswith("replication,seed,algorithm,")
    tex = latex_tables(a)
    assert r"\toprule" in tex and r"cloud\_only/fcfs" in tex and "Friedman" not in tex.split(r"\end{table}")[0]


def test_cli_template_is_a_valid_spec() -> None:
    spec = ExperimentSpec.model_validate(yaml.safe_load(EXPERIMENT_TEMPLATE))
    assert spec.replications == 30 and len(spec.algorithms) == 4
