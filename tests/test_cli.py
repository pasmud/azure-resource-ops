import json
import subprocess
import sys
from pathlib import Path

SUB = "aaaaaaaa-1111-4111-8111-111111111111"
BASE = f"/subscriptions/{SUB}/resourceGroups/"


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "azure_resource_ops", *map(str, args)],
        capture_output=True, text=True, check=False,
    )


def test_module_dry_run_is_byte_stable_and_writes_only_plan(tmp_path):
    policy = tmp_path / "policy.json"
    inventory = tmp_path / "inventory.json"
    policy.write_text(json.dumps({
        "protected": ["owner"], "ensure": {"env": "demo", "second": ""}, "subscriptions": [SUB],
    }), encoding="utf-8")
    rows = [{"id": BASE + "z", "tags": {"Owner": "fake-owner", "second": ""}},
            {"id": BASE + "a", "tags": None}]
    args = ("plan", "--inventory", inventory, "--policy", policy)
    inventory.write_text(json.dumps(rows), encoding="utf-8")
    first = run_cli(*args)
    inventory.write_text(json.dumps({"data": list(reversed(rows)), "count": 2}), encoding="utf-8")
    second = run_cli(*args)
    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == ""
    assert first.stdout == second.stdout
    assert "fake-owner" not in first.stdout
    assert [entry["id"] for entry in json.loads(first.stdout)["changes"]] == [BASE + "a", BASE + "z"]


def test_invalid_cli_input_has_no_partial_output_or_path(tmp_path):
    result = run_cli("plan", "--inventory", tmp_path / "fake-inventory",
                     "--policy", tmp_path / "fake-private-file")
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "error: cannot read policy as UTF-8\n"


def test_validation_rejects_unknown_fields_without_echoing_them(tmp_path):
    plan = tmp_path / "plan.json"
    value = {"version": 1, "policy": {"subscriptions": [SUB], "ensure": {}, "protected": []}, "changes": []}
    plan.write_text(json.dumps(value), encoding="utf-8")
    valid = run_cli("validate", "--plan", plan)
    assert valid.returncode == 0
    assert json.loads(valid.stdout) == {"valid": True}
    plan.write_text(json.dumps(value | {"fake-private-field": "fake-private-value"}), encoding="utf-8")
    invalid = run_cli("validate", "--plan", plan)
    assert invalid.returncode == 2
    assert invalid.stdout == ""
    assert "fake-private" not in invalid.stderr


def test_audit_counts_changes_and_redacts_plan_content(tmp_path):
    plan = tmp_path / "plan.json"
    digest = "1234" * 16
    first = {"id": BASE + "fake-private-a", "before_sha256": digest, "merge": {"fake-tag": "fake-value"}}
    second = first | {"id": BASE + "fake-private-b", "merge": {"extra": "another", "fake-tag": "fake-value"}}
    policy = {
        "subscriptions": [SUB, "22222222-2222-4222-8222-222222222222"],
        "ensure": second["merge"], "protected": ["fake-protected"],
    }
    value = {"version": 1, "policy": policy, "changes": [second, first]}
    plan.write_text(json.dumps(value), encoding="utf-8")
    report = run_cli("audit", "--plan", plan)
    assert report.returncode == 0, report.stderr
    assert not any(text in report.stdout for text in (SUB, digest, "fake-", "another"))
    result = json.loads(report.stdout)
    assert result["summary"] == {"scoped_subscription_count": 2, "targeted_subscription_count": 1,
                                 "resource_count": 2, "assignment_count": 3}
    assert result["changes"] == [{"change": 1, "assignment_count": 1}, {"change": 2, "assignment_count": 2}]
    plan.write_text(json.dumps(value | {"changes": [first, second]}, indent=4), encoding="utf-8")
    assert run_cli("audit", "--plan", plan).stdout == report.stdout
    plan.write_text(json.dumps(value | {"changes": [first]}), encoding="utf-8")
    assert json.loads(run_cli("audit", "--plan", plan).stdout)["plan_sha256"] != result["plan_sha256"]


def test_synthetic_walkthrough_and_detection_of_omitted_change(tmp_path):
    examples = Path(__file__).resolve().parents[1] / "examples"
    inventory = examples / "inventory.graph.json"
    plan = tmp_path / "plan.json"
    dry_run = run_cli("plan", "--inventory", inventory, "--policy", examples / "policy.json")
    assert dry_run.returncode == 0, dry_run.stderr
    plan.write_text(dry_run.stdout, encoding="utf-8")
    verify = ("validate", "--plan", plan, "--inventory", inventory)
    validated = run_cli(*verify)
    assert validated.returncode == 0, validated.stderr
    assert json.loads(validated.stdout) == {"valid": True, "inventory_match": True}
    audited = run_cli("audit", "--plan", plan)
    assert audited.stdout == (examples / "audit.expected.json").read_text(encoding="utf-8")

    edited = json.loads(dry_run.stdout)
    edited["changes"].pop()
    plan.write_text(json.dumps(edited), encoding="utf-8")
    assert run_cli("validate", "--plan", plan).returncode == 0
    mismatch = run_cli(*verify)
    assert mismatch.returncode == 2
    assert mismatch.stdout == ""
    assert "does not match the supplied inventory" in mismatch.stderr
