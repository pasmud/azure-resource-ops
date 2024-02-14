"""Strict validation for the serialized version 1 merge plan."""

from dataclasses import dataclass
import re

from .core import InputError, Policy, resource_subscription, tags

_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Change:
    id: str
    before_sha256: str
    merge: dict[str, str]


@dataclass(frozen=True)
class Plan:
    policy: Policy
    changes: tuple[Change, ...]

    def as_dict(self) -> dict:
        return {
            "version": 1,
            "policy": {
                "subscriptions": list(self.policy.subscriptions),
                "ensure": dict(self.policy.ensure),
                "protected": sorted(self.policy.protected),
            },
            "changes": [
                {"id": change.id, "before_sha256": change.before_sha256, "merge": dict(change.merge)}
                for change in self.changes
            ],
        }

    @classmethod
    def parse(cls, value: object) -> "Plan":
        if not isinstance(value, dict) or value.keys() != {"version", "policy", "changes"}:
            raise InputError("plan requires exactly version, policy, and changes")
        if type(value["version"]) is not int or value["version"] != 1:
            raise InputError("unsupported plan version")
        policy = Policy.parse(value["policy"])
        if not isinstance(value["changes"], list):
            raise InputError("plan changes must be an array")
        changes = []
        seen = set()
        for index, row in enumerate(value["changes"], 1):
            try:
                change = _parse_change(row, policy)
                ident = change.id.lower()
                if ident in seen:
                    raise InputError("duplicate resource ID")
                seen.add(ident)
                changes.append(change)
            except InputError as exc:
                raise InputError(f"plan change {index}: {exc}") from None
        return cls(policy, tuple(sorted(changes, key=lambda change: change.id.lower())))


def _parse_change(row: object, policy: Policy) -> Change:
    if not isinstance(row, dict) or row.keys() != {"id", "before_sha256", "merge"}:
        raise InputError("expected exactly id, before_sha256, and merge")
    if resource_subscription(row["id"]) not in policy.subscriptions:
        raise InputError("resource is outside plan subscription scope")
    digest = row["before_sha256"]
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise InputError("invalid tag snapshot digest")
    merge = tags(row["merge"], managed=True)
    if not merge or any(policy.ensure.get(key) != text for key, text in merge.items()):
        raise InputError("merge must be a nonempty subset of exact policy assignments")
    return Change(row["id"], digest, merge)
