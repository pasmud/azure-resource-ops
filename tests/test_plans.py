import pytest

from azure_resource_ops.core import InputError, Policy, Resource, build_plan
from azure_resource_ops.jsonio import decode, render
from azure_resource_ops.plans import Plan

SUB = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
RID = f"/subscriptions/{SUB}/resourceGroups/fake"


@pytest.fixture
def plan():
    policy = Policy.parse({"subscriptions": [SUB], "ensure": {"Env": "demo"}, "protected": ["Owner"]})
    return build_plan([Resource(RID, {})], policy)


def test_generated_plan_round_trip(plan):
    result = Plan.parse(decode(render(plan)))
    assert result.policy.subscriptions == (SUB,)
    assert result.changes[0].merge == {"Env": "demo"}


@pytest.mark.parametrize("patch", [
    {"version": True}, {"version": 3}, {"extra": "ignored?"}, {"changes": {}},
])
def test_rejects_bad_plan_envelopes(plan, patch):
    with pytest.raises(InputError):
        Plan.parse(plan | patch)


@pytest.mark.parametrize("patch", [
    {"merge": {}}, {"merge": {"Env": None}}, {"merge": {"Owner": "x"}},
    {"merge": {"Env": "different"}}, {"merge": {"env": "demo"}},
    {"delete": ["Owner"]}, {"id": RID.replace(SUB, OTHER)}, {"before_sha256": "not-a-digest"},
])
def test_rejects_invalid_change(plan, patch):
    plan["changes"][0].update(patch)
    with pytest.raises(InputError, match="plan change 1:"):
        Plan.parse(plan)


def test_rejects_duplicate_target_with_different_casing(plan):
    plan["changes"].append(plan["changes"][0] | {"id": RID.upper()})
    with pytest.raises(InputError, match="duplicate resource ID"):
        Plan.parse(plan)


@pytest.mark.parametrize("id_suffix", ["-other", "/providers/Fake.Provider/things/other"])
def test_saved_plan_retains_filters_and_rejects_targets_outside_them(plan, id_suffix):
    plan["policy"].update(resource_groups=["fake"], resource_types=["microsoft.resources/resourcegroups"])
    parsed = Plan.parse(plan)
    assert parsed.as_dict() == plan
    parsed.verify_inventory([Resource(RID, {}), Resource(RID + id_suffix, {})])
    plan["changes"][0]["id"] += id_suffix
    with pytest.raises(InputError, match="outside plan policy scope"):
        Plan.parse(plan)
