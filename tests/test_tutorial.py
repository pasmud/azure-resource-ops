import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from azure_resource_ops.audit import plan_digest
from azure_resource_ops.azure_cli import apply_plan
from azure_resource_ops.core import InputError, Policy, build_plan
from azure_resource_ops.inventory import parse_inventory
from azure_resource_ops.plans import Plan

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "two-subscriptions"


@pytest.mark.skipif(os.name != "posix", reason="tutorial uses a POSIX shell")
def test_documented_offline_commands(tmp_path):
    instructions = (DEMO / "README.md").read_text(encoding="utf-8")
    commands = instructions.split("```sh\n", 1)[1].split("```", 1)[0]
    run = subprocess.run(
        ["sh", "-c", commands], cwd=ROOT, text=True, capture_output=True,
        env=os.environ | {"PYTHON": sys.executable, "TMPDIR": str(tmp_path)}, timeout=15, check=False,
    )
    assert run.returncode == 0, run.stderr
    assert run.stderr == "error: plan does not match the supplied inventory and embedded policy\n"
    remaining = run.stdout.lstrip()
    outputs = []
    decoder = json.JSONDecoder()
    while remaining:
        obj, end = decoder.raw_decode(remaining)
        outputs.append(obj)
        remaining = remaining[end:].lstrip()
    validated, original, revalidated, replacement = outputs
    assert validated == revalidated == {"valid": True, "inventory_match": True}
    assert original["summary"] == {"scoped_subscription_count": 2, "targeted_subscription_count": 2,
                                   "resource_count": 2, "assignment_count": 3}
    assert replacement["summary"] == {"scoped_subscription_count": 2, "targeted_subscription_count": 1,
                                      "resource_count": 1, "assignment_count": 1}
    assert original["plan_sha256"] != replacement["plan_sha256"]


def test_tutorial_partial_apply_and_recovery_with_in_memory_runner():
    def load(name):
        return json.loads((DEMO / f"{name}.json").read_text(encoding="utf-8"))

    policy = Policy.parse(load("policy"))
    before = parse_inventory(load("before"))
    refreshed = parse_inventory(load("refreshed"))
    original = build_plan(before, policy)
    replacement = build_plan(refreshed, policy)
    original_digest = plan_digest(Plan.parse(original))
    replacement_digest = plan_digest(Plan.parse(replacement))
    east, west = (change["id"] for change in original["changes"])
    expected_refresh = {row.id: row.tags for row in refreshed}
    live = {row.id: row.tags for row in before} | {west: expected_refresh[west]}
    written = []

    def fake(argv):
        target = argv[argv.index("--resource-id") + 1]
        subscription = argv[argv.index("--subscription") + 1]
        assert (target, subscription) in zip((east, west), policy.subscriptions)
        if argv[2] == "list":
            output = {"id": target + "/providers/Microsoft.Resources/tags/default",
                      "properties": {"tags": live[target]}}
            return subprocess.CompletedProcess(argv, 0, json.dumps(output), "")
        assert argv[2] == "update" and argv[argv.index("--operation") + 1] == "Merge"
        written.append(target)
        live[target] = live[target] | dict(arg.split("=", 1) for arg in argv[argv.index("--tags") + 1:])
        return subprocess.CompletedProcess(argv, 0, "", "")

    subscriptions = list(policy.subscriptions)
    first = apply_plan(original, subscriptions, original_digest, runner=fake)
    assert [row["status"] for row in first["changes"]] == ["merged", "stale"]
    assert written == [east] and live == expected_refresh

    def unexpected(_):
        pytest.fail("approval failures must not run any commands")

    with pytest.raises(InputError, match="subscription scope"):
        apply_plan(replacement, subscriptions[1:], replacement_digest, runner=unexpected)
    with pytest.raises(InputError, match="approved SHA-256"):
        apply_plan(replacement, subscriptions, original_digest, runner=unexpected)
    second = apply_plan(replacement, subscriptions, replacement_digest, runner=fake)
    assert second["status"] == "applied" and written == [east, west]
    assert live[west] == {"Environment": "production", "CostCenter": "cc-4100", "Owner": "Payments Platform"}
