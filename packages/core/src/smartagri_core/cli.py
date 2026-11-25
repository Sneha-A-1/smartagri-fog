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

    demo = sub.add_parser("demo", help="Run the synthetic soil-moisture demo")
    demo.add_argument("--days", type=int, default=30)
    demo.set_defaults(func=_cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
