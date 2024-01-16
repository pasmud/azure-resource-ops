import pytest

from azure_resource_ops.core import InputError, Resource
from azure_resource_ops.inventory import parse_inventory
from azure_resource_ops.jsonio import decode, read_json

SUB = "11111111-1111-4111-8111-111111111111"
RID = f"/subscriptions/{SUB}/resourceGroups/fake/providers/Fake.Provider/parents/p/children/c"
ROW = {"id": RID, "tags": None, "subscriptionId": SUB, "unrelatedField": "ignored"}


def test_cli_and_resource_graph_normalize_to_same_rows():
    assert parse_inventory([ROW]) == parse_inventory({
        "data": [ROW], "count": 1, "total_records": 1, "result_truncated": False,
        "skip_token": None,
    }) == [Resource(RID, {})]


@pytest.mark.parametrize("metadata", [
    {"skipToken": "fake-token"}, {"resultTruncated": "true"}, {"totalRecords": 2}, {"count": True},
])
def test_incomplete_or_inconsistent_graph_pages_are_rejected(metadata):
    with pytest.raises(InputError, match="inventory"):
        parse_inventory({"data": [ROW]} | metadata)


@pytest.mark.parametrize("rows", [
    [{"id": RID}], [ROW, ROW | {"id": RID.upper()}],
    [ROW | {"subscriptionId": "22222222-2222-4222-8222-222222222222"}],
    [ROW | {"tags": {"env": "one", "ENV": "two"}}],
    [ROW | {"id": RID + "/extra"}], [ROW | {"id": RID + "/type/.."}],
    [ROW | {"id": RID + "?fake=parameter"}],
])
def test_malformed_rows_are_rejected_with_row_context(rows):
    with pytest.raises(InputError, match=r"inventory row [12]:"):
        parse_inventory(rows)


@pytest.mark.parametrize("text", ['{"data": [], "data": []}', '{"limit": NaN}', '[broken]'])
def test_strict_json_rejects_ambiguous_input(text):
    with pytest.raises(InputError):
        decode(text)


def test_read_error_does_not_echo_path(tmp_path):
    with pytest.raises(InputError, match="^cannot read inventory as UTF-8$"):
        read_json(tmp_path / "fake-sensitive-path", "inventory")
