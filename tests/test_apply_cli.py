import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from azure_resource_ops.cli import main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SUB = "11111111-1111-4111-8111-111111111111"


def unexpected(_):
    pytest.fail("unexpected Azure runner invocation")


@pytest.fixture
def reviewed_plan(tmp_path, capsys):
    assert main([
        "plan", "--inventory", str(EXAMPLES / "inventory.graph.json"),
        "--policy", str(EXAMPLES / "policy.json"),
    ], azure_runner=unexpected) == 0
    plan_text = capsys.readouterr().out
    path = tmp_path / "reviewed.json"
    path.write_text(plan_text, encoding="utf-8")
    raw_inventory = json.loads((EXAMPLES / "inventory.graph.json").read_text(encoding="utf-8"))
    live = {row["id"]: row["tags"] for row in raw_inventory["data"]}
    assert main(["audit", "--plan", str(path)], azure_runner=unexpected) == 0
    report = json.loads(capsys.readouterr().out)
    return path, report["plan_sha256"], live


@pytest.mark.parametrize(("drift", "exit_code", "statuses"), [
    (False, 0, ["merged", "merged"]), (True, 3, ["merged", "stale"]),
])
def test_reviewed_plan_end_to_end_with_injected_runner(reviewed_plan, capsys, drift, exit_code, statuses):
    path, digest, live = reviewed_plan
    if drift:
        untagged = next(ident for ident in live if ident.endswith("/fake-untagged"))
        live[untagged] = {"Owner": "fake concurrent change"}
    writes = []

    def fake(argv):
        resource_id = argv[argv.index("--resource-id") + 1]
        assert argv[argv.index("--subscription") + 1] == SUB
        if argv[2] == "list":
            result = {"id": resource_id + "/providers/Microsoft.Resources/tags/default",
                      "properties": {"tags": live[resource_id]}}
            return CompletedProcess(argv, 0, json.dumps(result), "")
        assert argv[2] == "update" and argv[argv.index("--operation") + 1] == "Merge"
        writes.append(resource_id)
        merged = dict(item.split("=", 1) for item in argv[argv.index("--tags") + 1:])
        live[resource_id] = (live[resource_id] or {}) | merged
        return CompletedProcess(argv, 0, "", "fake stderr, not a report")

    assert main(["apply", "--plan", str(path), "--subscription", SUB, "--approve-sha256", digest],
                azure_runner=fake) == exit_code
    captured = capsys.readouterr()
    record = json.loads(captured.out)
    assert captured.err == "" and "fake" not in captured.out and SUB not in captured.out
    assert record["plan_sha256"] == digest and record["complete"] is (not drift)
    assert (record["kind"], record["report_version"]) == ("plan_apply", 2)
    assert record["status"] == ("incomplete" if drift else "applied")
    assert [change["status"] for change in record["changes"]] == statuses
    assert len(writes) == (1 if drift else 2)
    assert live[writes[0]]["Owner"] == "fake team"


@pytest.mark.parametrize("flags", [[], ["--subscription", SUB], ["--approve-sha256", "0" * 64]])
def test_apply_requires_both_explicit_approvals(reviewed_plan, capsys, flags):
    path, _, _ = reviewed_plan
    with pytest.raises(SystemExit) as exc:
        main(["apply", "--plan", str(path), *flags], azure_runner=unexpected)
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert not output.out and SUB not in output.err


@pytest.mark.parametrize(("phase", "status"), [("list", "read_failed"), ("update", "merge_unconfirmed")])
def test_interrupt_during_command_stops_apply_with_a_redacted_report(reviewed_plan, capsys, phase, status):
    path, digest, live = reviewed_plan
    calls = []

    def fake(argv):
        calls.append(argv[2])
        if argv[2] == phase:
            raise KeyboardInterrupt("fake-private-interrupt")
        result = {"id": argv[4] + "/providers/Microsoft.Resources/tags/default",
                  "properties": {"tags": live[argv[4]]}}
        return CompletedProcess(argv, 0, json.dumps(result), "")

    assert main(["apply", "--plan", str(path), "--subscription", SUB, "--approve-sha256", digest],
                azure_runner=fake) == 3
    captured = capsys.readouterr()
    assert not captured.err and "fake-private" not in captured.out
    assert json.loads(captured.out)["changes"] == [
        {"change": 1, "status": status, "reason": "interrupted"},
        {"change": 2, "status": "not_attempted"},
    ]
    assert calls == (["list"] if phase == "list" else ["list", "update"])
