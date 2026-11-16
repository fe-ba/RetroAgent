"""Test design functions of the data layer: ``update_test_case`` (mcp-tools.md, ``memory.update_test_case``) and
links by name (project-contract.md, Traceability)."""

import json

import pytest

from retroagent.memory import design
from retroagent.memory.errors import InvariantViolation


def links(conn, test_case_id):
    return sorted(
        tuple(r)
        for r in conn.execute(
            "SELECT requirement_id, link FROM test_case_requirement WHERE test_case_id = ?", (test_case_id,)
        )
    )


def project_test(conn, test_id):
    return design.add_project_suite_test_case(conn, test_id=test_id, implementation=test_id.replace(".", "/"))


# update_test_case


def test_designed_test_case_can_change_every_design_field_but_links(conn, build):
    test_case_id = build.test_case(implemented=False)
    design.update_test_case(
        conn,
        test_case_id,
        {
            "title": "new title",
            "objective": "new objective",
            "priority": "low",
            "preconditions": ["a product with stock 2"],
            "input_data": [{"name": "quantity", "value": 3}],
            "steps": ["add 3 units"],
            "expected_result": "rejected",
        },
    )
    row = design.get_test_case(conn, test_case_id)
    assert (row["title"], row["objective"], row["priority"], row["expected_result"]) == (
        "new title",
        "new objective",
        "low",
        "rejected",
    )
    assert json.loads(row["input_data"]) == [{"name": "quantity", "value": 3}]
    assert json.loads(row["steps"]) == ["add 3 units"]


def test_implemented_generated_test_changes_only_title_objective_and_priority(conn, build):
    test_case_id = build.test_case(implemented=True)
    design.update_test_case(conn, test_case_id, {"title": "t", "objective": "o", "priority": "low"})
    assert design.get_test_case(conn, test_case_id)["priority"] == "low"
    for field, value in [("steps", ["x"]), ("expected_result", "y"), ("preconditions", []), ("input_data", [])]:
        with pytest.raises(InvariantViolation, match=f"invalid_state: {field}"):
            design.update_test_case(conn, test_case_id, {field: value})


def test_project_test_can_change_every_design_field(conn):
    test_case_id = project_test(conn, "tests.test_cart::test_total")
    design.update_test_case(conn, test_case_id, {"priority": "high", "steps": ["s"], "expected_result": "e"})
    row = design.get_test_case(conn, test_case_id)
    assert (row["priority"], row["expected_result"]) == ("high", "e")


def test_retired_unknown_or_foreign_fields_are_refused_and_nothing_changes(conn, build):
    test_case_id = build.test_case(implemented=False)
    with pytest.raises(InvariantViolation, match="invalid_state: status"):
        design.update_test_case(conn, test_case_id, {"priority": "low", "status": "implemented"})
    with pytest.raises(InvariantViolation, match="invalid_state: selection_reason"):
        design.update_test_case(conn, test_case_id, {"selection_reason": "x"})
    assert design.get_test_case(conn, test_case_id)["priority"] == "high"
    with pytest.raises(InvariantViolation, match="INV-13"):
        design.update_test_case(conn, "TC-999", {"title": "x"})
    design.retire_test_case(conn, test_case_id, reason="obsolete", retired_by="user")
    with pytest.raises(InvariantViolation, match="invalid_state: test case .* is retired"):
        design.update_test_case(conn, test_case_id, {"title": "x"})


def test_requirement_ids_replace_the_design_links_of_a_designed_test_case(conn, build):
    for requirement_id in ("REQ-001", "REQ-002", "REQ-003"):
        build.requirement(requirement_id)
    test_case_id = build.test_case(implemented=False, requirement_ids=["REQ-001", "REQ-002"])
    design.update_test_case(conn, test_case_id, {"requirement_ids": ["REQ-002", "REQ-003"]})
    assert links(conn, test_case_id) == [("REQ-002", "design"), ("REQ-003", "design")]
    design.update_test_case(conn, test_case_id, {"requirement_ids": []})
    assert links(conn, test_case_id) == []


def test_requirement_ids_of_a_project_test_keep_the_links_found_in_its_name(conn, build):
    build.requirement("REQ-004")
    build.requirement("REQ-005")
    test_case_id = project_test(conn, "tests.test_d::test_req_004_coupon")
    design.update_test_case(conn, test_case_id, {"requirement_ids": ["REQ-004", "REQ-005"]})
    assert links(conn, test_case_id) == [("REQ-004", "design"), ("REQ-004", "name"), ("REQ-005", "design")]
    design.update_test_case(conn, test_case_id, {"requirement_ids": []})
    assert links(conn, test_case_id) == [("REQ-004", "name")]


def test_requirement_ids_cannot_change_for_an_implemented_generated_test(conn, build):
    build.requirement("REQ-001")
    test_case_id = build.test_case(implemented=True, requirement_ids=["REQ-001"])
    with pytest.raises(InvariantViolation, match="invalid_state: requirement_ids"):
        design.update_test_case(conn, test_case_id, {"requirement_ids": []})
    assert links(conn, test_case_id) == [("REQ-001", "design")]


def test_an_unknown_requirement_changes_nothing(conn, build):
    build.requirement("REQ-001")
    test_case_id = build.test_case(implemented=False, requirement_ids=["REQ-001"])
    with pytest.raises(InvariantViolation, match="INV-13"):
        design.update_test_case(conn, test_case_id, {"title": "changed", "requirement_ids": ["REQ-001", "REQ-999"]})
    assert links(conn, test_case_id) == [("REQ-001", "design")]
    row = design.get_test_case(conn, test_case_id)
    assert row["title"] != "changed"


# Links by name


def test_requirement_references_in_a_test_name(conn):
    assert design.requirements_in_name("tests.test_x::test_req_004_coupon") == ["REQ-004"]
    assert design.requirements_in_name("tests.test_x::test_REQ-004_and_req005_and_Req_004") == ["REQ-004", "REQ-005"]
    assert design.requirements_in_name("tests.test_req_001::test_total") == []  # only the name, not the class
    assert design.requirements_in_name("tests.test_x::test_request_12") == []


def test_discovery_links_only_requirements_in_memory(conn, build):
    build.requirement("REQ-004")
    test_case_id = project_test(conn, "tests.test_d::test_req_004_and_req_005")
    assert links(conn, test_case_id) == [("REQ-004", "name")]


def test_name_links_do_not_depend_on_the_order_of_discovery_and_synchronization(conn, build):
    early = project_test(conn, "tests.test_d::test_req_004_coupon")
    build.requirement("REQ-004")
    assert links(conn, early) == []
    assert design.link_tests_by_name(conn) == 1
    late = project_test(conn, "tests.test_d::test_req_004_other")
    assert links(conn, early) == links(conn, late) == [("REQ-004", "name")]
    assert design.link_tests_by_name(conn) == 0  # idempotent


def test_generated_tests_are_not_linked_by_name(conn, build):
    build.requirement("REQ-004")
    test_case_id = build.test_case(implemented=True)
    design.link_tests_by_name(conn)
    assert links(conn, test_case_id) == []
