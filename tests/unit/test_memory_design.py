"""Test design functions of the data layer: ``update_test_case`` (mcp-tools.md, ``memory.update_test_case``), links
by name (project-contract.md, Traceability), the priority of discovered tests, the uncovered requirements of a
suite and the test cases that ``save_suite`` must decide."""

import json

import pytest
from fixtures.memory_records import BASE_COMMIT, CANDIDATE_COMMIT, count_rows, no_removal

from retroagent.memory import design, execution, impact, requirements
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


def test_a_generated_test_is_bound_once_to_its_junit_entry(conn, build):
    test_case_id = build.test_case()
    design.bind_test_id(conn, test_case_id, "tests.retro.test_case_1::test_case_1")
    assert design.get_test_case(conn, test_case_id)["test_id"] == "tests.retro.test_case_1::test_case_1"
    with pytest.raises(InvariantViolation, match="already bound"):
        design.bind_test_id(conn, test_case_id, "other::test_case_1")
    with pytest.raises(InvariantViolation, match="no generated test"):
        design.bind_test_id(conn, build.test_case(implemented=False), "x::y")
    project = project_test(conn, "tests.test_a::test_a")
    with pytest.raises(InvariantViolation, match="not designed by the agent"):
        design.bind_test_id(conn, project, "tests.test_a::test_b")


def test_active_implemented_test_cases_leave_out_designed_and_retired_ones(conn, build):
    implemented, designed, retired = build.test_case(), build.test_case(implemented=False), build.test_case()
    design.retire_test_case(conn, retired, reason="obsolete", retired_by="fake/model")
    assert [row["id"] for row in design.active_implemented_test_cases(conn)] == [implemented]
    assert designed not in [row["id"] for row in design.active_implemented_test_cases(conn)]


def test_the_current_suite_is_the_latest_suite_of_the_latest_analysis_of_the_versions(conn, build):
    first, second = build.test_case(), build.test_case()
    old = build.suite(first)
    assert design.current_suite(conn, BASE_COMMIT, CANDIDATE_COMMIT) == old
    latest = build.suite(second, first)
    assert design.current_suite(conn, BASE_COMMIT, CANDIDATE_COMMIT) == latest
    assert [row["id"] for row in design.suite_test_cases(conn, latest)] == [second, first]
    assert design.current_suite(conn, BASE_COMMIT, "d" * 40) is None
    build.analysis_id = build.analysis()  # a new analysis starts a new cycle without a suite
    assert design.current_suite(conn, BASE_COMMIT, CANDIDATE_COMMIT) is None


# The priority of a discovered test (data-model.md, test_case)


def requirement(conn, requirement_id, priority):
    requirements.add_requirement(
        conn, id=requirement_id, title="t", description="d", source_file="docs/req.md", priority=priority
    )


def priority_of(conn, test_case_id):
    return design.get_test_case(conn, test_case_id)["priority"]


def test_a_discovered_test_starts_with_the_priority_of_its_requirement(conn):
    requirement(conn, "REQ-003", "high")
    requirement(conn, "REQ-008", "low")
    assert priority_of(conn, project_test(conn, "tests.test_cart::test_req_003_total")) == "high"
    assert priority_of(conn, project_test(conn, "tests.test_orders::test_req_008_history")) == "low"


def test_a_test_linked_to_two_requirements_takes_the_highest_priority(conn):
    requirement(conn, "REQ-005", "medium")
    requirement(conn, "REQ-008", "low")
    requirement(conn, "REQ-004", "high")
    assert priority_of(conn, project_test(conn, "tests.t::test_req_008_req_005_both")) == "medium"
    assert priority_of(conn, project_test(conn, "tests.t::test_req_005_req_004_both")) == "high"


def test_a_test_linked_to_no_requirement_starts_as_medium(conn):
    requirement(conn, "REQ-001", None)  # no documented priority: it does not count
    assert priority_of(conn, project_test(conn, "tests.t::test_health")) == "medium"
    assert priority_of(conn, project_test(conn, "tests.t::test_req_099_not_in_memory")) == "medium"
    assert priority_of(conn, project_test(conn, "tests.t::test_req_001_no_priority")) == "medium"


# Uncovered requirements of a suite (mcp-tools.md, save_suite and get_suite)


def impact_on(conn, build, *impacted):
    impact.record_impact(
        conn,
        build.analysis_id,
        modules=[{"module": "cart", "files": ["app/cart.py"], "risk_level": "high", "reason": "r"}],
        requirements=[{"requirement_id": r, "reason": "r"} for r in impacted],
        not_impacted=[
            {"requirement_id": row["id"], "reason": "r"}
            for row in conn.execute("SELECT id FROM requirement")
            if row["id"] not in impacted
        ],
        removal_applies=no_removal,
    )


def test_no_requirement_is_uncovered_when_the_suite_traces_every_impacted_one(conn, build):
    for requirement_id in ("REQ-001", "REQ-002"):
        build.requirement(requirement_id)
    impact_on(conn, build, "REQ-001", "REQ-002")
    by_design = build.test_case(requirement_ids=["REQ-001"])
    by_name = project_test(conn, "tests.test_cart::test_req_002_add")
    suite_id = design.save_suite(conn, analysis_id=build.analysis_id, session_id=build.session_id, items=[
        {"test_case_id": by_design, "position": 1, "selection_reason": "r"},
        {"test_case_id": by_name, "position": 2, "selection_reason": "r"},
    ], left_out=[])  # fmt: skip
    assert design.uncovered_requirements(conn, suite_id) == []


def test_an_impacted_requirement_without_a_test_case_is_uncovered_until_one_is_designed(conn, build):
    for requirement_id in ("REQ-001", "REQ-002", "REQ-003"):
        build.requirement(requirement_id)
    impact_on(conn, build, "REQ-001", "REQ-002")  # REQ-003 is not impacted: never a gap
    traced = build.test_case(requirement_ids=["REQ-001", "REQ-003"])
    elsewhere = build.test_case(requirement_ids=["REQ-002"])  # traced to REQ-002, but not in the suite
    suite_id = design.save_suite(conn, analysis_id=build.analysis_id, session_id=build.session_id,
                                 items=[{"test_case_id": traced, "position": 1, "selection_reason": "r"}],
                                 left_out=[{"test_case_id": elsewhere, "reason": "r"}])  # fmt: skip
    assert elsewhere and design.uncovered_requirements(conn, suite_id) == ["REQ-002"]
    designed, _ = design.design_test_case(
        conn, suite_id=suite_id, selection_reason="Gap of REQ-002.", designed_by="fake/model", title="t",
        priority="high", steps=["s"], requirement_ids=["REQ-002"],
    )  # fmt: skip
    assert design.uncovered_requirements(conn, suite_id) == []
    design.retire_test_case(conn, designed, reason="Obsolete.", retired_by="fake/model")
    assert design.uncovered_requirements(conn, suite_id) == ["REQ-002"]  # a retired test case covers nothing


def test_the_first_name_links_of_a_synchronization_set_the_priority_again(conn):
    discovered = project_test(conn, "tests.test_cart::test_req_003_total")  # before the requirements are known
    unlinked = project_test(conn, "tests.t::test_health")
    assert priority_of(conn, discovered) == "medium"
    requirement(conn, "REQ-003", "high")
    assert design.link_tests_by_name(conn) == 1
    assert priority_of(conn, discovered) == "high"
    assert priority_of(conn, unlinked) == "medium"  # no link: nothing to set


def test_a_second_synchronization_changes_no_priority(conn):
    requirement(conn, "REQ-008", "low")
    discovered = project_test(conn, "tests.t::test_req_008_history")
    before = conn.execute("SELECT id, priority, updated_at FROM test_case ORDER BY id").fetchall()
    assert design.link_tests_by_name(conn) == 0
    assert conn.execute("SELECT id, priority, updated_at FROM test_case ORDER BY id").fetchall() == before
    assert priority_of(conn, discovered) == "low"


def test_a_priority_changed_after_the_links_is_kept_when_more_links_come(conn):
    requirement(conn, "REQ-005", "medium")
    discovered = project_test(conn, "tests.t::test_req_005_req_004_both")  # linked to REQ-005 only, for now
    design.update_test_case(conn, discovered, {"priority": "low"})  # a change of the model
    requirement(conn, "REQ-004", "high")
    assert design.link_tests_by_name(conn) == 1  # its link to REQ-004, but not its first name link
    assert priority_of(conn, discovered) == "low"
    assert links(conn, discovered) == [("REQ-004", "name"), ("REQ-005", "name")]


# The test cases that save_suite must decide (mcp-tools.md, save_suite)


def selected(*test_case_ids):
    return [{"test_case_id": t, "position": n, "selection_reason": "r"} for n, t in enumerate(test_case_ids, start=1)]


def left(*test_case_ids, reason="Not selected."):
    return [{"test_case_id": t, "reason": reason} for t in test_case_ids]


def save(conn, build, items, left_out):
    return design.save_suite(
        conn, analysis_id=build.analysis_id, session_id=build.session_id, items=items, left_out=left_out
    )


def refused(conn, build, items, left_out) -> str:
    """The message of a refused save_suite, checking that nothing was written."""
    before = count_rows(conn)
    with pytest.raises(InvariantViolation) as error:
        save(conn, build, items, left_out)
    assert count_rows(conn) == before
    return str(error.value)


@pytest.fixture
def impacted(conn, build):
    """REQ-004 and REQ-005 are impacted; REQ-001 is not."""
    for requirement_id in ("REQ-001", "REQ-004", "REQ-005"):
        build.requirement(requirement_id)
    impact_on(conn, build, "REQ-004", "REQ-005")


def test_a_test_case_of_an_impacted_requirement_in_neither_list_is_refused_and_named(conn, build, impacted):
    chosen, forgotten = build.test_case(requirement_ids=["REQ-004"]), build.test_case(requirement_ids=["REQ-004"])
    message = refused(conn, build, selected(chosen), [])
    assert message == (
        "invalid_argument: test cases traced to an impacted requirement are in neither items nor left_out:"
        f" {forgotten} (REQ-004); select each one or add it to left_out with a reason"
    )


def test_every_undecided_test_case_is_named_in_one_message(conn, build, impacted):
    first, second = build.test_case(requirement_ids=["REQ-004"]), build.test_case(requirement_ids=["REQ-004"])
    both = build.test_case(requirement_ids=["REQ-004", "REQ-005"])
    message = refused(conn, build, [], [])
    assert f"neither items nor left_out: {first} (REQ-004), {second} (REQ-004), {both} (REQ-004, REQ-005);" in message


def test_a_test_case_in_both_lists_is_refused_and_named(conn, build, impacted):
    chosen = build.test_case(requirement_ids=["REQ-004"])
    message = refused(conn, build, selected(chosen), left(chosen))
    assert message.startswith("invalid_argument: ") and f"in both items and left_out: {chosen}" in message
    assert "neither" not in message


def test_retired_designed_and_not_impacted_test_cases_need_no_decision(conn, build, impacted):
    chosen = build.test_case(requirement_ids=["REQ-004"])
    designed = build.test_case(implemented=False, requirement_ids=["REQ-004"])
    retired = build.test_case(requirement_ids=["REQ-005"])
    design.retire_test_case(conn, retired, reason="obsolete", retired_by="fake/model")
    elsewhere = build.test_case(requirement_ids=["REQ-001"])
    suite_id = save(conn, build, selected(chosen), [])
    assert designed and elsewhere and design.suite_left_out(conn, suite_id) == []


def test_a_test_case_linked_only_by_name_must_be_decided(conn, build, impacted):
    by_name = project_test(conn, "tests.test_discounts::test_req_004_second_coupon_is_rejected")
    assert links(conn, by_name) == [("REQ-004", "name")]
    assert f"neither items nor left_out: {by_name} (REQ-004);" in refused(conn, build, [], [])
    suite_id = save(conn, build, [], left(by_name, reason="Removed by the change."))
    assert [tuple(row) for row in design.suite_left_out(conn, suite_id)] == [(by_name, "Removed by the change.")]


def test_a_valid_call_stores_the_test_cases_left_out_with_their_reasons(conn, build, impacted):
    chosen, other = build.test_case(requirement_ids=["REQ-004"]), build.test_case(requirement_ids=["REQ-005"])
    elsewhere = build.test_case(requirement_ids=["REQ-001"])  # needs no decision, but may be listed
    retired = build.test_case(requirement_ids=["REQ-001"])
    design.retire_test_case(conn, retired, reason="obsolete", retired_by="fake/model")
    left_out = [
        {"test_case_id": retired, "reason": "Retired."},
        {"test_case_id": other, "reason": "Covered by a slower end-to-end test."},
        {"test_case_id": elsewhere, "reason": "REQ-001 is not impacted."},
    ]
    suite_id = save(conn, build, selected(chosen), left_out)
    stored = [tuple(row) for row in design.suite_left_out(conn, suite_id)]
    assert stored == sorted((entry["test_case_id"], entry["reason"]) for entry in left_out)
    assert [row["id"] for row in design.suite_test_cases(conn, suite_id)] == [chosen]
    assert design.uncovered_requirements(conn, suite_id) == ["REQ-005"]  # a test case left out covers nothing


def test_an_unknown_test_case_in_left_out_is_not_found(conn, build, impacted):
    assert refused(conn, build, [], left("TC-999")) == "INV-13: test case 'TC-999' does not exist"


def test_a_test_case_repeated_in_left_out_is_refused(conn, build, impacted):
    chosen = build.test_case(requirement_ids=["REQ-004"])
    assert f"repeated test cases in left_out: {chosen}" in refused(conn, build, [], left(chosen, chosen))


# The test cases whose verdict differs between the full runs of the two versions (mcp-tools.md, save_suite)


def full_run(conn, build, role, results: dict, status="completed", scope="all"):
    """A run on the commit of the role, with one execution per test case: a result, a result and its reruns, or
    ``"blocked"``."""
    run_id = build.run(role=role, scope=scope)
    for test_case_id, result in results.items():
        if result == "blocked":
            execution.record_test_execution(
                conn, run_id=run_id, test_case_id=test_case_id, status="blocked", reason="not_reported"
            )
        else:
            build.execute(run_id, test_case_id, *result.split("+"))
    execution.finish_run(conn, run_id, status=status, exit_code=0 if status == "completed" else None)
    return run_id


def test_a_test_case_whose_verdict_changed_between_the_full_runs_must_be_decided(conn, build, impacted):
    case = build.test_case(requirement_ids=["REQ-001"])  # REQ-001 is not impacted
    base = full_run(conn, build, "base", {case: "passed"})
    candidate = full_run(conn, build, "candidate", {case: "failed"})
    assert refused(conn, build, [], []) == (
        "invalid_argument: test cases whose verdict differs between the latest full runs of the baseline and the"
        f" candidate are in neither items nor left_out: {case} (passed in {base} on the baseline, failed in"
        f" {candidate} on the candidate); select each one or add it to left_out with a reason"
    )
    suite_id = save(conn, build, [], left(case, reason="Not selected."))
    assert [tuple(row) for row in design.suite_left_out(conn, suite_id)] == [(case, "Not selected.")]


def test_a_test_case_that_is_traced_and_changed_is_named_with_both_evidences(conn, build, impacted):
    case = build.test_case(requirement_ids=["REQ-005"])
    base = full_run(conn, build, "base", {case: "error"})
    candidate = full_run(conn, build, "candidate", {case: "passed"})
    message = refused(conn, build, [], [])
    assert f"neither items nor left_out: {case} (REQ-005);" in message
    assert f"{case} (error in {base} on the baseline, passed in {candidate} on the candidate)" in message
    save(conn, build, selected(case), [])


@pytest.mark.parametrize("missing", ["base", "candidate"])
def test_no_decision_is_required_without_a_completed_full_run_on_both_commits(conn, build, impacted, missing):
    case = build.test_case(requirement_ids=["REQ-001"])
    verdicts = {"base": "passed", "candidate": "failed"}
    present = "candidate" if missing == "base" else "base"
    full_run(conn, build, present, {case: verdicts[present]})
    full_run(conn, build, missing, {case: verdicts[missing]}, scope="selected")  # not a full run
    full_run(conn, build, missing, {case: verdicts[missing]}, status="error")  # not completed
    assert design.verdict_changes(conn, BASE_COMMIT, CANDIDATE_COMMIT) == {}
    save(conn, build, [], [])


def test_the_latest_full_runs_decide_and_a_flaky_execution_is_a_failure(conn, build, impacted):
    flaky, fixed = build.test_case(requirement_ids=["REQ-001"]), build.test_case(requirement_ids=["REQ-001"])
    full_run(conn, build, "base", {flaky: "passed", fixed: "passed"})
    base = full_run(conn, build, "base", {flaky: "passed", fixed: "failed"})  # the latest one decides
    candidate = full_run(conn, build, "candidate", {flaky: "failed+passed", fixed: "failed"})
    assert design.verdict_changes(conn, BASE_COMMIT, CANDIDATE_COMMIT) == {flaky: (base, "passed", candidate, "failed")}


def test_retired_unexecuted_and_both_failing_test_cases_need_no_decision(conn, build, impacted):
    retired, blocked, absent, failing = (build.test_case(requirement_ids=["REQ-001"]) for _ in range(4))
    full_run(conn, build, "base", {retired: "passed", blocked: "passed", absent: "passed", failing: "failed"})
    full_run(conn, build, "candidate", {retired: "failed", blocked: "blocked", failing: "error"})
    design.retire_test_case(conn, retired, reason="obsolete", retired_by="fake/model")
    assert design.verdict_changes(conn, BASE_COMMIT, CANDIDATE_COMMIT) == {}
    save(conn, build, [], [])
