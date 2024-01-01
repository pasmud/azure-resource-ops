"""Materialize synthetic inventories and hand-specified answer tables; stdlib only."""

import hashlib
import json
from itertools import product
from pathlib import Path

A = "aaaaaaaa-1111-4111-8111-111111111111"
B = "bbbbbbbb-2222-4222-8222-222222222222"
READY = {"Env": "ready"}


def rid(sub, group=None, path=""):
    base = f"/subscriptions/{sub}"
    return base + (f"/resourceGroups/{group}" if group else "") + path


def row(identifier, tags=None, **metadata):
    return {"id": identifier, "tags": tags, **metadata}


def policy(subscriptions=(A,), ensure=READY, protected=(), **scope):
    return {
        "subscriptions": list(subscriptions),
        "ensure": ensure,
        "protected": list(protected),
        **scope,
    }


def expected(pol, *targets, canonical=None, check_scope=False):
    """Package explicit (ID, delta) answers in their specified output order."""
    targets = [(identifier, delta) for identifier, delta in targets if delta]
    subscriptions = {identifier.split("/")[2].lower() for identifier, _ in targets}
    counts = [len(delta) for _, delta in targets]
    result = {
        "exit_code": 4 if targets else 0,
        "changes": [{"id": identifier, "merge": delta} for identifier, delta in targets],
        "audit": {
            "report_version": 2,
            "kind": "plan_audit",
            "status": "changes_planned" if targets else "no_changes",
            "summary": {
                "scoped_subscription_count": len(pol["subscriptions"]),
                "targeted_subscription_count": len(subscriptions),
                "resource_count": len(targets),
                "assignment_count": sum(counts),
            },
            "changes": [{"change": i, "assignment_count": count} for i, count in enumerate(counts, 1)],
        },
    }
    if canonical is not None:
        result["before_sha256"] = [
            hashlib.sha256(canonical[identifier].encode("ascii")).hexdigest() for identifier, _ in targets
        ]
    if check_scope:
        result["scope"] = {
            key: sorted(item.casefold() for item in values) for key, values in pol.items() if key != "ensure"
        }
    return result


def vector(title, inventory, pol, answer, **extra):
    return {"title": title, "inventory": inventory, "policy": pol, "expected": answer, **extra}


def selectors(groups, types):
    return {key: values for key, values in (("resource_groups", groups), ("resource_types", types)) if values}


def deltas():
    # Raw tag state and the exact keys to write are separate columns. The two
    # peers deliberately use different misses (absent, stale, empty, or case drift).
    ensure = {"Env": "ready", "Note": "", "Release": "café"}
    profiles = {
        "equal": (("ready", "", "café"), ("ready", "", "café"), ()),
        "env": ((None, "", "café"), ("READY", "", "café"), ("Env",)),
        "note": (("ready", "old", "café"), ("ready", None, "café"), ("Note",)),
        "rel": (("ready", "", "cafe\u0301"), ("ready", "", None), ("Release",)),
        "env-note": (("READY", None, "café"), ("ready ", " ", "café"), ("Env", "Note")),
        "env-rel": (("", "", None), (None, "", "CAFÉ"), ("Env", "Release")),
        "note-rel": (("ready", " ", "cafe"), ("ready", None, "CAFÉ"), ("Note", "Release")),
        "all": ((None, "old", None), ("old", None, ""), ("Env", "Note", "Release")),
    }
    left, right = rid(A, "alpha"), rid(A, "Zulu")
    for (lname, (ltags, _, lkeys)), (rname, (_, rtags, rkeys)) in product(profiles.items(), repeat=2):
        protected = ("OwNeR", "BILLING") if "Note" in rkeys else ("OWNER", "Release.Legacy")
        pol = policy(ensure=ensure, protected=protected, resource_groups=["ZULU", "ALPHA"])
        tags_a = {k: v for k, v in zip(("eNv", "NOTE", "release"), ltags) if v is not None}
        tags_b = {k: v for k, v in zip(("RELEASE", "note", "ENV"), reversed(rtags)) if v is not None}
        inventory = [
            row(right, tags_b | {"OWNER": "right", "Billing": "west"}),
            row(rid(A, "alpha-archive"), {"Owner": "out of scope"}),
            row(left, {"owner": "left", "RELEASE.LEGACY": "keep"} | tags_a),
        ]
        answer = expected(pol, (left, {k: ensure[k] for k in lkeys}), (right, {k: ensure[k] for k in rkeys}))
        title = f"Merge alpha {lname} and Zulu {rname} deltas independently"
        yield f"delta-alpha-{lname}-zulu-{rname}", vector(title, inventory, pol, answer)


def flat_scope():
    # The order here is the expected ID order; the saved inventory reverses it.
    x, y = "Fake.Provider/things", "Fake.Provider/thingsExtra"
    z, other = "Other.Provider/things", "Other.Provider/extra"
    # fmt: off
    specs = {
        "ao": (A, "west-2", other), "ax": (A, "west", x), "ay": (A, "west", y), "az": (A, "west", z),
        "b2": (B, "west-2", x), "bx": (B, "WEST", x), "by": (B, "WEST", y), "bz": (B, "WEST", z),
        "bw": (B, "western", y),
    }
    # fmt: on
    ids = {slot: rid(sub, group, f"/providers/{kind}/asset") for slot, (sub, group, kind) in specs.items()}
    scopes = [
        ("a-west", [A.upper()], ["WEST"], "ax ay az"),
        ("b-west", [B], ["west"], "bx by bz"),
        ("both-west", [B, A], ["WeSt"], "ax ay az bx by bz"),
        ("both-west2", [A, B.upper()], ["WEST-2"], "ao b2"),
        ("a-two-groups", [A], ["west-2", "WEST"], "ax ay az ao"),
        ("b-any-group", [B], [], "bx by bz b2 bw"),
        ("both-any-group", [B.upper(), A], [], "ax ay az ao bx by bz b2 bw"),
        ("both-outer-groups", [B, A], ["WESTERN", "west-2"], "ao b2 bw"),
    ]
    menus = [
        ("any", [], "ax ay az ao bx by bz b2 bw"),
        ("things", [x.upper()], "ax bx b2"),
        ("longer-type", [y], "ay by bw"),
        ("other-provider", [z.swapcase()], "az bz"),
        ("same-provider", [y, x], "ax ay bx by b2 bw"),
        ("same-leaf", [z, x], "ax az bx bz b2"),
        ("other-two", [z, y], "ay az by bz bw"),
        ("three-types", [z, y, x.upper()], "ax ay az bx by bz b2 bw"),
    ]
    inventory = [
        row(
            identifier,
            {"Owner": "keep", "Env.Legacy": "ready"},
            subscriptionId=specs[slot][0].upper(),
            resourceGroup="metadata-only",
            type="Metadata.Provider/ignored",
        )
        for slot, identifier in reversed(ids.items())
    ]
    for (scope, subs, groups, group_slots), (menu, types, type_slots) in product(scopes, menus):
        pol = policy(subs, protected=["Env.Legacy", "Owner"], **selectors(groups, types))
        selected = set(group_slots.split()) & set(type_slots.split())
        targets = [(identifier, READY) for slot, identifier in ids.items() if slot in selected]
        answer = expected(pol, *targets, check_scope=True)
        yield f"scope-{scope}-{menu}", vector(f"Select {menu} in {scope}", inventory, pol, answer)


def arm_paths():
    # An extension on a group, on a parent, on a deep child, and on an
    # extension's child. Each tuple spells out the expected final ARM types.
    # fmt: off
    layouts = [
        ("group-extension", "Fake.Compute/hosts", "/slots", "/slots/s", "", "Fake.Monitor/checks", ""),
        ("parent-extension", "Fake.Storage/volumes", "/shares", "/shares/s", "parent", "Fake.Auth/locks", ""),
        ("deep-extension", "Fake.Network/nets", "/regions/subnets", "/regions/r/subnets/s", "child",
         "Fake.Monitor/checks", ""),
        ("nested-extension", "Fake.Compute/hosts", "/slots", "/slots/s", "child",
         "Fake.Attach/links/rules", "/providers/Fake.Attach/links/upstream/rules/r"),
    ]
    # fmt: on
    for name, ptype, ctype, child_path, anchor, etype, extra in layouts:
        group = rid(A, "Ops")
        parent = f"/providers/{ptype}/node+1"
        child = parent + child_path
        namespace, kind, *subtype = etype.split("/")
        extension = f"/PROVIDERS/{namespace}/{kind}/node:1" + (f"/{subtype[0]}/leaf~1" if subtype else "")
        ext_path = {"": "", "parent": parent, "child": child}[anchor] + extra + extension
        # Subscription-level IDs precede grouped IDs. The parent extension
        # sorts before its sibling share because "providers" precedes "shares".
        ids = {
            "s": rid(A) + extension,
            "g": group,
            "p": group + parent,
            "c": group + child,
            "e": group + ext_path,
        }
        ordered = "sgpce" if name != "parent-extension" else "sgpec"
        rgtype = "Microsoft.Resources/resourceGroups"
        menus = [
            ("parent-type", [], [ptype], "p"),
            ("exact-child-type", [], [ptype + ctype], "c"),
            ("extension-type", [], [etype.upper()], "se"),
            ("group-type", [], [rgtype], "g"),
            ("parent-and-child", [], [ptype + ctype, ptype], "pc"),
            ("unfiltered", [], [], "sgpce"),
            ("grouped-any-type", ["OPS"], [], "gpce"),
            ("grouped-extension", ["ops"], [etype], "e"),
            ("grouped-child", ["OPS"], [ptype + ctype], "c"),
            ("group-and-extension", ["Ops"], [etype, rgtype], "ge"),
            ("missing-group", ["ops-next"], [etype], ""),
            ("near-miss-child-type", ["Ops"], [ptype + ctype + "-extra"], ""),
        ]
        inventory = [
            row(ids[key], {"Team": "keep", "env": "old"} if key in "ge" else None) for key in "cepsg"
        ]
        for menu, groups, types, selected in menus:
            pol = policy(protected=["Team", "Cost.Center"], **selectors(groups, types))
            targets = [(ids[slot], READY) for slot in ordered if slot in selected]
            answer = expected(pol, *targets, check_scope=True)
            yield f"arm-{name}-{menu}", vector(f"Match {menu} on a {name} path", inventory, pol, answer)


def snapshots():
    # (raw tags, literal canonical bytes if planned); None in the second column
    # designates a resource already at the desired state, including after a refresh.
    none = (None, "{}")
    empty = ({}, "{}")
    stale = ({"eNv": "old"}, '{"env":"old"}')
    ready = ({"eNv": "ready"}, None)
    owner = ({"Owner": "east"}, '{"owner":"east"}')
    order = ({"Env": "old", "Owner": "east"}, '{"env":"old","owner":"east"}')
    # fmt: off
    cases = [
        ("null-to-empty", none, empty, True),
        ("empty-to-null", empty, none, True),
        ("managed-key-case", stale, ({"ENV": "old"}, '{"env":"old"}'), True),
        ("protected-key-case", owner, ({"OWNER": "east"}, '{"owner":"east"}'), True),
        ("tag-order", order, ({"Owner": "east", "Env": "old"}, '{"env":"old","owner":"east"}'), True),
        ("unicode-key-fold", ({"Straße": "keep"}, '{"strasse":"keep"}'),
         ({"STRASSE": "keep"}, '{"strasse":"keep"}'), True),
        ("escaped-text", ({"Label": 'café "x"'}, r'{"label":"caf\u00e9 \"x\""}'),
         ({"LABEL": 'café "x"'}, r'{"label":"caf\u00e9 \"x\""}'), True),
        ("protected-value-drift", owner, ({"Owner": "west"}, '{"owner":"west"}'), False),
        ("protected-added", stale, order, False),
        ("protected-removed", order, stale, False),
        ("unmanaged-blank-added", empty, ({"Other": ""}, '{"other":""}'), False),
        ("key-spelling-changed", ({"A.B": "x"}, '{"a.b":"x"}'), ({"A:B": "x"}, '{"a:b":"x"}'), False),
        ("value-space-drift", owner, ({"Owner": "east "}, '{"owner":"east "}'), False),
        ("unicode-value-drift", ({"Label": "café"}, r'{"label":"caf\u00e9"}'),
         ({"Label": "cafe\u0301"}, r'{"label":"cafe\u0301"}'), False),
        ("managed-converges", stale, ready, False),
        ("managed-regresses", ready, stale, False),
    ]
    # fmt: on
    peers = [
        ("peer-pending", empty, none, True),
        ("peer-converges", empty, ready, False),
        ("peer-steady", ready, ({"ENV": "ready", "Owner": "irrelevant"}, None), True),
        ("peer-regresses", ready, empty, False),
    ]
    left, right = rid(A.upper(), "Ops"), rid(B, "ops")
    excluded = rid(B, "ops-archive")
    for (name, first, refreshed, kept), (peer, start, finish, peer_kept) in product(cases, peers):
        pol = policy([B, A], protected=["Owner", "STRASSE"], resource_groups=["OPS"])

        def snapshot(a, b, decoy):
            rows = [row(left, a[0]), row(right, b[0]), row(excluded, decoy)]
            answer = expected(
                pol,
                (left, READY if a[1] else {}),
                (right, READY if b[1] else {}),
                canonical={left: a[1], right: b[1]},
            )
            return rows, answer

        rows, answer = snapshot(first, start, None)
        updated, revised = snapshot(refreshed, finish, {"Owner": "outside scope changed"})
        refresh = {
            "inventory": {"data": updated, "count": 3},
            "inventory_match": kept and peer_kept,
            "expected": revised,
        }
        title = f"Refresh {name} with {peer}"
        yield f"snapshot-{name}-{peer}", vector(title, list(reversed(rows)), pol, answer, refresh=refresh)


def graph_exports():
    first, second = rid(A, "alpha"), rid(B, "beta")
    pol = policy([B, A], protected=["Owner"], resource_groups=["BETA", "alpha"])
    pending = [row(second, {"env": "READY", "Owner": "keep"}), row(first)]
    bad_flag = "inventory is truncated or has an invalid truncation flag"
    bad_count = "inventory row count does not match response metadata"
    for label, rows, targets in [
        ("empty", [], ()),
        ("pending", pending, ((first, READY), (second, READY))),
    ]:
        n = len(rows)
        # fmt: off
        pages = [
            ("minimal", {}, None),
            ("camel-complete", {"totalRecords": n, "resultTruncated": "false", "skipToken": ""}, None),
            ("snake-complete", {"total_records": n, "result_truncated": False, "skip_token": None}, None),
            ("token-present", {"$skipToken": "synthetic-cursor"},
             "inventory has a continuation token; export and combine all pages"),
            ("true-truncation", {"resultTruncated": True}, bad_flag),
            ("bad-truncation-case", {"result_truncated": "False"}, bad_flag),
            ("boolean-count", {"count": False}, bad_count),
            ("inconsistent-totals", {"count": n, "totalRecords": n, "total_records": n + 1}, bad_count),
        ]
        # fmt: on
        for name, metadata, error in pages:
            answer = {"exit_code": 2, "error": error} if error else expected(pol, *targets)
            title = f"Read {label} Graph export: {name}"
            yield f"graph-{label}-{name}", vector(title, {"data": rows} | metadata, pol, answer)


def invalid_rows():
    valid = row(rid(A, "alpha"))
    pol = policy(
        protected=["Owner"],
        resource_groups=["ALPHA"],
        resource_types=["Microsoft.Resources/resourceGroups", "Fake.Provider/things"],
    )
    bad_value = "tag values must be strings of at most 256 characters without controls"
    for name, target, duplicate in [
        ("included", rid(A, "alpha", "/providers/Fake.Provider/things/next"), rid(A, "alpha")),
        ("excluded", rid(B, "beta"), rid(B, "beta")),
    ]:
        metadata_sub = B if name == "included" else A
        faults = [
            ("tag-alias", row(target, {"Owner": "a", "OWNER": "b"}), "duplicate case-insensitive tag name"),
            ("long-value", row(target, {"Note": "x" * 257}), bad_value),
            ("control-value", row(target, {"Note": "with\tcontrol"}), bad_value),
            (
                "subscription-metadata",
                row(target, subscription_id=metadata_sub),
                "subscription metadata disagrees with resource ID",
            ),
            ("encoded-segment", row(target + "%20"), "invalid resource ID segment"),
            ("empty-segment", row(target + "/"), "invalid resource ID segment"),
            ("missing-tags", {"id": target}, "expected an object with id and tags fields"),
            ("duplicate-id-case", row(duplicate.upper()), "duplicate resource ID"),
        ]
        for fault, malformed, error in faults:
            prefix = [valid]
            if fault == "duplicate-id-case" and name == "excluded":
                prefix.append(row(duplicate))
            answer = {"exit_code": 2, "error": f"inventory row {len(prefix) + 1}: {error}"}
            title = f"Reject {fault} on {name} row before emitting a plan"
            yield f"invalid-{name}-{fault}", vector(title, [*prefix, malformed], pol, answer)


def main():
    destination = Path(__file__).with_name("regression_vectors")
    destination.mkdir(exist_ok=True)
    seen_slugs, seen_titles = set(), set()
    for family in (deltas, flat_scope, arm_paths, snapshots, graph_exports, invalid_rows):
        for slug, case in family():
            title = case["title"]
            assert slug not in seen_slugs and title not in seen_titles, (slug, title)
            assert 0 < len(title) < 72 and title.isprintable(), title
            seen_slugs.add(slug)
            seen_titles.add(title)
            (destination / f"{slug}.json").write_text(
                json.dumps(case, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )


if __name__ == "__main__":
    main()
