"""Offline commands and explicitly approved application of a saved plan."""

import argparse
import sys
from pathlib import Path

from .audit import audit_plan
from .azure_cli import Runner, apply_plan, run_az
from .core import InputError, Policy, build_plan
from .inventory import parse_inventory
from .jsonio import read_json, render
from .plans import Plan


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        super().error("invalid arguments; see --help")


def main(argv: list[str] | None = None, *, azure_runner: Runner = run_az) -> int:
    parser = Parser(prog="azure-resource-ops", description="Plan scoped Azure tag merges offline.",
                    allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="create a dry-run plan", allow_abbrev=False)
    plan.add_argument("--inventory", type=Path, required=True, help="saved inventory JSON")
    plan.add_argument("--policy", type=Path, required=True, help="local policy JSON")
    validate = commands.add_parser("validate", help="validate a saved plan offline", allow_abbrev=False)
    validate.add_argument("--plan", type=Path, required=True, help="saved version 1 plan JSON")
    validate.add_argument("--inventory", type=Path, help="also verify against the original saved inventory")
    audit = commands.add_parser("audit", help="summarize a saved plan without identifiers or tags",
                                allow_abbrev=False)
    audit.add_argument("--plan", type=Path, required=True, help="saved version 1 plan JSON")
    apply = commands.add_parser("apply", help="execute a reviewed plan with Azure CLI", allow_abbrev=False)
    apply.add_argument("--plan", type=Path, required=True, help="reviewed version 1 plan JSON")
    apply.add_argument("--subscription", action="append", required=True, metavar="UUID",
                       help="explicitly approved subscription UUID; repeat for each subscription")
    apply.add_argument("--approve-sha256", required=True, metavar="DIGEST",
                       help="canonical digest from the audit of the reviewed plan")
    args = parser.parse_args(argv)
    status = 0
    try:
        if args.command == "plan":
            policy = Policy.parse(read_json(args.policy, "policy"))
            resources = parse_inventory(read_json(args.inventory, "inventory"))
            result = build_plan(resources, policy)
        elif args.command == "audit":
            result = audit_plan(Plan.parse(read_json(args.plan, "plan")))
        elif args.command == "apply":
            result = apply_plan(read_json(args.plan, "plan"), args.subscription,
                                args.approve_sha256, runner=azure_runner)
            status = 0 if result["complete"] else 3
        else:
            parsed = Plan.parse(read_json(args.plan, "plan"))
            result = {"valid": True}
            if args.inventory is not None:
                parsed.verify_inventory(parse_inventory(read_json(args.inventory, "inventory")))
                result["inventory_match"] = True
        sys.stdout.write(render(result))
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return status
