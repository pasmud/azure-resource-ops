"""Redacted audit metadata for a validated plan."""

import hashlib

from .core import resource_subscription
from .jsonio import render
from .plans import Plan


def plan_digest(plan: Plan) -> str:
    return hashlib.sha256(render(plan.as_dict()).encode("ascii")).hexdigest()


def audit_plan(plan: Plan) -> dict:
    rows = [
        {"change": index, "assignment_count": len(change.merge)}
        for index, change in enumerate(plan.changes, 1)
    ]
    return {
        "report_version": 2,
        "kind": "plan_audit",
        "status": "changes_planned" if rows else "no_changes",
        "plan_sha256": plan_digest(plan),
        "summary": {
            "scoped_subscription_count": len(plan.policy.subscriptions),
            "targeted_subscription_count": len({resource_subscription(c.id) for c in plan.changes}),
            "resource_count": len(rows),
            "assignment_count": sum(row["assignment_count"] for row in rows),
        },
        "changes": rows,
    }
