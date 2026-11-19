"""The ``memory`` tools of selection and design, and the reads of runs and executions, through a real server process
and the real client, on shop-api after ``/run all --on both`` (RUN-0001 against v1.0, RUN-0002 against v1.1) and an
impact analysis: the result of each tool, and one test for each error code it can return (mcp-tools.md)."""

from types import SimpleNamespace

import pytest
from fixtures.example_project import example_project, project_copy
from fixtures.mcp_project import dump, error_of, open_session

from retroagent.mcp_client import Client
from retroagent.memory import connect, design, interpretation

pytestmark = pytest.mark.network

SEARCH = "test_req_001_search_results_are_sorted_by_name"
SHIPPING = "test_req_005_shipping_charged_when_discount_drops_below_threshold"
SECOND_COUPON = "test_req_004_second_coupon_is_rejected"
ORDER_HISTORY = "test_req_008_"  # the tests added in v1.1 for REQ-008
FIELDS = {
    "title": "A quantity above the stock is rejected",
    "objective": "Verify that adding more units than in stock is refused and the cart does not change.",
    "priority": "high",
    "preconditions": ["A product with stock 5", "An empty cart"],
    "input_data": [{"name": "quantity", "value": "6"}],
    "steps": ["Add 6 units of the product to the cart", "Read the cart"],
    "expected_result": "The request is rejected with status 409 and the cart stays empty.",
    "requirement_ids": ["REQ-002"],
}


@pytest.fixture(scope="module")
def shop(tmp_path_factory, shop_after_both_runs):
    """A copy of the project after both full runs, with the requirements synchronized and an impact recorded for
    analysis 1 of v1.0..v1.1. ``client()`` gives a client for a session with other versions or result limit."""
    with project_copy(tmp_path_factory, shop_after_both_runs.path) as path:
        clients: dict[tuple, Client] = {}

        def client(base="v1.0", candidate="v1.1", limit=20_000) -> Client:
            if (base, candidate, limit) not in clients:
                clients[base, candidate, limit] = Client(path, open_session(path, base, candidate, limit))
                clients[base, candidate, limit].start()
            return clients[base, candidate, limit]

        main = client()
        client(base="v1.1", candidate="v1.2"), client(base=None)  # opened now: a session row is not a write of a tool
        main.call("memory", "sync_requirements")
        analysis = main.call("git", "analyze_changes")
        main.call(
            "memory",
            "save_impact",
            {
                "analysis_id": analysis["analysis_id"],
                "modules": [
                    {
                        "module": "shop",
                        "files": [f["path"] for f in analysis["files"]],
                        "risk_level": "high",
                        "reason": "Changed.",
                    }
                ],  # fmt: skip
                "requirements": [{"requirement_id": f"REQ-00{n}", "reason": "Impacted."} for n in range(2, 9)],
                "not_impacted": [{"requirement_id": "REQ-001", "reason": "Catalog search did not change."}],
            },
        )
        test_cases = main.call("memory", "get_test_cases")["test_cases"]
        by_name = {tc["test_id"].rpartition("::")[2]: tc["id"] for tc in test_cases}
        yield SimpleNamespace(path=path, client=client, analysis_id=analysis["analysis_id"], by_name=by_name)
        for started in clients.values():
            started.stop()


def call(shop, tool, arguments=None, **session):
    return shop.client(**session).call("memory", tool, arguments or {})


def failure(shop, tool, arguments=None, **session):
    return error_of(lambda: call(shop, tool, arguments, **session))


def code(shop, tool, arguments=None, **session) -> str:
    return failure(shop, tool, arguments, **session).code


def tc(shop, name: str) -> str:
    return shop.by_name[name]


def item(test_case_id: str, position: int, reason: str = "Traced to an impacted requirement.") -> dict:
    return {"test_case_id": test_case_id, "position": position, "selection_reason": reason}


IMPACTED = [f"REQ-00{n}" for n in range(2, 9)]  # the impact of the analysis of the fixture


def to_decide(shop, requirement_ids=IMPACTED) -> list[str]:
    """The implemented test cases traced to one of these requirements, as get_test_cases lists them."""
    return [
        test_case["id"]
        for test_case in call(shop, "get_test_cases")["test_cases"]
        if test_case["status"] == "implemented"
        and any(r["requirement_id"] in requirement_ids for r in test_case["requirements"])
    ]


# Passed in RUN-0001 against v1.0 and failed in RUN-0002 against v1.1 (ORACLE.md, S2 and S1): never left out.
BROKEN = (SECOND_COUPON, SHIPPING)


def save_arguments(shop, items, reason="Not selected.") -> dict:
    """The arguments of a valid save_suite: the items, the test cases of ``BROKEN`` that they lack after them, and
    every other test case to decide left out."""
    chosen = {i["test_case_id"] for i in items}
    after = max((i["position"] for i in items), default=0)
    missing = [tc(shop, name) for name in BROKEN if tc(shop, name) not in chosen]
    items = [*items, *(item(t, after + n, "Passed on v1.0, fails on v1.1.") for n, t in enumerate(missing, 1))]
    chosen.update(missing)
    left_out = [{"test_case_id": t, "reason": reason} for t in to_decide(shop) if t not in chosen]
    return {"analysis_id": shop.analysis_id, "items": items, "left_out": left_out}


def designed(shop, **changes) -> str:
    """A new designed test case in the current suite, saving an empty suite first when there is none."""
    if failure_or_none(shop, "get_suite") is not None:
        call(shop, "save_suite", save_arguments(shop, []))
    return call(shop, "design_test_case", {**FIELDS, "selection_reason": "Gap of REQ-002.", **changes})["test_case_id"]


def failure_or_none(shop, tool, arguments=None):
    try:
        call(shop, tool, arguments)
    except Exception as error:  # noqa: BLE001 - the ToolError of the call
        return error
    return None


# save_suite and get_suite --------------------------------------------------------------------------------------------


def test_save_suite_becomes_the_current_suite_and_get_suite_returns_it_in_order(shop):
    items = [item(tc(shop, SHIPPING), 2, "Shipping changed."), item(tc(shop, SECOND_COUPON), 1, "REQ-004 changed.")]
    saved = call(shop, "save_suite", save_arguments(shop, items))
    uncovered = ["REQ-002", "REQ-003", "REQ-006", "REQ-007", "REQ-008"]  # impacted, and not REQ-004 or REQ-005
    assert saved == {"suite_id": saved["suite_id"], "analysis_id": shop.analysis_id, "test_cases": 2,
                     "uncovered_requirements": uncovered}  # fmt: skip
    current = call(shop, "get_suite")
    assert current["suite_id"] == saved["suite_id"] and current["analysis_id"] == shop.analysis_id
    assert current["uncovered_requirements"] == uncovered
    assert current["left_out"] == save_arguments(shop, items)["left_out"]  # every other test case to decide, by ID
    assert [(i["position"], i["test_case_id"], i["selection_reason"]) for i in current["items"]] == [
        (1, tc(shop, SECOND_COUPON), "REQ-004 changed."),
        (2, tc(shop, SHIPPING), "Shipping changed."),
    ]
    first = current["items"][0]
    assert (first["title"], first["priority"], first["status"], first["origin"]) == (
        SECOND_COUPON,
        "high",
        "implemented",
        "project_suite",
    )  # fmt: skip  high: REQ-004 is high, and the synchronization gave the test its first name link
    assert call(shop, "get_suite", {"suite_id": saved["suite_id"]}) == current


def test_after_both_full_runs_the_smallest_suite_holds_the_two_test_cases_that_broke(shop):
    # An empty suite is valid without full runs on both versions (tests/unit/test_memory_design.py); here TC-014 and
    # TC-020 passed in RUN-0001 and failed in RUN-0002, so they are never left out.
    empty = save_arguments(shop, [])
    broken = [i["test_case_id"] for i in empty["items"]]
    assert broken == [tc(shop, SECOND_COUPON), tc(shop, SHIPPING)]
    left_out = [*empty["left_out"], *({"test_case_id": t, "reason": "Not impacted."} for t in broken)]
    before = dump(shop.path)
    error = failure(shop, "save_suite", {**empty, "items": [], "left_out": left_out})
    runs = "(passed in RUN-0001 on the baseline, failed in RUN-0002 on the candidate)"
    assert error.code == "invalid_argument"
    assert f"cannot be left out: {broken[0]} {runs}, {broken[1]} {runs}; select each one" in error.message
    assert dump(shop.path) == before
    saved = call(shop, "save_suite", empty)
    assert saved["test_cases"] == 2 and [i["test_case_id"] for i in call(shop, "get_suite")["items"]] == broken
    assert saved["uncovered_requirements"] == ["REQ-002", "REQ-003", "REQ-006", "REQ-007", "REQ-008"]


def test_uncovered_requirements_follow_the_traces_and_a_designed_test_case_removes_one(shop):
    # One project test per impacted requirement that has one, traced by its name: REQ-002 has none (ORACLE.md, S5).
    # TC-002, test_req_003_api_cart_shows_totals, is traced to REQ-003, not to REQ-002, whatever its title says.
    names = [SECOND_COUPON, SHIPPING, "test_req_003_api_cart_shows_totals", "test_req_006_api_checkout_creates_order",
             "test_req_007_tax_rounds_half_up", "test_req_008_api_returns_order_by_id"]  # fmt: skip
    items = [item(tc(shop, name), position) for position, name in enumerate(names, start=1)]
    saved = call(shop, "save_suite", save_arguments(shop, items))
    assert saved["uncovered_requirements"] == ["REQ-002"]
    call(shop, "design_test_case", {**FIELDS, "selection_reason": "Gap of REQ-002."})
    suite = call(shop, "get_suite")  # computed when read
    assert suite["suite_id"] == saved["suite_id"] and suite["uncovered_requirements"] == []


def test_save_suite_errors(shop):
    before = dump(shop.path)
    one = item(tc(shop, SHIPPING), 1)
    assert code(shop, "save_suite", {"analysis_id": 999, "items": [], "left_out": []}) == "not_found"
    assert code(shop, "save_suite", save_arguments(shop, [one, item("TC-999", 2)])) == "not_found"
    unknown = {"test_case_id": "TC-999", "reason": "Obsolete."}
    assert code(shop, "save_suite", {**save_arguments(shop, []), "left_out": [unknown]}) == "not_found"
    twice = failure(shop, "save_suite", save_arguments(shop, [one, {**one, "position": 2}]))
    assert twice.code == "invalid_argument" and f"repeated test cases: {one['test_case_id']}" in twice.message
    same = failure(shop, "save_suite", save_arguments(shop, [one, item(tc(shop, SECOND_COUPON), 1)]))
    assert same.code == "invalid_argument" and "repeated positions: 1" in same.message
    assert code(shop, "save_suite", save_arguments(shop, [{**one, "position": 0}])) == "invalid_argument"
    assert code(shop, "save_suite", {"analysis_id": shop.analysis_id}) == "invalid_argument"
    assert code(shop, "save_suite", {"analysis_id": shop.analysis_id, "items": []}) == "invalid_argument"  # left_out
    # analysis 1 is of v1.0..v1.1: it is not the latest analysis of a session on v1.1..v1.2, and would not be current
    other = failure(shop, "save_suite", save_arguments(shop, []), base="v1.1", candidate="v1.2")
    assert other.code == "invalid_state" and "not the latest analysis" in other.message
    assert code(shop, "save_suite", save_arguments(shop, []), base=None) == "invalid_state"
    assert dump(shop.path) == before


def test_save_suite_refuses_the_test_cases_of_req_004_left_in_neither_list_and_names_all_of_them(shop):
    # The selection of the real model: REQ-004 is impacted with a documented change, and its test cases were missing.
    req_004 = to_decide(shop, ["REQ-004"])
    assert req_004 == sorted(t for name, t in shop.by_name.items() if name.startswith("test_req_004_"))  # by name
    arguments = save_arguments(shop, [])
    arguments["items"] = [i for i in arguments["items"] if i["test_case_id"] not in req_004]  # TC-014 too
    arguments["left_out"] = [entry for entry in arguments["left_out"] if entry["test_case_id"] not in req_004]
    before = dump(shop.path)
    error = failure(shop, "save_suite", arguments)
    assert error.code == "invalid_argument"
    named = ", ".join(f"{test_case_id} (REQ-004)" for test_case_id in req_004)
    assert f"neither items nor left_out: {named};" in error.message
    both = save_arguments(shop, [item(req_004[0], 1)])
    both["left_out"].append({"test_case_id": req_004[0], "reason": "Not selected."})
    error = failure(shop, "save_suite", both)
    assert error.code == "invalid_argument" and f"in both items and left_out: {req_004[0]}" in error.message
    assert dump(shop.path) == before


def verdicts(client, run_id: str) -> dict[str, str]:
    return {e["test_case_id"]: e["result"] for e in client.call("memory", "get_executions", {"run_id": run_id})[
        "executions"] if e["status"] == "executed"}  # fmt: skip


def test_save_suite_refuses_tc_020_left_in_neither_list_naming_both_full_runs(tmp_path_factory, shop_after_both_runs):
    # The selection of the real model: REQ-005 and REQ-007 judged not impacted, so TC-020, the seeded regression, was
    # left out in silence although it passed in RUN-0001 (v1.0) and failed in RUN-0002 (v1.1).
    with project_copy(tmp_path_factory, shop_after_both_runs.path) as path:
        with Client(path, open_session(path, "v1.0", "v1.1")) as client:
            client.call("memory", "sync_requirements")
            analysis = client.call("git", "analyze_changes")
            impacted = ["REQ-002", "REQ-003", "REQ-004", "REQ-006", "REQ-008"]
            client.call("memory", "save_impact", {
                "analysis_id": analysis["analysis_id"],
                "modules": [{"module": "shop", "files": [f["path"] for f in analysis["files"]], "risk_level": "high",
                             "reason": "Changed."}],
                "requirements": [{"requirement_id": r, "reason": "Impacted."} for r in impacted],
                "not_impacted": [{"requirement_id": r, "reason": "Not impacted."}
                                 for r in ("REQ-001", "REQ-005", "REQ-007")],
            })  # fmt: skip
            test_cases = client.call("memory", "get_test_cases")["test_cases"]
            tc_020 = next(t["id"] for t in test_cases if t["test_id"].endswith(SHIPPING))
            traced = [
                {"test_case_id": t["id"], "reason": "Not selected."}
                for t in test_cases
                if t["status"] == "implemented" and any(r["requirement_id"] in impacted for r in t["requirements"])
            ]
            arguments = {"analysis_id": analysis["analysis_id"], "items": [], "left_out": traced}
            before = dump(path)
            error = error_of(lambda: client.call("memory", "save_suite", arguments))
            assert error.code == "invalid_argument"
            assert (
                f"{tc_020} (passed in RUN-0001 on the baseline, failed in RUN-0002 on the candidate)" in error.message
            )
            assert dump(path) == before
            # Every test case it names, decided in one more call, is accepted.
            base, candidate = verdicts(client, "RUN-0001"), verdicts(client, "RUN-0002")
            changed = sorted(
                t for t in base.keys() & candidate.keys() if (base[t] == "passed") != (candidate[t] == "passed")
            )
            undecided = [t for t in changed if t not in {entry["test_case_id"] for entry in traced}]
            assert tc_020 in undecided and all(f"{t} (" in error.message for t in undecided)
            arguments["items"] = [
                item(t, n, "Its verdict changed between the full runs.") for n, t in enumerate(changed, 1)
            ]
            arguments["left_out"] = [entry for entry in traced if entry["test_case_id"] not in changed]
            assert client.call("memory", "save_suite", arguments)["test_cases"] == len(changed)


def test_get_suite_returns_the_test_cases_left_out_with_their_reasons(shop):
    req_004 = to_decide(shop, ["REQ-004"])
    items = [item(test_case_id, n, "REQ-004 changed.") for n, test_case_id in enumerate(req_004, start=1)]
    arguments = save_arguments(shop, items, reason="Covered by the end-to-end tests of the change.")
    obsolete = designed(shop)  # needs no decision, but may be left out
    arguments["left_out"].append({"test_case_id": obsolete, "reason": "Replaced."})
    saved = call(shop, "save_suite", arguments)
    current = call(shop, "get_suite")
    assert current["suite_id"] == saved["suite_id"]
    assert current["left_out"] == sorted(arguments["left_out"], key=lambda entry: entry["test_case_id"])
    assert [i["test_case_id"] for i in current["items"]] == [*req_004, tc(shop, SHIPPING)]
    assert current["uncovered_requirements"] == [r for r in IMPACTED if r not in ("REQ-004", "REQ-005")]  # left out
    # covers nothing


def test_a_retired_test_case_cannot_be_selected(shop):
    retired = designed(shop)
    call(shop, "retire_test_case", {"test_case_id": retired, "reason": "Obsolete."})
    before = dump(shop.path)
    error = failure(shop, "save_suite", save_arguments(shop, [item(retired, 1)]))
    assert error.code == "invalid_argument" and "INV-16" in error.message and retired in error.message
    assert dump(shop.path) == before


def test_get_suite_errors(shop):
    assert code(shop, "get_suite", {"suite_id": 999}) == "not_found"
    assert code(shop, "get_suite", base="v1.1", candidate="v1.2") == "not_found"  # no current suite for them
    assert code(shop, "get_suite", base=None) == "invalid_state"
    assert code(shop, "get_suite", {"suite_id": "current"}) == "invalid_argument"


# design_test_case ----------------------------------------------------------------------------------------------------


def test_design_test_case_stores_every_field_and_adds_it_to_the_end_of_the_current_suite(shop):
    items = [item(tc(shop, SECOND_COUPON), 1), item(tc(shop, SHIPPING), 3)]  # the last position is 3
    suite = call(shop, "save_suite", save_arguments(shop, items))
    created = call(shop, "design_test_case", {**FIELDS, "selection_reason": "Gap of REQ-002: no test."})
    assert created == {"test_case_id": created["test_case_id"], "suite_id": suite["suite_id"], "position": 4}
    (stored,) = call(shop, "get_test_cases", {"ids": [created["test_case_id"]]})["test_cases"]
    assert {key: stored[key] for key in FIELDS if key != "requirement_ids"} == {
        key: value for key, value in FIELDS.items() if key != "requirement_ids"
    }
    assert stored["requirements"] == [{"requirement_id": "REQ-002", "link": "design"}]
    assert (stored["status"], stored["origin"], stored["designed_by"]) == ("designed", "designed", "fake/model")
    assert "implementation" not in stored and "test_id" not in stored
    last = call(shop, "get_suite")["items"][-1]
    assert (last["test_case_id"], last["position"], last["selection_reason"]) == (
        created["test_case_id"], 4, "Gap of REQ-002: no test.",
    )  # fmt: skip


def test_design_test_case_errors(shop):
    call(shop, "save_suite", save_arguments(shop, []))
    arguments = {**FIELDS, "selection_reason": "Gap."}
    before = dump(shop.path)
    assert code(shop, "design_test_case", {**arguments, "requirement_ids": ["REQ-099"]}) == "not_found"
    empty = failure(shop, "design_test_case", {**arguments, "requirement_ids": []})
    assert empty.code == "invalid_argument" and "the project has requirements" in empty.message
    assert code(shop, "design_test_case", {**arguments, "steps": []}) == "invalid_argument"
    assert code(shop, "design_test_case", {**arguments, "priority": "urgent"}) == "invalid_argument"
    assert code(shop, "design_test_case", {**arguments, "input_data": [{"name": "q", "value": 6}]}) == (
        "invalid_argument"
    )
    assert code(shop, "design_test_case", {**arguments, "status": "implemented"}) == "invalid_argument"
    no_suite = failure(shop, "design_test_case", arguments, base="v1.1", candidate="v1.2")
    assert no_suite.code == "invalid_state" and "no current suite" in no_suite.message
    assert dump(shop.path) == before


# update_test_case: one test per row of its table ---------------------------------------------------------------------

EVERY_FIELD = {
    "title": "Six units are refused",
    "objective": "Verify that six units of a product with stock 5 are refused.",
    "priority": "medium",
    "preconditions": ["A product with stock 5"],
    "input_data": [{"name": "quantity", "value": "6"}, {"name": "product", "value": "P-1"}],
    "steps": ["Add 6 units of P-1"],
    "expected_result": "Status 409; the cart is empty.",
    "requirement_ids": ["REQ-002", "REQ-003"],
}


def stored_fields(shop, test_case_id: str) -> dict:
    (stored,) = call(shop, "get_test_cases", {"ids": [test_case_id]})["test_cases"]
    return stored


def test_a_designed_test_case_changes_every_design_field(shop):
    test_case_id = designed(shop)
    result = call(shop, "update_test_case", {"test_case_id": test_case_id, "fields": EVERY_FIELD})
    assert result == {"test_case_id": test_case_id, "updated": sorted(EVERY_FIELD)}
    stored = stored_fields(shop, test_case_id)
    assert {key: stored[key] for key in EVERY_FIELD if key != "requirement_ids"} == {
        key: value for key, value in EVERY_FIELD.items() if key != "requirement_ids"
    }
    assert stored["requirements"] == [
        {"requirement_id": "REQ-002", "link": "design"},
        {"requirement_id": "REQ-003", "link": "design"},
    ]


def test_an_implemented_generated_test_changes_only_title_objective_and_priority(shop):
    test_case_id = designed(shop)
    conn = connect(shop.path)  # implemented as test_runner.write_test would, which comes in a later session
    design.mark_implemented(conn, test_case_id, f"test_{test_case_id.lower()}.py::test_req_002_{test_case_id[3:]}")
    conn.close()
    names = {"title": "Renamed", "objective": "Verify that it is renamed.", "priority": "low"}
    assert call(shop, "update_test_case", {"test_case_id": test_case_id, "fields": names})["updated"] == sorted(names)
    for field in ("preconditions", "input_data", "steps", "expected_result", "requirement_ids"):
        before = dump(shop.path)
        error = failure(shop, "update_test_case", {"test_case_id": test_case_id, "fields": {field: EVERY_FIELD[field]}})
        assert error.code == "invalid_state" and "test_runner.write_test" in error.message, field
        assert dump(shop.path) == before
    stored = stored_fields(shop, test_case_id)
    assert (stored["title"], stored["priority"], stored["steps"]) == ("Renamed", "low", FIELDS["steps"])


def test_a_project_test_changes_every_design_field_and_keeps_its_name_links(shop):
    test_case_id = tc(shop, SECOND_COUPON)
    call(shop, "update_test_case", {"test_case_id": test_case_id, "fields": EVERY_FIELD})
    stored = stored_fields(shop, test_case_id)
    assert stored["objective"] == EVERY_FIELD["objective"] and stored["origin"] == "project_suite"
    assert stored["requirements"] == [
        {"requirement_id": "REQ-002", "link": "design"},
        {"requirement_id": "REQ-003", "link": "design"},
        {"requirement_id": "REQ-004", "link": "name"},
    ]
    call(shop, "update_test_case", {"test_case_id": test_case_id, "fields": {"requirement_ids": []}})
    assert stored_fields(shop, test_case_id)["requirements"] == [{"requirement_id": "REQ-004", "link": "name"}]


def test_a_retired_test_case_cannot_change(shop):
    test_case_id = designed(shop)
    call(shop, "retire_test_case", {"test_case_id": test_case_id, "reason": "Obsolete."})
    error = failure(shop, "update_test_case", {"test_case_id": test_case_id, "fields": {"title": "x"}})
    assert error.code == "invalid_state" and "retired" in error.message


def test_update_test_case_errors(shop):
    test_case_id = designed(shop)
    before = dump(shop.path)
    assert code(shop, "update_test_case", {"test_case_id": "TC-999", "fields": {"title": "x"}}) == "not_found"
    assert code(
        shop, "update_test_case", {"test_case_id": test_case_id, "fields": {"requirement_ids": ["REQ-099"]}}
    ) == ("not_found")
    for fields in ({}, {"selection_reason": "x"}, {"status": "implemented"}, {"steps": []}, {"priority": "urgent"}):
        assert code(shop, "update_test_case", {"test_case_id": test_case_id, "fields": fields}) == "invalid_argument"
    assert dump(shop.path) == before


# retire_test_case ----------------------------------------------------------------------------------------------------


def test_retire_test_case_keeps_the_record_and_hides_it_from_the_default_list(shop):
    test_case_id = designed(shop)
    result = call(shop, "retire_test_case", {"test_case_id": test_case_id, "reason": "Its requirement was removed."})
    assert result["test_case_id"] == test_case_id and result["retired_at"]
    assert test_case_id not in [t["id"] for t in call(shop, "get_test_cases")["test_cases"]]
    assert test_case_id in [t["id"] for t in call(shop, "get_test_cases", {"include_retired": True})["test_cases"]]
    stored = stored_fields(shop, test_case_id)  # asked for by ID: returned although retired
    assert (stored["retired_at"], stored["retire_reason"], stored["retired_by"]) == (
        result["retired_at"], "Its requirement was removed.", "fake/model",
    )  # fmt: skip


def test_retire_test_case_errors(shop):
    test_case_id = designed(shop)
    assert code(shop, "retire_test_case", {"test_case_id": "TC-999", "reason": "r"}) == "not_found"
    assert code(shop, "retire_test_case", {"test_case_id": test_case_id}) == "invalid_argument"
    call(shop, "retire_test_case", {"test_case_id": test_case_id, "reason": "Obsolete."})
    before = dump(shop.path)
    again = failure(shop, "retire_test_case", {"test_case_id": test_case_id, "reason": "Again."})
    assert again.code == "invalid_state" and "already retired" in again.message
    assert dump(shop.path) == before


# get_test_cases ------------------------------------------------------------------------------------------------------


def test_get_test_cases_filters(shop):
    every = call(shop, "get_test_cases")["test_cases"]
    project = [t for t in every if t["origin"] == "project_suite"]
    assert len(project) == 26 and all(t["status"] == "implemented" for t in project)
    search = next(t for t in project if t["id"] == tc(shop, SEARCH))
    assert search["test_id"] == f"tests.test_catalog::{SEARCH}" and search["implementation"].endswith(f"::{SEARCH}")
    assert search["requirements"] == [{"requirement_id": "REQ-001", "link": "name"}]
    assert search["preconditions"] == [] and search["steps"] == []
    traced = call(shop, "get_test_cases", {"requirement_id": "REQ-008"})["test_cases"]
    assert len(traced) == 2 and all(ORDER_HISTORY in t["test_id"] for t in traced)
    designed_only = call(shop, "get_test_cases", {"status": "designed"})["test_cases"]
    assert all(t["status"] == "designed" and t["origin"] == "designed" for t in designed_only)
    asked = call(shop, "get_test_cases", {"ids": [tc(shop, SHIPPING), tc(shop, SEARCH)]})["test_cases"]
    assert sorted(t["id"] for t in asked) == sorted([tc(shop, SHIPPING), tc(shop, SEARCH)])
    assert "truncated" not in call(shop, "get_test_cases", {"ids": [tc(shop, SEARCH)]})


def test_get_test_cases_with_empty_ids_filters_nothing(shop):
    # mcp-tools.md, Empty filters: an empty list has the same effect as an absent one.
    every = call(shop, "get_test_cases")["test_cases"]
    assert every and call(shop, "get_test_cases", {"ids": []})["test_cases"] == every
    implemented = call(shop, "get_test_cases", {"status": "implemented"})["test_cases"]
    assert call(shop, "get_test_cases", {"ids": [], "status": "implemented"})["test_cases"] == implemented


def test_get_test_cases_returns_the_code_of_generated_tests_within_the_result_limit(shop):
    with_code, without_file = designed(shop), designed(shop)
    conn = connect(shop.path)
    for test_case_id in (with_code, without_file):
        design.mark_implemented(
            conn, test_case_id, f"test_code_{test_case_id[3:]}.py::test_req_002_code_{test_case_id[3:]}"
        )
    conn.close()
    code_text = "def test_req_002_code():\n    assert True\n" * 3
    tests_dir = shop.path / ".retro" / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / f"test_code_{with_code[3:]}.py").write_text(code_text, encoding="utf-8")
    ids = {"ids": [with_code, without_file, tc(shop, SEARCH)], "include_code": True}
    result = call(shop, "get_test_cases", ids)
    found = {t["id"]: t for t in result["test_cases"]}
    assert result["truncated"] is False
    assert found[with_code]["code"] == code_text
    assert found[without_file]["code_missing"] is True and "code" not in found[without_file]
    assert "code" not in found[tc(shop, SEARCH)]  # a project test: its code is read with git__read_file
    small = shop.client(limit=len(code_text) - 1).call("memory", "get_test_cases", ids)
    assert small["truncated"] is True
    assert {t["id"]: t.get("code_omitted") for t in small["test_cases"]}[with_code] is True


def test_get_test_cases_errors(shop):
    unknown = failure(shop, "get_test_cases", {"ids": [tc(shop, SEARCH), "TC-998", "TC-999"]})
    assert unknown.code == "not_found" and "TC-998, TC-999" in unknown.message
    assert code(shop, "get_test_cases", {"requirement_id": "REQ-099"}) == "not_found"
    assert code(shop, "get_test_cases", {"status": "executed"}) == "invalid_argument"
    assert code(shop, "get_test_cases", {"include_code": "yes"}) == "invalid_argument"


# get_runs, get_executions and get_test_case_history -----------------------------------------------------------------


def test_get_runs_lists_the_latest_first_with_their_counts(shop):
    runs = call(shop, "get_runs")["runs"]
    assert [r["id"] for r in runs] == ["RUN-0002", "RUN-0001"]
    latest = runs[0]
    assert (latest["version_role"], latest["ref"], latest["scope"], latest["status"]) == (
        "candidate", "v1.1", "all", "completed",
    )  # fmt: skip
    assert latest["commit"] == "46a5ef0910ce409a767f7549ed0c557106409321"
    assert latest["counts"] == {"executed": 26, "blocked": 0, "skipped": 0, "passed": 22, "failed": 4, "error": 0}
    assert runs[1]["counts"]["passed"] == 20 and runs[1]["counts"]["failed"] == 2
    assert [r["id"] for r in call(shop, "get_runs", {"version_role": "base"})["runs"]] == ["RUN-0001"]
    assert [r["id"] for r in call(shop, "get_runs", {"limit": 1})["runs"]] == ["RUN-0002"]


def test_get_runs_errors(shop):
    assert code(shop, "get_runs", {"limit": 0}) == "invalid_argument"
    assert code(shop, "get_runs", {"version_role": "both"}) == "invalid_argument"


def test_get_executions_with_attempts_flakiness_and_triage(shop):
    every = call(shop, "get_executions", {"run_id": "RUN-0002"})
    assert every["run_id"] == "RUN-0002" and len(every["executions"]) == 26
    failed = {e["test_case_id"]: e for e in call(shop, "get_executions", {"run_id": "RUN-0002", "result": "failed"})
              ["executions"]}  # fmt: skip
    assert set(failed) == {tc(shop, n) for n in (SEARCH, SHIPPING, SECOND_COUPON, "test_req_007_tax_rounds_half_up")}
    search = failed[tc(shop, SEARCH)]
    assert (search["title"], search["status"], search["result"], search["flaky"]) == (
        SEARCH,
        "executed",
        "failed",
        True,
    )
    assert [a["result"] for a in search["attempts"]] == ["failed", "passed", "passed"]
    assert [a["number"] for a in search["attempts"]] == [1, 2, 3]
    assert failed[tc(shop, SHIPPING)]["flaky"] is False and failed[tc(shop, SHIPPING)]["triage"] is None
    passed = call(shop, "get_executions", {"run_id": "RUN-0002", "result": "passed"})["executions"]
    assert len(passed) == 22 and all(len(e["attempts"]) == 1 for e in passed)

    untriaged = call(shop, "get_executions", {"run_id": "RUN-0002", "untriaged": True})["executions"]
    assert {e["test_case_id"] for e in untriaged} == set(failed)
    conn = connect(shop.path)  # a triage, then a second one that replaces it
    for classification in ("environment", "regression"):
        interpretation.add_triage(
            conn, execution_id=failed[tc(shop, SHIPPING)]["execution_id"], classification=classification,
            justification="Shipping is charged on the subtotal before discounts.", triaged_by="fake/model",
            replace=classification == "regression",
        )  # fmt: skip
    conn.close()
    untriaged = call(shop, "get_executions", {"run_id": "RUN-0002", "untriaged": True})["executions"]
    assert {e["test_case_id"] for e in untriaged} == set(failed) - {tc(shop, SHIPPING)}
    (shipping,) = [
        e for e in call(shop, "get_executions", {"run_id": "RUN-0002"})["executions"]
        if e["test_case_id"] == tc(shop, SHIPPING)
    ]  # fmt: skip
    assert shipping["triage"]["classification"] == "regression" and shipping["triage_count"] == 2


def test_get_executions_errors(shop):
    assert code(shop, "get_executions", {"run_id": "RUN-9999"}) == "not_found"
    assert code(shop, "get_executions", {"run_id": "RUN-0002", "result": "skipped"}) == "invalid_argument"
    assert code(shop, "get_executions", {}) == "invalid_argument"


def test_get_test_case_history_oldest_first(shop):
    history = call(shop, "get_test_case_history", {"test_case_id": tc(shop, SEARCH)})
    assert history["test_case_id"] == tc(shop, SEARCH)
    assert [(e["run_id"], e["version_role"], e["ref"], e["status"], e["result"], e["flaky"])
            for e in history["executions"]] == [
        ("RUN-0001", "base", "v1.0", "executed", "failed", True),
        ("RUN-0002", "candidate", "v1.1", "executed", "failed", True),
    ]  # fmt: skip
    added = call(shop, "get_test_case_history", {"test_case_id": tc(shop, SECOND_COUPON)})["executions"]
    assert [(e["run_id"], e["result"], e["flaky"]) for e in added] == [
        ("RUN-0001", "passed", False), ("RUN-0002", "failed", False),
    ]  # fmt: skip
    assert call(shop, "get_test_case_history", {"test_case_id": designed(shop)})["executions"] == []


def test_get_test_case_history_errors(shop):
    assert code(shop, "get_test_case_history", {"test_case_id": "TC-999"}) == "not_found"
    assert code(shop, "get_test_case_history", {}) == "invalid_argument"


# The priority of discovered tests, against ORACLE.md -------------------------------------------------------------


def test_discovery_after_synchronization_gives_the_priorities_of_the_oracle(tmp_path_factory, pip_cache):
    """Discovered on v1.0 and v1.1 with the requirements already in memory, as in a cycle: the tests of REQ-002,
    REQ-003, REQ-004 and REQ-006 are high. ORACLE.md counts 15 with TC-027, which is designed later: 14 here."""
    with example_project(tmp_path_factory, pip_cache) as path:
        with Client(path, open_session(path)) as client:
            client.call("memory", "sync_requirements")
            for version in ("base", "candidate"):
                assert client.call("test_runner", "run_tests", {"version": version, "scope": "all"})["status"] == (
                    "completed"
                )
            test_cases = client.call("memory", "get_test_cases")["test_cases"]
    assert len(test_cases) == 26 and {t["origin"] for t in test_cases} == {"project_suite"}
    by_priority: dict[str, set[str]] = {}
    for test_case in test_cases:
        requirement_ids = {link["requirement_id"] for link in test_case["requirements"]}
        by_priority.setdefault(test_case["priority"], set()).update(requirement_ids)
    high = [t for t in test_cases if t["priority"] == "high"]
    assert len(high) == 14
    assert by_priority == {
        "high": {"REQ-003", "REQ-004", "REQ-006"},  # REQ-002 is high too, but no project test is traced to it
        "medium": {"REQ-001", "REQ-005", "REQ-007"},
        "low": {"REQ-008"},
    }


def test_tests_discovered_before_the_first_synchronization_get_their_priority_from_it(
    tmp_path_factory, shop_after_both_runs
):
    """``/run all --on both`` before the first ``sync_requirements``: discovery finds no requirement, so every test
    starts as medium; the synchronization that gives them their first name links sets their priority again. A second
    synchronization changes nothing, and a priority the model changed is kept."""
    with project_copy(tmp_path_factory, shop_after_both_runs.path) as path:
        with Client(path, open_session(path)) as client:

            def priorities() -> dict[str, tuple[str, frozenset]]:
                return {
                    t["id"]: (t["priority"], frozenset(link["requirement_id"] for link in t["requirements"]))
                    for t in client.call("memory", "get_test_cases")["test_cases"]
                }

            before = priorities()
            assert len(before) == 26 and {priority for priority, _ in before.values()} == {"medium"}
            assert all(not requirement_ids for _, requirement_ids in before.values())  # no requirement known yet

            client.call("memory", "sync_requirements")
            synced = priorities()
            by_requirement: dict[str, set[str]] = {}
            for priority, requirement_ids in synced.values():
                for requirement_id in requirement_ids:
                    by_requirement.setdefault(requirement_id, set()).add(priority)
            assert by_requirement == {
                "REQ-001": {"medium"}, "REQ-003": {"high"}, "REQ-004": {"high"}, "REQ-005": {"medium"},
                "REQ-006": {"high"}, "REQ-007": {"medium"}, "REQ-008": {"low"},
            }  # fmt: skip
            assert sum(priority == "high" for priority, _ in synced.values()) == 14  # as after discovery (ORACLE.md)

            changed = next(test_case_id for test_case_id, (_, ids) in synced.items() if "REQ-003" in ids)
            client.call("memory", "update_test_case", {"test_case_id": changed, "fields": {"priority": "low"}})
            second = client.call("memory", "sync_requirements")
            assert second["name_links_added"] == 0
            assert priorities() == {**synced, changed: ("low", synced[changed][1])}
