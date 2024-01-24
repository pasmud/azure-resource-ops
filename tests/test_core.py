import pytest

from azure_resource_ops.core import InputError, Policy, Resource, build_plan, fingerprint

SUB = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
RG = f"/subscriptions/{SUB}/resourceGroups/fake-rg"


def test_merge_is_additive_scoped_and_case_insensitive():
    policy = Policy.parse({
        "subscriptions": [SUB], "ensure": {"Env": "demo", "Service": "example"},
        "protected": ["Owner"],
    })
    existing = {"ENV": "demo", "service": "legacy", "Owner": "fake", "Team": "test"}
    plan = build_plan([
        Resource(RG + "/providers/Fake.Provider/things/steady", policy.ensure),
        Resource(RG.replace(SUB, OTHER), {}),
        Resource(RG, existing),
    ], policy)
    assert plan["changes"] == [
        {"id": RG, "before_sha256": fingerprint(existing), "merge": {"Service": "example"}},
    ]
    assert existing["service"] == "legacy"
    assert fingerprint(existing) == fingerprint({k.lower(): existing[k] for k in reversed(existing)})
    assert fingerprint(existing) != fingerprint({**existing, "Owner": "different"})


@pytest.mark.parametrize("patch", [
    {"ensure": {"oWnEr": "demo"}}, {"ensure": {"Tag": "a", "tag": "b"}},
    {"ensure": {"bad=key": "demo"}}, {"ensure": {"tag": None}},
    {"subscriptions": []}, {"subscriptions": [SUB, SUB]}, {"subscriptions": ["*"]},
])
def test_invalid_policy_fails_closed(patch):
    with pytest.raises(InputError):
        Policy.parse({"subscriptions": [SUB], "ensure": {}, "protected": ["Owner"]} | patch)


@pytest.mark.parametrize("patch", [
    {"resource_groups": []}, {"resource_groups": ["*"]}, {"resource_groups": "fake-rg"},
    {"resource_groups": ["fake-rg", "FAKE-RG"]}, {"resource_types": None},
    {"resource_types": ["Fake.Provider/*"]}, {"resource_types": ["things"]},
    {"resource_type": ["Fake.Provider/things"]},
])
def test_invalid_filters_do_not_fall_back_to_subscription_scope(patch):
    with pytest.raises(InputError):
        Policy.parse({"subscriptions": [SUB], "ensure": {"env": "demo"}, "protected": []} | patch)


def test_filters_intersect_scope_and_match_full_types_from_arm_paths():
    parent = RG + "/providers/Fake.Provider/things/demo"
    child = parent + "/widgets/demo"
    extension = child + "/providers/Other.Provider/extras/demo"
    rows = [RG, parent, child, extension, child.replace(SUB, OTHER),
            child.replace("fake-rg", "fake-rg-other"), child.replace("/resourceGroups/fake-rg", "")]
    base = {"subscriptions": [SUB], "ensure": {"env": "demo"}, "protected": []}

    def planned(**filters):
        policy = Policy.parse(base | filters)
        return [change["id"] for change in build_plan([Resource(rid, {}) for rid in rows], policy)["changes"]]

    assert planned(resource_groups=["FAKE-RG"], resource_types=["Other.Provider/extras", "FAKE.Provider/things/widgets"]) == [
        child, extension,
    ]
    assert planned(resource_types=["Fake.Provider/things"]) == [parent]
    assert planned(resource_groups=["fake-rg"], resource_types=["Microsoft.Resources/resourceGroups"]) == [RG]
    assert planned(resource_groups=["typo"]) == []
