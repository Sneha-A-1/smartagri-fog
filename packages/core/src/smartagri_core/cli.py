"""Command-line interface: ``smartagri``.

The CLI calls the same core code as the web interface. In later phases it runs experiment files
(``smartagri run experiments/x.yaml``) for overnight batch runs.
"""

from __future__ import annotations

import argparse
import json
import sys

from smartagri_core import __version__
from smartagri_core.registry import PluginError, get_registry


def _cmd_plugins_list(args: argparse.Namespace) -> int:
    specs = get_registry().all(kind=args.kind)
    for s in specs:
        print(f"{s.id:<40} {s.status:<18} {s.name}")
    print(f"\n{len(specs)} plugin(s)")
    return 0


def _cmd_plugins_show(args: argparse.Namespace) -> int:
    try:
        spec = get_registry().get(args.plugin_id)
    except PluginError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(json.dumps(spec.to_dict(include_schema=True), indent=2, ensure_ascii=False))
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    registry = get_registry()
    plugin = registry.create("data_generator:soil_moisture_demo", {"days": args.days, "demo_delay_ms": 0})

    def progress(fraction: float, message: str = "") -> None:
        print(f"\r[{fraction:6.1%}] {message}", end="", flush=True)

    result = plugin.run(progress)
    print()
    print(json.dumps({"data_origin": result["data_origin"], "summary": result["summary"]}, indent=2))
    return 0


EXPERIMENT_TEMPLATE = """\
# SmartAgri-Fog experiment. Run with:  uv run smartagri experiment run this-file.yaml --out results/my-experiment
name: Placement baselines on a rural farm network
objective: Do edge-ward and MCT placement meet more urgent deadlines than cloud-only on a slow cloud link?
description: Baseline comparison for Paper 3.
replications: 30          # 30 is the usual minimum for papers
base_seed: 1
scenario:
  farms: 4
  gateways_per_farm: 2
  edge_per_farm: 1
  fog_nodes: 2
  cloud_nodes: 1
  duration_s: 3600
  intensity: 20
  wan_bandwidth_mbps: 5
  wan_latency_ms: 250
algorithms:
  - {placement: cloud_only, discipline: edf}
  - {placement: edge_ward, discipline: edf}
  - {placement: mct, discipline: edf}
  - {placement: min_min, discipline: edf}
"""


def _cmd_experiment_template(args: argparse.Namespace) -> int:
    print(EXPERIMENT_TEMPLATE, end="")
    return 0


def _cmd_experiment_run(args: argparse.Namespace) -> int:
    from pathlib import Path

    import yaml

    from smartagri_core.experiment import ExperimentSpec, latex_tables, run_experiment, runs_to_csv

    spec = ExperimentSpec.model_validate(yaml.safe_load(Path(args.spec).read_text(encoding="utf-8")))
    print(f"{spec.name}: {len(spec.algorithms)} algorithms x {spec.replications} replications = {spec.total_runs} runs")

    def progress(fraction: float, message: str = "") -> None:
        print(f"\r[{fraction:6.1%}] {message:<70}", end="", flush=True)

    result = run_experiment(spec, progress)
    print()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    (out / "runs.csv").write_text(runs_to_csv(result), encoding="utf-8")
    (out / "tables.tex").write_text(latex_tables(result), encoding="utf-8")
    (out / "spec.yaml").write_text(yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    for metric in spec.metrics:
        print(f"- {metric}: {result['analysis'][metric]['verdict']}")
    print(f"\nWrote result.json, runs.csv, tables.tex and spec.yaml to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smartagri", description="SmartAgri-Fog command line")
    parser.add_argument("--version", action="version", version=f"smartagri-core {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    plugins = sub.add_parser("plugins", help="Browse the plugin catalogue")
    psub = plugins.add_subparsers(dest="action", required=True)
    p_list = psub.add_parser("list", help="List plugins")
    p_list.add_argument("--kind", help="Filter by kind, e.g. scheduler")
    p_list.set_defaults(func=_cmd_plugins_list)
    p_show = psub.add_parser("show", help="Show one plugin with its parameter schema")
    p_show.add_argument("plugin_id", help="e.g. data_generator:soil_moisture_demo")
    p_show.set_defaults(func=_cmd_plugins_show)

    exp = sub.add_parser("experiment", help="Run reproducible experiments from YAML files")
    esub = exp.add_subparsers(dest="action", required=True)
    e_tpl = esub.add_parser("template", help="Print an example experiment file")
    e_tpl.set_defaults(func=_cmd_experiment_template)
    e_run = esub.add_parser("run", help="Run an experiment file and write results, CSV and LaTeX tables")
    e_run.add_argument("spec", help="Path to the experiment YAML file")
    e_run.add_argument("--out", required=True, help="Output folder")
    e_run.set_defaults(func=_cmd_experiment_run)

    demo = sub.add_parser("demo", help="Run the synthetic soil-moisture demo")
    demo.add_argument("--days", type=int, default=30)
    demo.set_defaults(func=_cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
