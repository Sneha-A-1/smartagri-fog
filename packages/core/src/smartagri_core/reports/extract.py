"""Extractors: one job result (by its ``kind``) -> a :class:`Report`.

Each extractor only restates what the result contains. Unknown kinds get a generic report (parameters,
summary values and the raw result), so every finished job can still be exported.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from smartagri_core.reports.model import CI, Column, Figure, Report, Series, Table, fmt_num, summary_to_ci

Extractor = Callable[[dict[str, Any]], Report]
EXTRACTORS: dict[str, Extractor] = {}

KIND_TITLES = {
    "simulation.aura_evaluation": "AURA evaluation",
    "experiment": "Experiment",
    "simulation.comparison": "Placement policy comparison",
    "simulation.optimizer_benchmark": "Optimiser benchmark",
    "simulation.dqn_training": "DQN training and evaluation",
    "simulation.strategy_comparison": "Strategy comparison",
    "simulation.case_study.ifogsim_eeg": "iFogSim EEG case study (validation)",
    "simulation.single_run": "Single simulation run",
    "simulation.dag_comparison": "DAG scheduling comparison",
}


def extractor(kind: str) -> Callable[[Extractor], Extractor]:
    def deco(fn: Extractor) -> Extractor:
        EXTRACTORS[kind] = fn
        return fn

    return deco


def build_report(result: dict[str, Any]) -> Report:
    kind = str(result.get("kind", ""))
    report = EXTRACTORS.get(kind, generic)(result)
    report.kind = kind
    report.data_origin = str(result.get("data_origin", "unknown"))
    report.params = report.params or dict(result.get("params") or result.get("spec") or {})
    report.provenance = report.provenance or dict(result.get("provenance") or {})
    if report.data_origin in ("synthetic", "simulated"):
        report.caveats.insert(
            0,
            "All values come from simulation with synthetic workloads (data origin: "
            f"{report.data_origin}); none were measured on real hardware.",
        )
    return report


def supported(kind: str) -> bool:
    return kind in EXTRACTORS


def _mark(outcome: str | None) -> str:
    return {"better": "better", "worse": "worse"}.get(outcome or "", "")


def _ci_series(name: str, labels: list[str], summaries: list[dict | None], emphasis: bool = False) -> Series:
    means = [s.get("mean") if s else None for s in summaries]
    lows = [s.get("ci_low") if s else None for s in summaries]
    highs = [s.get("ci_high") if s else None for s in summaries]
    return Series(name, list(range(len(labels))), means, lows, highs, emphasis)


def _dotwhisker(
    key: str,
    caption: str,
    label: str,
    unit: str,
    names: list[str],
    summaries: list[dict | None],
    emphasis: str | None = None,
) -> Figure:
    s = _ci_series(label, names, summaries)
    return Figure(
        key,
        caption,
        "dotwhisker",
        xlabel=f"{label} ({unit})" if unit else label,
        labels=names,
        series=[s],
        note=emphasis or "",
    )


# --- AURA evaluation -----------------------------------------------------------------------------------


@extractor("simulation.aura_evaluation")
def aura_evaluation(r: dict[str, Any]) -> Report:
    names: dict[str, str] = r["names"]
    algs: list[str] = r["algorithms"]
    scenarios = list(r["table"])
    info = r["metric_info"]
    p = r["params"]
    summary = [
        f"{len(algs)} algorithms (AURA, its ablations and baselines) were run on {len(scenarios)} scenarios with "
        f"{p['replications']} seeded workloads each, {p['duration_s'] / 60:g} simulated minutes per run at workload "
        f"intensity {p['intensity']:g}. Every algorithm saw the same workloads.",
        "Each other algorithm was compared with AURA per scenario and metric by a paired Wilcoxon signed-rank test, "
        "Holm-corrected over the comparisons with AURA, with the Vargha-Delaney A12 effect size (α = 0.05).",
    ]
    for h in r["hypotheses"]:
        per = "; ".join(
            f"{r['scenario_info'].get(e['scenario'], [e['scenario']])[0]}: {e['verdict']}" for e in h["evidence"]
        )
        summary.append(
            f"{h['id']} ({h['statement']}) Verdict: {h['verdict']}." + (f" Per scenario: {per}." if per else "")
        )

    metric_cols = [m for m in r["metrics"] if m != "scheduling_overhead_us"]
    tables: list[Table] = []
    for sc in scenarios:
        cols = [Column("Algorithm", kind="text")] + [Column(info[m][0], info[m][1], "ci") for m in metric_cols]
        rows = []
        for a in algs:
            row: list[Any] = [names[a]]
            for m in metric_cols:
                mark = ""
                if a != "aura":
                    t = next((x for x in r["tests"][sc][m]["rows"] if x["other"] == names[a]), None)
                    mark = _mark(t["outcome"] if t else None)
                row.append(summary_to_ci(r["table"][sc][a][m], mark))
            rows.append(row)
        title = r["scenario_info"].get(sc, [sc])[0]
        tables.append(
            Table(
                f"results_{sc}",
                f"{title}: mean ± 95% CI over {p['replications']} workloads.",
                cols,
                rows,
                notes="▼: AURA significantly better than this algorithm; ▲: this algorithm significantly "
                "better than AURA (paired Wilcoxon, Holm-corrected, α = 0.05).",
                highlight_row=algs.index("aura"),
            )
        )
    hyp_rows = [[h["id"], h["statement"], h["verdict"]] for h in r["hypotheses"]]
    tables.insert(
        0,
        Table(
            "hypotheses",
            "Hypotheses and verdicts computed from the tests.",
            [Column("Hypothesis", kind="text"), Column("Statement", kind="text"), Column("Verdict", kind="text")],
            hyp_rows,
        ),
    )
    rt = r.get("runtime_s", {})
    if rt:
        tables.append(
            Table(
                "runtime",
                "Wall-clock time per simulation on the machine that ran the evaluation.",
                [Column("Algorithm", kind="text"), Column("Run time", "s", "ci")],
                [[names[a], summary_to_ci(rt[a])] for a in algs if a in rt],
            )
        )

    figures: list[Figure] = []
    baseline_pick = [
        a for a in ["aura", "mct", "edge_ward", "cloud_only", "least_loaded", "nsga2", "min_min"] if a in algs
    ][:6]
    ablation_pick = [a for a in algs if a.startswith("aura")][:6]
    sc_labels = [r["scenario_info"].get(sc, [sc])[0] for sc in scenarios]
    for m in ["urgent_deadline_success_rate", "aoi_violation_rate", "decision_value_pct", "energy_dynamic_j", "cost"]:
        if m not in r["metrics"]:
            continue
        figures.append(
            Figure(
                f"baselines_{m}",
                f"{info[m][0]} by scenario: AURA and baselines (mean, 95% CI).",
                "bars",
                ylabel=f"{info[m][0]} ({info[m][1]})" if info[m][1] else info[m][0],
                labels=sc_labels,
                series=[
                    _ci_series(names[a], sc_labels, [r["table"][sc][a][m] for sc in scenarios], a == "aura")
                    for a in baseline_pick
                ],
            )
        )
    for m in ["urgent_deadline_success_rate", "aoi_violation_rate"]:
        if m in r["metrics"] and len(ablation_pick) > 1:
            figures.append(
                Figure(
                    f"ablations_{m}",
                    f"{info[m][0]} by scenario: AURA and its ablations (mean, 95% CI).",
                    "bars",
                    ylabel=f"{info[m][0]} ({info[m][1]})",
                    labels=sc_labels,
                    series=[
                        _ci_series(names[a], sc_labels, [r["table"][sc][a][m] for sc in scenarios], a == "aura")
                        for a in ablation_pick
                    ],
                )
            )
    for sc in scenarios:
        log = r.get("aura_logs", {}).get(sc)
        if log and log.get("reservation"):
            res = log["reservation"]
            ev = r.get("events", {}).get(sc, {})
            shading = [
                (e["start_s"] / 60, min(e["end_s"], p["duration_s"]) / 60, e["label"])
                for e in (ev.get("events", []) if isinstance(ev, dict) else [])
            ]
            figures.append(
                Figure(
                    f"reservation_{sc}",
                    f"AURA's capacity reservation over time, {r['scenario_info'].get(sc, [sc])[0]} "
                    "(first workload; shaded: scenario event).",
                    "lines",
                    xlabel="Simulated time (min)",
                    ylabel="Reserved share (%)",
                    shading=shading,
                    series=[
                        Series("Edge devices", [x["time_s"] / 60 for x in res], [100 * x["edge"] for x in res]),
                        Series("Fog servers", [x["time_s"] / 60 for x in res], [100 * x["fog"] for x in res]),
                    ],
                )
            )
    caveats = ["Preemption of running tasks and light task variants are not implemented in this version of AURA."]
    return Report(
        "AURA evaluation", "Scenarios, ablations and baselines", "", summary, tables, figures, caveats=caveats
    )


# --- experiments and policy comparisons ---------------------------------------------------------------


@extractor("experiment")
def experiment(r: dict[str, Any]) -> Report:
    algs = r["algorithms"]
    info = r["metric_info"]
    metrics = r["headline_metrics"]
    n = r["spec"].get("replications")
    summary = [
        f'Experiment "{r["spec"].get("name", "")}": {len(algs)} algorithms, {n} paired replications each on identical '
        "workloads. Differences were tested with the Friedman test and Holm-corrected pairwise Wilcoxon tests, "
        "with A12."
    ]
    rows = []
    for a in algs:
        rows.append([a] + [summary_to_ci(r["analysis"][m]["summaries"].get(a)) for m in metrics])
    cols = [Column("Algorithm", kind="text")] + [Column(info[m][0], info[m][1], "ci") for m in metrics]
    tables = [Table("results", f"Mean ± 95% CI over {n} replications.", cols, rows)]
    verdict_rows = [[info[m][0], r["analysis"][m].get("verdict", "")] for m in metrics]
    tables.append(
        Table(
            "tests",
            "Friedman test outcome per metric.",
            [Column("Metric", kind="text"), Column("Outcome", kind="text")],
            verdict_rows,
        )
    )
    for m in metrics:
        summary.append(f"{info[m][0]}: {r['analysis'][m].get('verdict', '')}")
    figures = [
        _dotwhisker(
            f"ci_{m}",
            f"{info[m][0]}: mean and 95% CI.",
            info[m][0],
            info[m][1],
            algs,
            [r["analysis"][m]["summaries"].get(a) for a in algs],
        )
        for m in metrics[:6]
    ]
    return Report(KIND_TITLES["experiment"], str(r["spec"].get("name", "")), "", summary, tables, figures)


@extractor("simulation.comparison")
def comparison(r: dict[str, Any]) -> Report:
    comp = r["comparison"]
    algs = list(comp)
    info = r["metric_info"]
    metrics = r["headline_metrics"]
    p = r["params"]
    summary = [
        f"{len(algs)} placement policies, {p.get('replications')} replications each on identical workloads, queue "
        f"discipline {p.get('discipline')}, scenario {p.get('stress', 'none')}, {p.get('duration_s')} simulated "
        "seconds "
        f"at intensity {p.get('intensity')}. No significance tests are run by this plugin; use an experiment for those."
    ]
    if r.get("scenario_events"):
        summary.append(
            "Scenario events: "
            + "; ".join(
                f"{e['label']} from {e['start_s'] / 60:g} to {e['end_s'] / 60:g} min ({e['detail']})"
                for e in r["scenario_events"]
            )
        )
    cols = [Column("Policy", kind="text")] + [Column(info[m][0], info[m][1], "ci") for m in metrics]
    rows = [[a] + [summary_to_ci(comp[a].get(m)) for m in metrics] for a in algs]
    figures = [
        _dotwhisker(
            f"ci_{m}", f"{info[m][0]}: mean and 95% CI.", info[m][0], info[m][1], algs, [comp[a].get(m) for a in algs]
        )
        for m in metrics[:6]
    ]
    return Report(
        KIND_TITLES["simulation.comparison"],
        "",
        "",
        summary,
        [Table("results", f"Mean ± 95% CI over {p.get('replications')} replications.", cols, rows)],
        figures,
    )


# --- optimisation and learning ------------------------------------------------------------------------


@extractor("simulation.optimizer_benchmark")
def optimizer_benchmark(r: dict[str, Any]) -> Report:
    t = r["table"]
    algs = list(t)
    names = r["names"]
    s = r["summary"]
    summary = [
        f"{s['instances']} frozen scheduling windows, {s['replications']} seeded runs per optimiser and window, "
        f"{s['budget']} objective evaluations per run. Fitness is the scheduler's estimate for a window (lower is "
        f"better). {s['verdict']} Lowest mean fitness: {s['best_mean_fitness']}."
    ]
    cols = [
        Column("Optimiser", kind="text"),
        Column("Fitness", kind="ci"),
        Column("Gain over Min-Min", "%", "ci"),
        Column("Runs better than Min-Min", "%"),
        Column("Weighted misses", "share", "ci"),
        Column("Mean response", "s", "ci"),
        Column("Energy", "J", "ci"),
        Column("Run time", "ms", "ci"),
    ]
    rows = []
    for a in algs:
        x = t[a]
        rows.append(
            [
                names[a],
                summary_to_ci(x["fitness"]),
                summary_to_ci(x.get("improvement_vs_min_min_pct")),
                x.get("better_than_min_min_pct"),
                summary_to_ci(x["objectives"]["weighted_miss"]),
                summary_to_ci(x["objectives"]["mean_response_s"]),
                summary_to_ci(x["objectives"]["energy_j"]),
                summary_to_ci(x.get("runtime_ms")),
            ]
        )
    conv = r["convergence"]
    figures = [
        Figure(
            "convergence",
            "Best fitness found so far, averaged over every window and run.",
            "lines",
            xlabel="Objective evaluations",
            ylabel="Fitness",
            series=[Series(names[a], conv["evaluations"], v, emphasis=False) for a, v in conv["mean"].items()],
        ),
        _dotwhisker(
            "final_fitness",
            "Final fitness: mean and 95% CI (lower is better).",
            "Fitness",
            "",
            [names[a] for a in algs],
            [t[a]["fitness"] for a in algs],
        ),
    ]
    if r.get("pareto"):
        front = r["pareto"]["front"]
        figures.append(
            Figure(
                "pareto",
                "NSGA-II Pareto front for the first window (energy against mean response); crosses: the "
                "answers of the other methods.",
                "scatter",
                xlabel="Dynamic energy (J)",
                ylabel="Mean response (s)",
                series=[
                    Series("NSGA-II front", [f["energy_j"] for f in front], [f["mean_response_s"] for f in front]),
                    Series(
                        "Answers",
                        [o["energy_j"] for o in r["pareto"]["points"].values()],
                        [o["mean_response_s"] for o in r["pareto"]["points"].values()],
                        emphasis=True,
                    ),
                ],
            )
        )
    return Report(
        KIND_TITLES["simulation.optimizer_benchmark"],
        "",
        "",
        summary,
        [Table("results", "Results per optimiser (mean ± 95% CI).", cols, rows)],
        figures,
    )


@extractor("simulation.dqn_training")
def dqn_training(r: dict[str, Any]) -> Report:
    names = r.get("names") or {k: k for k in r["policies"]}
    pol = r["policies"]
    s = r["summary"]
    summary = [
        f"The DQN scheduler was trained for {s['episodes']} episodes on fresh simulated workloads "
        f"({r['training_seconds']} s of computing), then compared with online baselines on "
        f"{s['evaluation_replications']} held-out workloads. {s['verdict']}"
    ]
    info = {
        "deadline_success_rate": ("Deadlines met", "%"),
        "urgent_deadline_success_rate": ("Urgent deadlines met", "%"),
        "mean_response_s": ("Mean response", "s"),
        "p95_response_s": ("95th pct response", "s"),
        "energy_dynamic_j": ("Dynamic energy", "J"),
        "cost": ("Cloud cost", "$"),
        "scheduling_overhead_us": ("Decision time", "µs"),
    }
    cols = [Column("Policy", kind="text")] + [Column(*info[m], kind="ci") for m in r["metrics"]]
    rows = [[names[k]] + [summary_to_ci(r["table"][k][m]) for m in r["metrics"]] for k in pol]
    h = r["history"]
    ep = [x["episode"] for x in h]
    figures = [
        Figure(
            "learning_deadlines",
            "Deadlines met per training episode (while still exploring).",
            "lines",
            xlabel="Training episode",
            ylabel="Deadlines met (%)",
            series=[Series("DQN", ep, [x["deadline_success_rate"] for x in h], emphasis=True)],
        ),
        Figure(
            "learning_reward",
            "Mean reward per decision per training episode.",
            "lines",
            xlabel="Training episode",
            ylabel="Mean reward",
            series=[Series("DQN", ep, [x["mean_reward"] for x in h], emphasis=True)],
        ),
        _dotwhisker(
            "heldout_deadlines",
            "Deadlines met on held-out workloads: mean and 95% CI.",
            "Deadlines met",
            "%",
            [names[k] for k in pol],
            [r["table"][k]["deadline_success_rate"] for k in pol],
        ),
        _dotwhisker(
            "heldout_energy",
            "Dynamic energy on held-out workloads: mean and 95% CI.",
            "Dynamic energy",
            "J",
            [names[k] for k in pol],
            [r["table"][k]["energy_dynamic_j"] for k in pol],
        ),
    ]
    return Report(
        KIND_TITLES["simulation.dqn_training"],
        "",
        "",
        summary,
        [Table("heldout", "Held-out comparison (mean ± 95% CI).", cols, rows)],
        figures,
    )


# --- agriculture and data retrieval -------------------------------------------------------------------


@extractor("simulation.strategy_comparison")
def strategy_comparison(r: dict[str, Any]) -> Report:
    labels: dict[str, str] = r["labels"]
    keys = list(labels)
    info = r["metric_info"]
    metrics = list(r["summary"])
    summary = [r.get("description", "")]
    for m in metrics:
        if m in r.get("tests", {}):
            summary.append(f"{info[m][0]}: {r['tests'][m].get('verdict', '')}")
    cols = [Column("Strategy", kind="text")] + [Column(info[m][0], kind="ci") for m in metrics]
    rows = [[labels[k]] + [summary_to_ci(r["summary"][m].get(k)) for m in metrics] for k in keys]
    figures = [
        _dotwhisker(
            f"ci_{m}",
            f"{info[m][0]}: mean and 95% CI.",
            info[m][0],
            "",
            [labels[k] for k in keys],
            [r["summary"][m].get(k) for k in keys],
        )
        for m in (r.get("highlight") or metrics[:2])
        if m in r["summary"]
    ]
    return Report(
        r.get("title", KIND_TITLES["simulation.strategy_comparison"]),
        "",
        "",
        summary,
        [Table("results", "Mean ± 95% CI over the replications.", cols, rows)],
        figures,
    )


@extractor("simulation.case_study.ifogsim_eeg")
def ifogsim_eeg(r: dict[str, Any]) -> Report:
    rows_in = r["rows"]
    summary = [
        f"Rebuild of the EEG Tractor Beam case study from {r['paper']['citation']} (DOI {r['paper']['doi']}). "
        f"{r['summary']['replications']} replications of {r['summary']['simulated_s_per_run']:g} simulated seconds per "
        "cell.",
        r.get("paper_values_note", ""),
    ]
    summary += [
        f"{'Reproduced' if c['holds'] else 'Not reproduced'}: {c['claim']} ({c['paper']})." for c in r["checks"]
    ]
    cols = [
        Column("Headset", kind="text"),
        Column("Placement", kind="text"),
        Column("Config", kind="num", decimals=0),
        Column("Gateways", kind="num", decimals=0),
        Column("Loop delay", "ms", "ci"),
        Column("Paper loop delay", "ms"),
        Column("Network usage", "KB"),
        Column("Paper network usage", "KB"),
    ]
    rows = [
        [
            x["headset"],
            x["placement"],
            x["config"],
            x["gateways"],
            summary_to_ci(x["loop_delay_ms"]),
            x.get("paper_loop_delay_ms"),
            _mean(x.get("network_usage_kb")),
            x.get("paper_network_usage_kb"),
        ]
        for x in rows_in
    ]
    checks = Table(
        "checks",
        "Qualitative findings of the paper and whether they were reproduced.",
        [Column("Finding", kind="text"), Column("Paper", kind="text"), Column("Reproduced", kind="text")],
        [[c["claim"], c["paper"], "yes" if c["holds"] else "no"] for c in r["checks"]],
    )
    figures = []
    for headset in sorted({x["headset"] for x in rows_in}):
        sub = [x for x in rows_in if x["headset"] == headset]
        configs = sorted({x["config"] for x in sub})
        labels = [f"Config {c}" for c in configs]
        for field, label, unit in (
            ("loop_delay_ms", "Control-loop delay", "ms"),
            ("network_usage_kb", "Network usage", "KB"),
        ):
            series = []
            for pl in sorted({x["placement"] for x in sub}):
                vals = [next((x for x in sub if x["placement"] == pl and x["config"] == c), None) for c in configs]
                series.append(
                    _ci_series(
                        pl.replace("_", "-"),
                        labels,
                        [
                            v[field] if v and isinstance(v[field], dict) else {"mean": _mean(v[field]) if v else None}
                            for v in vals
                        ],
                    )
                )
            figures.append(
                Figure(
                    f"{field}_{headset}",
                    f"{label}, headset {headset}, by topology configuration.",
                    "bars",
                    ylabel=f"{label} ({unit})",
                    labels=labels,
                    series=series,
                    log_y=field == "loop_delay_ms",
                )
            )
    return Report(
        KIND_TITLES["simulation.case_study.ifogsim_eeg"],
        "Simulator validation",
        "",
        summary,
        [Table("cells", "Simulated values next to the values read from the paper's figures.", cols, rows), checks],
        figures,
    )


def _mean(v: Any) -> float | None:
    if isinstance(v, dict):
        return v.get("mean")
    return v if isinstance(v, (int, float)) else None


# --- anything else ------------------------------------------------------------------------------------


def generic(r: dict[str, Any]) -> Report:
    kind = str(r.get("kind", "result"))
    rows: list[list[Any]] = []
    for key, value in (r.get("summary") or {}).items():
        if isinstance(value, (int, float, str, bool)):
            rows.append([key.replace("_", " "), value])
    metrics = r.get("metrics")
    if isinstance(metrics, dict):
        info = r.get("metric_info", {})
        for key, value in metrics.items():
            if isinstance(value, (int, float)) and not (isinstance(value, float) and math.isnan(value)):
                name = info.get(key, [key.replace("_", " "), ""])
                rows.append([f"{name[0]} ({name[1]})" if name[1] else name[0], value])
    tables = (
        [Table("values", "Values reported by the job.", [Column("Quantity", kind="text"), Column("Value")], rows)]
        if rows
        else []
    )
    summary = [
        f'Result of kind "{kind}". This kind has no dedicated report layout, so the report lists the job\'s '
        "summary values; the full result is in data/result.json."
    ]
    return Report(KIND_TITLES.get(kind, kind), "", "", summary, tables, [])


__all__ = ["CI", "EXTRACTORS", "build_report", "fmt_num", "supported"]
