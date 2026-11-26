"""Statistics for comparing algorithms over replications.

The procedure follows common practice for comparing several algorithms over paired runs
(Demšar, JMLR 2006; Arcuri & Briand, ICSE 2011):

* mean with a Student-t 95% confidence interval per algorithm and metric;
* Friedman test across all algorithms (k >= 3), with mean ranks and the Nemenyi critical difference;
* pairwise Wilcoxon signed-rank tests paired by replication seed, Holm-corrected within each metric;
* Vargha-Delaney A12 effect size with its conventional magnitude label.

Replications are paired because every algorithm in replication r saw the same workload (common random numbers).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import combinations
from typing import Any

import numpy as np
from scipy import stats as sps

ALPHA = 0.05


def summarize(values: Sequence[float], confidence: float = 0.95) -> dict[str, float]:
    """Mean, standard deviation and a Student-t confidence interval, ignoring NaNs."""
    arr = _clean(values)
    n = int(arr.size)
    if n == 0:
        return {
            "n": 0,
            "mean": math.nan,
            "std": math.nan,
            "ci_low": math.nan,
            "ci_high": math.nan,
            "half_width": math.nan,
        }
    mean = float(arr.mean())
    if n == 1:
        return {"n": 1, "mean": mean, "std": 0.0, "ci_low": math.nan, "ci_high": math.nan, "half_width": math.nan}
    std = float(arr.std(ddof=1))
    half = float(sps.t.ppf((1 + confidence) / 2, n - 1) * std / math.sqrt(n))
    return {"n": n, "mean": mean, "std": std, "ci_low": mean - half, "ci_high": mean + half, "half_width": half}


def a12(a: Sequence[float], b: Sequence[float], higher_is_better: bool) -> float:
    """Vargha-Delaney A12: probability that a run of A is better than a run of B (ties count half)."""
    x, y = _clean(a), _clean(b)
    if x.size == 0 or y.size == 0:
        return math.nan
    diff = x[:, None] - y[None, :]
    if not higher_is_better:
        diff = -diff
    return float(((diff > 0).sum() + 0.5 * (diff == 0).sum()) / diff.size)


def a12_magnitude(value: float) -> str:
    """Thresholds from Vargha & Delaney (2000): 0.56, 0.64 and 0.71 (symmetric around 0.5)."""
    if math.isnan(value):
        return "n/a"
    d = abs(value - 0.5)
    return "negligible" if d < 0.06 else "small" if d < 0.14 else "medium" if d < 0.21 else "large"


def wilcoxon_paired(a: Sequence[float], b: Sequence[float]) -> float:
    """Two-sided Wilcoxon signed-rank p-value for paired samples. Identical samples give p = 1."""
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = x[mask], y[mask]
    if x.size < 2 or np.allclose(x, y):
        return 1.0
    try:
        return float(sps.wilcoxon(x, y, zero_method="wilcox", alternative="two-sided").pvalue)
    except ValueError:
        return 1.0


def holm(pvalues: Sequence[float]) -> list[float]:
    """Holm step-down adjustment of a family of p-values."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def nemenyi_cd(k: int, n: int, alpha: float = ALPHA) -> float:
    """Nemenyi critical difference for mean ranks of k algorithms over n paired replications."""
    q = sps.studentized_range.ppf(1 - alpha, k, np.inf) / math.sqrt(2)
    return float(q * math.sqrt(k * (k + 1) / (6.0 * n)))


def compare(samples: dict[str, Sequence[float]], higher_is_better: bool, alpha: float = ALPHA) -> dict[str, Any]:
    """Full comparison of algorithms on one metric. ``samples[alg][r]`` is the value in replication r.

    Returns summaries, mean ranks (1 = best), the omnibus test, pairwise tests and a plain-language verdict.
    The ranking is reported as meaningful only when the omnibus test (Friedman for k >= 3, Wilcoxon for k = 2)
    is significant at ``alpha``.
    """
    algs = list(samples)
    k = len(algs)
    n_rows = min(len(samples[a]) for a in algs)
    matrix = np.array([[samples[a][r] for a in algs] for r in range(n_rows)], dtype=float).reshape(n_rows, k)
    complete = matrix[~np.isnan(matrix).any(axis=1)]
    n = complete.shape[0]

    ranks = np.full(k, math.nan)
    if n > 0:
        signed = -complete if higher_is_better else complete
        ranks = np.mean([sps.rankdata(row) for row in signed], axis=0)

    omnibus: dict[str, Any] = {"test": None, "statistic": None, "p_value": None, "critical_difference": None}
    if k >= 3 and n >= 2:
        if np.allclose(complete, complete[:, :1]):
            omnibus.update(test="friedman", statistic=0.0, p_value=1.0)
        else:
            res = sps.friedmanchisquare(*[complete[:, j] for j in range(k)])
            p = float(res.pvalue)
            omnibus.update(test="friedman", statistic=float(res.statistic), p_value=1.0 if math.isnan(p) else p)
        omnibus["critical_difference"] = nemenyi_cd(k, n, alpha)

    pairs: list[dict[str, Any]] = []
    raw_p: list[float] = []
    for i, j in combinations(range(k), 2):
        p = wilcoxon_paired(complete[:, i], complete[:, j]) if n else 1.0
        raw_p.append(p)
        effect = a12(complete[:, i], complete[:, j], higher_is_better) if n else math.nan
        pairs.append({"a": algs[i], "b": algs[j], "p_value": p, "a12": effect, "magnitude": a12_magnitude(effect)})
    for pair, adj in zip(pairs, holm(raw_p), strict=True):
        pair["p_holm"] = adj
        pair["significant"] = adj < alpha
        pair["better"] = (pair["a"] if pair["a12"] > 0.5 else pair["b"]) if pair["significant"] else None

    if k >= 3:
        significant = omnibus["p_value"] is not None and omnibus["p_value"] < alpha
    else:
        significant = bool(pairs and pairs[0]["significant"])

    order = sorted(range(k), key=lambda j: (ranks[j], algs[j]))
    if n < 2:
        verdict = "Not enough replications to test for differences."
    elif not significant:
        verdict = (
            f"No statistically significant difference between the algorithms ({_omnibus_text(omnibus, pairs, k)})."
        )
    else:
        best_rank = ranks[order[0]]
        best = [algs[j] for j in order if abs(ranks[j] - best_rank) < 1e-9]
        verdict = (
            f"The algorithms differ significantly ({_omnibus_text(omnibus, pairs, k)}). "
            f"Best mean rank: {', '.join(best)}{' (tied)' if len(best) > 1 else ''}."
        )

    return {
        "n": n,
        "higher_is_better": higher_is_better,
        "summaries": {a: _nan_to_none(summarize(complete[:, j])) for j, a in enumerate(algs)},
        "mean_ranks": {a: (None if math.isnan(ranks[j]) else float(ranks[j])) for j, a in enumerate(algs)},
        "rank_order": [algs[j] for j in order],
        "omnibus": omnibus,
        "pairwise": [_nan_to_none(p) for p in pairs],
        "significant": significant,
        "verdict": verdict,
    }


def _omnibus_text(omnibus: dict[str, Any], pairs: list[dict[str, Any]], k: int) -> str:
    if k >= 3 and omnibus["p_value"] is not None:
        return f"Friedman {_p(omnibus['p_value'])}"
    if pairs:
        return f"Wilcoxon {_p(pairs[0]['p_holm'])}"
    return "no test"


def _p(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def _nan_to_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in d.items()}


def _clean(values: Sequence[float]) -> np.ndarray:
    return np.asarray([v for v in values if v is not None and not math.isnan(v)], dtype=float)
