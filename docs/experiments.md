# Running experiments and reporting them

An **experiment** compares several algorithms on one scenario over many seeded replications, then tests whether
the differences are statistically significant. Its definition is saved and frozen once it has run, so every
number in a paper can be regenerated.

## In the browser

1. **Experiments** → **New experiment**.
2. Write the research question in **Research question or hypothesis**. It is stored with the results.
3. Set the **Scenario**: farm network size, workload intensity and duration. In researcher mode, also the cloud
   link speed and latency, failure rates and the batch window.
4. Add the **Algorithms to compare**. Each one is a placement policy plus a queue discipline.
5. Choose **Replications** (30 for papers) and click **Save and run**.
6. When it finishes, the results table shows each algorithm's mean ± 95% confidence half-width and its mean rank
   for every headline metric, with the test result. Click a metric to see every pairwise comparison and its
   effect size.
7. Download **LaTeX tables** for the paper, **CSV (all runs)** for your own analysis in Excel, R or Python, and
   the **Experiment file** (YAML) to archive alongside the paper.

To change a finished experiment, use **Duplicate to edit**. **Run again** repeats it with the same seeds and
should give identical numbers (except scheduler decision time, which is measured on the wall clock).

## From the command line

Useful for long experiments you want to leave running, for example overnight:

```powershell
uv run smartagri experiment template > experiments\rural-baseline.yaml
# edit the file in VS Code, then:
uv run smartagri experiment run experiments\rural-baseline.yaml --out D:\SmartAgriData\results\rural-baseline
```

The output folder receives `result.json`, `runs.csv`, `tables.tex` and a copy of the specification, `spec.yaml`.
Keep experiment files in the `experiments\` folder of the repository, so they are versioned with the code.

## Statistical method

Text you can adapt for a methods section:

> Each configuration was simulated for *n* = 30 independent replications. Replication *r* used seed *s₀ + r*,
> and within a replication every algorithm processed an identical workload trace (common random numbers), so
> observations are paired by replication. We report the mean and the 95% confidence interval based on Student's
> *t* distribution. Differences among *k* ≥ 3 algorithms were tested with the Friedman test (α = 0.05), and mean
> ranks are reported with the Nemenyi critical difference (Demšar, 2006). Pairwise differences were assessed
> with two-sided Wilcoxon signed-rank tests, paired by replication, with Holm's correction within each metric.
> Effect sizes are reported as the Vargha–Delaney *A₁₂* statistic, with the conventional thresholds of 0.56, 0.64
> and 0.71 for small, medium and large effects (Vargha & Delaney, 2000; Arcuri & Briand, 2011).

### What the results mean

| You see | It means |
| --- | --- |
| **Not significant** | The data can't tell the algorithms apart. Don't claim one is better. |
| **Significant** + a large effect size | A consistent and practically relevant difference. |
| **Significant** + a negligible effect size | A consistent but tiny difference (for example 100% vs 99.99%). Report it, but don't present it as an improvement. |
| A bold rank | The best-ranked algorithm on that metric, shown only when the overall test is significant. |

With fewer than about 10 replications, pairwise tests can't reach significance after correction. With 6
replications, the smallest possible Wilcoxon *p*-value is 0.031, which becomes 0.094 after Holm correction for
3 pairs. Use 30.

### References

- Demšar, J. (2006). Statistical comparisons of classifiers over multiple data sets. *Journal of Machine Learning
  Research*, 7, 1–30.
- Vargha, A., & Delaney, H. D. (2000). A critique and improvement of the CL common language effect size statistics
  of McGraw and Wong. *Journal of Educational and Behavioral Statistics*, 25(2), 101–132.
- Arcuri, A., & Briand, L. (2011). A practical guide for using statistical tests to assess randomized algorithms
  in software engineering. *ICSE 2011*, 1–10.

Check each reference against the published version before citing it.
