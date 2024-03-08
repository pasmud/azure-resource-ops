"""Opt-in scoped merge adapter. The runner boundary is injectable for offline tests."""

import os
import subprocess
from collections.abc import Callable

from .audit import plan_digest
from .core import InputError, fingerprint, merge_for, resource_subscription, scope, tags
from .jsonio import decode
from .plans import Change, Plan

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
_COMMAND_ERRORS = (OSError, subprocess.SubprocessError, UnicodeError)
_STATUSES = ("merged", "read_failed", "invalid_read", "stale", "merge_unconfirmed", "not_attempted")


def run_az(argv: list[str]) -> subprocess.CompletedProcess[str]:
    if os.name != "posix":
        raise OSError("the native subprocess adapter requires POSIX")
    return subprocess.run(
        argv, shell=False, stdin=subprocess.DEVNULL, capture_output=True,
        encoding="utf-8", timeout=60, check=False,
    )


def _live_tags(output: str, target: str) -> dict[str, str]:
    response = decode(output)
    ident = response.get("id") if isinstance(response, dict) else None
    expected = target + "/providers/Microsoft.Resources/tags/default"
    if not isinstance(ident, str) or ident.lower() != expected.lower():
        raise InputError("unexpected live tag resource ID")
    properties = response.get("properties")
    if not isinstance(properties, dict) or "tags" not in properties:
        raise InputError("missing live tag map")
    return {} if properties["tags"] is None else tags(properties["tags"])


def _invoke(runner: Runner, argv: list[str]) -> tuple[str | None, str | None]:
    """Return stdout or a fixed failure reason, never subprocess diagnostics."""
    try:
        response = runner(argv)
    except KeyboardInterrupt:
        return None, "interrupted"
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except _COMMAND_ERRORS:
        return None, "runner_error"
    if response.returncode != 0:
        return None, "nonzero_exit"
    return response.stdout, None


def _apply_change(change: Change, plan: Plan, runner: Runner) -> tuple[str, str | None]:
    target = ["--resource-id", change.id, "--subscription", resource_subscription(change.id)]
    output, reason = _invoke(runner, ["az", "tag", "list", *target, "--only-show-errors", "--output", "json"])
    if reason is not None:
        return "read_failed", reason
    if not isinstance(output, str):
        return "invalid_read", None
    try:
        live = _live_tags(output, change.id)
    except InputError:
        return "invalid_read", None
    if fingerprint(live) != change.before_sha256 or merge_for(plan.policy, live) != change.merge:
        return "stale", None
    assignments = [f"{key}={change.merge[key]}" for key in sorted(change.merge)]
    _, reason = _invoke(runner, [
        "az", "tag", "update", *target, "--operation", "Merge", "--only-show-errors",
        "--output", "none", "--tags", *assignments,
    ])
    return ("merged", None) if reason is None else ("merge_unconfirmed", reason)


def apply_plan(value: object, subscriptions: list[str], approved_sha256: str, *, runner: Runner = run_az) -> dict:
    """Validate all input before reading and stop at the first unconfirmed change."""
    plan = Plan.parse(value)
    if scope(subscriptions) != plan.policy.subscriptions:
        raise InputError("explicit subscription scope must exactly match plan scope")
    digest = plan_digest(plan)
    if approved_sha256 != digest:
        raise InputError("approved SHA-256 does not match the canonical plan")

    rows = []
    summary = dict.fromkeys(_STATUSES, 0)
    complete = True
    for index, change in enumerate(plan.changes, 1):
        status, reason = _apply_change(change, plan, runner) if complete else ("not_attempted", None)
        complete = status == "merged"
        summary[status] += 1
        row = {"change": index, "status": status}
        if reason is not None:
            row["reason"] = reason
        rows.append(row)
    return {
        "report_version": 2,
        "kind": "plan_apply",
        "status": "no_changes" if not rows else "applied" if complete else "incomplete",
        "plan_sha256": digest,
        "complete": complete,
        "summary": summary,
        "changes": rows,
    }
