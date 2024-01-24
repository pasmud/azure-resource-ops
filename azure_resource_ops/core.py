"""Policy and deterministic, additive planning."""

import hashlib
import json
import re
from dataclasses import dataclass


class InputError(ValueError):
    """Invalid operator input; messages must not contain submitted values."""


_SUBSCRIPTION = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I | re.ASCII)
_MANAGED_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SEGMENT = re.compile(r"[A-Za-z0-9_().:@+~-]+")
_GROUP = re.compile(r"[A-Za-z0-9_().-]{1,90}(?<!\.)")
_TYPE = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?:/[A-Za-z0-9_-]+)+")


def subscription_id(value: object) -> str:
    if not isinstance(value, str) or not _SUBSCRIPTION.fullmatch(value):
        raise InputError("expected a subscription UUID")
    return value.lower()


def scope(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise InputError("subscriptions must be a nonempty list")
    ids = tuple(sorted(subscription_id(item) for item in value))
    if len(set(ids)) != len(ids):
        raise InputError("duplicate subscription in scope")
    return ids


@dataclass(frozen=True)
class ResourceScope:
    subscription: str
    group: str | None
    type: str


def resource_scope(value: object) -> ResourceScope:
    if not isinstance(value, str) or not value.startswith("/"):
        raise InputError("expected a subscription-qualified resource ID")
    parts = value[1:].split("/")
    if any(not _SEGMENT.fullmatch(part) or part in {".", ".."} for part in parts):
        raise InputError("invalid resource ID segment")
    parts = [part.lower() for part in parts]
    if len(parts) < 4 or parts[0] != "subscriptions":
        raise InputError("expected a subscription-qualified resource ID")
    sub = subscription_id(parts[1])
    i = 2
    group = None
    resource_type = "microsoft.resources/resourcegroups"
    if parts[i] == "resourcegroups":
        group = parts[i + 1]
        i += 2
    # Each provider block has a namespace and one or more type/name pairs.
    while i < len(parts):
        if parts[i] != "providers" or i + 3 >= len(parts):
            raise InputError("invalid resource ID provider path")
        type_parts = parts[i + 1:i + 3]
        i += 4
        while i < len(parts) and parts[i] != "providers":
            if i + 1 >= len(parts):
                raise InputError("invalid resource ID type/name pair")
            type_parts.append(parts[i])
            i += 2
        resource_type = "/".join(type_parts)
    return ResourceScope(sub, group, resource_type)


def resource_subscription(value: object) -> str:
    return resource_scope(value).subscription


def _selector(value: object, pattern: re.Pattern[str], field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not pattern.fullmatch(item) for item in value
    ):
        raise InputError(f"{field} must be a nonempty list of exact names")
    names = tuple(sorted(item.lower() for item in value))
    if len(set(names)) != len(names):
        raise InputError(f"duplicate name in {field}")
    return names


def _text(value: object, limit: int) -> bool:
    return isinstance(value, str) and len(value) <= limit and all(
        ord(char) >= 32 and not 127 <= ord(char) <= 159 and not 0xD800 <= ord(char) <= 0xDFFF
        for char in value
    )


def tags(value: object, *, managed: bool = False) -> dict[str, str]:
    if not isinstance(value, dict):
        raise InputError("tags must be an object")
    keys: set[str] = set()
    for key, text in value.items():
        if not key or not _text(key, 512) or (managed and not _MANAGED_KEY.fullmatch(key)):
            raise InputError("invalid tag name")
        normalized = key.casefold()
        if normalized in keys:
            raise InputError("duplicate case-insensitive tag name")
        if not _text(text, 256):
            raise InputError("tag values must be strings of at most 256 characters without controls")
        keys.add(normalized)
    return dict(value)


@dataclass(frozen=True)
class Policy:
    subscriptions: tuple[str, ...]
    ensure: dict[str, str]
    protected: frozenset[str]
    resource_groups: tuple[str, ...] = ()
    resource_types: tuple[str, ...] = ()

    def includes(self, target: ResourceScope) -> bool:
        return (
            target.subscription in self.subscriptions
            and (not self.resource_groups or target.group in self.resource_groups)
            and (not self.resource_types or target.type in self.resource_types)
        )

    def as_dict(self) -> dict:
        result = {
            "subscriptions": list(self.subscriptions),
            "ensure": dict(self.ensure),
            "protected": sorted(self.protected),
        }
        if self.resource_groups:
            result["resource_groups"] = list(self.resource_groups)
        if self.resource_types:
            result["resource_types"] = list(self.resource_types)
        return result

    @classmethod
    def parse(cls, value: object) -> "Policy":
        required = {"subscriptions", "ensure", "protected"}
        if not isinstance(value, dict) or not required <= value.keys() <= required | {
            "resource_groups", "resource_types",
        }:
            raise InputError("policy requires subscriptions, ensure, and protected; only scope filters are optional")
        protected = value["protected"]
        if not isinstance(protected, list) or any(not key or not _text(key, 512) for key in protected):
            raise InputError("protected must be a list of valid tag names")
        normalized = frozenset(key.casefold() for key in protected)
        if any(not _text(key, 512) for key in normalized):
            raise InputError("normalized protected tag name exceeds the length limit")
        if len(normalized) != len(protected):
            raise InputError("duplicate protected tag name")
        ensure = tags(value["ensure"], managed=True)
        if normalized.intersection(key.casefold() for key in ensure):
            raise InputError("policy cannot manage a protected tag")
        return cls(
            scope(value["subscriptions"]), ensure, normalized,
            _selector(value["resource_groups"], _GROUP, "resource_groups") if "resource_groups" in value else (),
            _selector(value["resource_types"], _TYPE, "resource_types") if "resource_types" in value else (),
        )


@dataclass(frozen=True)
class Resource:
    id: str
    tags: dict[str, str]


def merge_for(policy: Policy, existing: dict[str, str]) -> dict[str, str]:
    current = {key.casefold(): text for key, text in existing.items()}
    return {key: text for key, text in policy.ensure.items() if current.get(key.casefold()) != text}


def fingerprint(existing: dict[str, str]) -> str:
    normalized = {key.casefold(): text for key, text in existing.items()}
    encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def build_plan(resources: list[Resource], policy: Policy) -> dict:
    changes = []
    seen: set[str] = set()
    for resource in sorted(resources, key=lambda item: item.id.lower()):
        target = resource_scope(resource.id)
        ident = resource.id.lower()
        if ident in seen:
            raise InputError("duplicate resource ID")
        seen.add(ident)
        if not policy.includes(target):
            continue
        current = tags(resource.tags)
        merge = merge_for(policy, current)
        if merge:
            changes.append({"id": resource.id, "before_sha256": fingerprint(current), "merge": merge})
    return {"version": 1, "policy": policy.as_dict(), "changes": changes}
