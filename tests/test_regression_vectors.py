import hashlib
import json
from pathlib import Path

import pytest

from azure_resource_ops.cli import main

VECTORS = sorted(Path(__file__).with_name("regression_vectors").glob("*.json"))


def unexpected_azure_call(_):
    pytest.fail("regression vectors must run offline")


@pytest.mark.parametrize("path", VECTORS, ids=lambda path: path.stem)
def test_saved_inventory_vector(path, tmp_path, capsys):
    case = json.loads(path.read_text(encoding="utf-8"))
    assert 0 < len(case["title"]) < 72 and case["title"].isprintable()

    def save(name, value):
        file = tmp_path / f"{name}.json"
        file.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return str(file)

    def run(*args):
        code = main(list(args), azure_runner=unexpected_azure_call)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    policy = save("policy", case["policy"])

    def check_plan(inventory, expected, name):
        code, text, error = run("plan", "--inventory", inventory, "--policy", policy, "--exit-code")
        assert code == expected["exit_code"], error
        if "error" in expected:
            assert (text, error) == ("", f"error: {expected['error']}\n")
            return None

        assert not error
        plan = json.loads(text)
        assert plan["version"] == 1
        assert plan["policy"]["ensure"] == case["policy"]["ensure"]
        assert [{"id": row["id"], "merge": row["merge"]} for row in plan["changes"]] == expected["changes"]
        if "before_sha256" in expected:
            assert [row["before_sha256"] for row in plan["changes"]] == expected["before_sha256"]
        if "scope" in expected:
            scope = {key: value for key, value in plan["policy"].items() if key != "ensure"}
            assert scope == expected["scope"]

        plan_path = save(name, plan)
        code, output, error = run("validate", "--plan", plan_path, "--inventory", inventory)
        assert (code, error) == (0, "")
        assert json.loads(output) == {"valid": True, "inventory_match": True}
        code, output, error = run("audit", "--plan", plan_path)
        assert (code, error) == (0, "")
        assert json.loads(output) == expected["audit"] | {
            "plan_sha256": hashlib.sha256(text.encode("ascii")).hexdigest(),
        }
        return plan_path

    original = check_plan(save("inventory", case["inventory"]), case["expected"], "plan")
    if "refresh" in case:
        assert original is not None
        refresh = case["refresh"]
        inventory = save("refresh", refresh["inventory"])
        code, output, error = run("validate", "--plan", original, "--inventory", inventory)
        if refresh["inventory_match"]:
            assert (code, error) == (0, "")
            assert json.loads(output) == {"valid": True, "inventory_match": True}
        else:
            assert (code, output, error) == (
                2,
                "",
                "error: plan does not match the supplied inventory and embedded policy\n",
            )
        check_plan(inventory, refresh["expected"], "replacement")
