"""Statistics for experiment results. Phase 1a: means with t-based 95% confidence intervals.

Paired significance tests (Wilcoxon, Friedman with Nemenyi post-hoc) and effect sizes arrive in Phase 1b.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy import stats as sps


def summarize(values: Sequence[float], confidence: float = 0.95) -> dict[str, float]:
    """Mean, standard deviation and a Student-t confidence interval, ignoring NaNs."""
    arr = np.asarray([v for v in values if v is not None and not math.isnan(v)], dtype=float)
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
