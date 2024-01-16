"""Normalize saved Azure CLI lists and complete Resource Graph responses."""

from .core import InputError, Resource, resource_subscription, subscription_id, tags


def _rows(value: object) -> list:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict) or not isinstance(value.get("data"), list):
        raise InputError("inventory must be an array or a Resource Graph data envelope")
    rows = value["data"]
    for key in ("skipToken", "skip_token", "$skipToken"):
        if key in value and value[key] not in (None, ""):
            raise InputError("inventory has a continuation token; export and combine all pages")
    for key in ("resultTruncated", "result_truncated"):
        if key in value and value[key] is not False and value[key] != "false":
            raise InputError("inventory is truncated or has an invalid truncation flag")
    for key in ("count", "totalRecords", "total_records"):
        if key in value and (type(value[key]) is not int or value[key] != len(rows)):
            raise InputError("inventory row count does not match response metadata")
    return rows


def parse_inventory(value: object) -> list[Resource]:
    resources = []
    seen = set()
    for index, row in enumerate(_rows(value), 1):
        try:
            if not isinstance(row, dict) or not {"id", "tags"} <= row.keys():
                raise InputError("expected an object with id and tags fields")
            sub = resource_subscription(row["id"])
            for key in ("subscriptionId", "subscription_id"):
                if key in row and subscription_id(row[key]) != sub:
                    raise InputError("subscription metadata disagrees with resource ID")
            ident = row["id"].lower()
            if ident in seen:
                raise InputError("duplicate resource ID")
            seen.add(ident)
            current = {} if row["tags"] is None else tags(row["tags"])
            resources.append(Resource(row["id"], current))
        except InputError as exc:
            raise InputError(f"inventory row {index}: {exc}") from None
    return resources
