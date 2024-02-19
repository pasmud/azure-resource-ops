import json
import os
import subprocess

import pytest

from azure_resource_ops.audit import plan_digest
from azure_resource_ops.azure_cli import apply_plan, run_az
from azure_resource_ops.core import InputError, Policy, Resource, build_plan
from azure_resource_ops.plans import Plan

SUB = "aaaaaaaa-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
RID = f"/subscriptions/{SUB}/resourceGroups/fake-private-rg"
CURRENT = {"owner": "fake-private-owner", "Environment": "legacy"}
DESIRED = {"Environment": "fake value = with spaces", "Blank": ""}


def plan_for(*targets):
    policy = Policy.parse({"subscriptions": [SUB], "ensure": DESIRED, "protected": ["Owner"]})
    value = build_plan([Resource(target, CURRENT) for target in targets], policy)
    return value, plan_digest(Plan.parse(value))


def tag_response(target, current=CURRENT):
    return json.dumps({
        "id": target + "/providers/Microsoft.Resources/tags/default", "properties": {"tags": current},
    })


def test_apply_uses_only_scoped_merge_commands_and_redacts_reports():
    value, approved = plan_for(RID)
    calls = []

    def fake(argv):
        calls.append(argv)
        output = tag_response(RID.upper(), {"OWNER": CURRENT["owner"], "environment": "legacy"})
        return subprocess.CompletedProcess(argv, 0, output, "fake-private-cli-message")

    report = apply_plan(value, [SUB.upper()], approved, runner=fake)
    target = ["--resource-id", RID, "--subscription", SUB]
    assert calls == [
        ["az", "tag", "list", *target, "--only-show-errors", "--output", "json"],
        ["az", "tag", "update", *target, "--operation", "Merge", "--only-show-errors", "--output", "none",
         "--tags", "Blank=", "Environment=fake value = with spaces"],
    ]
    assert report["complete"] and report["summary"]["merged"] == 1
    assert report["plan_sha256"] == approved
    serialized = json.dumps(report)
    assert all(text not in serialized for text in (SUB, "fake-private", "Environment", "fake value", "legacy"))


@pytest.mark.parametrize("subscriptions", [[], [OTHER], [SUB, OTHER], [SUB, SUB]])
def test_explicit_scope_mismatch_runs_nothing(subscriptions):
    value, approved = plan_for(RID)
    with pytest.raises(InputError):
        apply_plan(value, subscriptions, approved, runner=lambda _: pytest.fail("unexpected command"))


def test_unapproved_or_invalid_plan_runs_nothing():
    value, approved = plan_for(RID)

    def unexpected(_):
        pytest.fail("unexpected command")

    with pytest.raises(InputError, match="does not match"):
        apply_plan(value, [SUB], "0" * 64, runner=unexpected)
    value["changes"].append(value["changes"][0] | {"id": RID.replace(SUB, OTHER)})
    with pytest.raises(InputError, match="outside plan"):
        apply_plan(value, [SUB], approved, runner=unexpected)


def test_empty_apply_issues_no_calls():
    value, approved = plan_for()
    report = apply_plan(value, [SUB], approved, runner=lambda _: pytest.fail("unexpected command"))
    assert report["complete"] and report["changes"] == []
    assert report["status"] == "no_changes"


@pytest.mark.parametrize(("output", "returncode", "expected"), [
    (tag_response(RID, CURRENT | {"unrelated": "drift"}), 0, "stale"),
    (tag_response(RID + "-wrong"), 0, "invalid_read"),
    (tag_response(RID, {"Owner": "a", "OWNER": "b"}), 0, "invalid_read"),
    ("fake-private-not-json", 0, "invalid_read"),
    (tag_response(RID), 1, "read_failed"),
])
def test_apply_stops_on_first_failed_read_or_drift(output, returncode, expected):
    value, approved = plan_for(RID, RID + "-next")
    calls = []

    def fake(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode, output, "fake-private-error")

    report = apply_plan(value, [SUB], approved, runner=fake)
    assert not report["complete"]
    assert [row["status"] for row in report["changes"]] == [expected, "not_attempted"]
    assert len(calls) == 1 and calls[0][2] == "list"
    assert "fake-private" not in json.dumps(report)


def test_matching_snapshot_is_insufficient_if_saved_merge_is_incomplete():
    value, _ = plan_for(RID)
    value["changes"][0]["merge"].pop("Blank")
    approved = plan_digest(Plan.parse(value))

    def fake(argv):
        assert argv[2] == "list"
        return subprocess.CompletedProcess(argv, 0, tag_response(RID), "")

    assert apply_plan(value, [SUB], approved, runner=fake)["summary"]["stale"] == 1


def test_later_timeout_is_unconfirmed_and_earlier_merge_is_retained():
    value, approved = plan_for(RID, RID + "-next", RID + "-third")
    calls = []

    def fake(argv):
        calls.append(argv)
        if argv[2] == "update" and argv[4] == RID + "-next":
            raise subprocess.TimeoutExpired(argv, 60, stderr="fake-private-timeout")
        return subprocess.CompletedProcess(argv, 0, tag_response(argv[4]), "")

    report = apply_plan(value, [SUB], approved, runner=fake)
    assert [row["status"] for row in report["changes"]] == ["merged", "merge_unconfirmed", "not_attempted"]
    assert len(calls) == 4 and "fake-private" not in json.dumps(report)


@pytest.mark.skipif(os.name != "posix", reason="native apply runner requires POSIX")
def test_native_runner_invokes_subprocess_without_shell_or_stdin(monkeypatch):
    def fake(argv, **kwargs):
        assert argv == ["az", "tag", "list"]
        assert kwargs == {"shell": False, "stdin": subprocess.DEVNULL, "capture_output": True,
                          "encoding": "utf-8", "timeout": 60, "check": False}
        return subprocess.CompletedProcess(argv, 0, "{}", "")

    monkeypatch.setattr(subprocess, "run", fake)
    assert run_az(["az", "tag", "list"]).returncode == 0
