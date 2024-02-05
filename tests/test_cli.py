import json
import subprocess
import sys

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
