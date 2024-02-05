"""Command-line entry point; planning only reads local files."""

import argparse
from pathlib import Path
import sys

from .core import InputError, Policy, build_plan
from .inventory import parse_inventory
from .jsonio import read_json, render
from .plans import Plan


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        super().error("invalid arguments; see --help")


def main(argv: list[str] | None = None) -> int:
    parser = Parser(prog="azure-resource-ops", description="Plan scoped Azure tag merges offline.",
                    allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="create a dry-run plan", allow_abbrev=False)
    plan.add_argument("--inventory", type=Path, required=True, help="saved inventory JSON")
    plan.add_argument("--policy", type=Path, required=True, help="local policy JSON")
    validate = commands.add_parser("validate", help="validate a saved plan offline", allow_abbrev=False)
    validate.add_argument("--plan", type=Path, required=True, help="saved version 1 plan JSON")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            policy = Policy.parse(read_json(args.policy, "policy"))
            resources = parse_inventory(read_json(args.inventory, "inventory"))
            result = build_plan(resources, policy)
        else:
            Plan.parse(read_json(args.plan, "plan"))
            result = {"valid": True}
        sys.stdout.write(render(result))
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
