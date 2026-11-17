"""Defects in the data layer: links, closing by the user, and closing by a run that verifies the fix (INV-14,
mcp-tools.md ``test_runner.run_tests``, Closing defects)."""

import pytest
from fixtures.memory_records import count_rows

from retroagent.memory import execution, interpretation
from retroagent.memory.errors import InvariantViolation


def defect(conn, *execution_ids, severity="high"):
    return interpretation.add_defect(conn, title="wrong total", severity=severity, execution_ids=list(execution_ids))


def completed(build, role="candidate", **results):
    """A completed run with one execution per test case; a value is the result and the reruns."""
    run_id = build.run(role=role)
    for test_case_id, outcome in results.items():
        build.execute(run_id, test_case_id, *outcome.split())
    execution.finish_run(build.conn, run_id, status="completed", exit_code=0)
    return run_id


def test_a_defect_needs_distinct_executions(conn, build):
    _, _, failed = build.failed_execution()
    before = count_rows(conn)
    with pytest.raises(InvariantViolation, match="invalid_argument: execution .* is listed twice"):
        defect(conn, failed, failed)
    with pytest.raises(InvariantViolation, match="invalid_argument: a defect is linked to at least one execution"):
        defect(conn)
    assert count_rows(conn) == before


def test_link_more_executions_to_an_open_defect(conn, build):
    run_id, case, failed = build.failed_execution()
    defect_id = defect(conn, failed)
    later = build.execute(build.run(), case, "error")
    passed = build.execute(run_id, build.test_case(), "passed")
    before = count_rows(conn)
    with pytest.raises(InvariantViolation, match=f"invalid_state: execution {failed} is already linked to {defect_id}"):
        interpretation.link_executions(conn, defect_id, [later, failed])
    with pytest.raises(InvariantViolation, match="INV-08"):
        interpretation.link_executions(conn, defect_id, [later, passed])
    with pytest.raises(InvariantViolation, match="INV-13"):
        interpretation.link_executions(conn, defect_id, [later, 9999])
    with pytest.raises(InvariantViolation, match="INV-13"):
        interpretation.link_executions(conn, "DEF-999", [later])
    with pytest.raises(InvariantViolation, match="listed twice"):
        interpretation.link_executions(conn, defect_id, [later, later])
    assert count_rows(conn) == before  # nothing of a refused call is written
    interpretation.link_executions(conn, defect_id, [later])
    assert [row["execution_id"] for row in interpretation.linked_executions(conn, defect_id)] == [failed, later]

    interpretation.close_defect(conn, defect_id, closed_by="user", close_reason="obsolete")
    with pytest.raises(InvariantViolation, match=f"invalid_state: {defect_id} is already closed"):
        interpretation.link_executions(conn, defect_id, [build.execute(build.run(), case, "failed")])


def test_the_user_closes_an_open_defect_once(conn, build):
    _, _, failed = build.failed_execution()
    defect_id = defect(conn, failed)
    interpretation.close_defect(conn, defect_id, closed_by="user", close_reason="fixed outside the tested scope")
    row = interpretation.get_defect(conn, defect_id)
    assert (row["status"], row["closed_by"], row["closed_run_id"], row["close_reason"]) == (
        "closed",
        "user",
        None,
        "fixed outside the tested scope",
    )
    with pytest.raises(InvariantViolation, match=f"invalid_state: {defect_id} is already closed"):
        interpretation.close_defect(conn, defect_id, closed_by="user", close_reason="again")
    assert interpretation.get_defect(conn, defect_id)["close_reason"] == "fixed outside the tested scope"
    with pytest.raises(InvariantViolation, match="INV-13"):
        interpretation.close_defect(conn, "DEF-999", closed_by="user", close_reason="x")


def test_a_completed_run_against_the_candidate_closes_a_defect_whose_test_cases_all_passed(conn, build):
    first, second = build.test_case(), build.test_case()
    detected = completed(build, **{first: "failed", second: "failed"})
    both = [row["id"] for row in execution.list_executions(conn, detected)]
    fixed = defect(conn, *both)  # linked to both test cases
    run_id = completed(build, **{first: "passed", second: "passed"})
    assert interpretation.close_defects_verified_by(conn, run_id) == [fixed]
    row = interpretation.get_defect(conn, fixed)
    assert (row["status"], row["closed_by"], row["closed_run_id"]) == ("closed", "run", run_id)
    assert row["close_reason"] == f"Every linked test case passed in {run_id}: {first}, {second}."
    assert interpretation.defects_closed_by(conn, run_id) == [fixed]
    assert interpretation.close_defects_verified_by(conn, run_id) == []  # a closed defect is not closed again


@pytest.mark.parametrize(
    "second_outcome",
    [
        "failed",  # one of its test cases failed
        "failed passed passed",  # flaky: the result is the first attempt
        "error",
        None,  # one of its test cases is not in the run
    ],
)
def test_a_defect_stays_open_unless_every_linked_test_case_passed(conn, build, second_outcome):
    first, second = build.test_case(), build.test_case()
    detected = completed(build, **{first: "failed", second: "failed"})
    open_defect = defect(conn, *(row["id"] for row in execution.list_executions(conn, detected)))
    results = {first: "passed"} | ({second: second_outcome} if second_outcome else {})
    run_id = completed(build, **results)
    assert interpretation.close_defects_verified_by(conn, run_id) == []
    assert interpretation.get_defect(conn, open_defect)["status"] == "open"


def test_a_blocked_execution_does_not_verify_the_fix(conn, build):
    case = build.test_case()
    _, failed = build.finished_run(role="candidate", test_case_id=case, result="failed")
    open_defect = defect(conn, failed)
    run_id = build.run(junit=False)
    execution.record_test_execution(conn, run_id=run_id, test_case_id=case, status="blocked", reason="no_junit")
    execution.finish_run(conn, run_id, status="completed", exit_code=2)
    assert interpretation.close_defects_verified_by(conn, run_id) == []
    assert interpretation.get_defect(conn, open_defect)["status"] == "open"


def test_only_a_completed_run_against_the_candidate_closes_defects(conn, build):
    case = build.test_case()
    _, failed = build.finished_run(role="candidate", test_case_id=case, result="failed")
    open_defect = defect(conn, failed)
    base_run = completed(build, role="base", **{case: "passed"})
    assert interpretation.close_defects_verified_by(conn, base_run) == []
    running = build.run()
    build.execute(running, case, "passed")
    assert interpretation.close_defects_verified_by(conn, running) == []
    execution.finish_run(conn, running, status="interrupted", error="interrupted by the user")
    assert interpretation.close_defects_verified_by(conn, running) == []
    assert interpretation.get_defect(conn, open_defect)["status"] == "open"


def test_list_defects_by_status(conn, build):
    _, _, first = build.failed_execution()
    _, _, second = build.failed_execution()
    open_defect, closed_defect = defect(conn, first), defect(conn, second, severity="low")
    interpretation.close_defect(conn, closed_defect, closed_by="user", close_reason="obsolete")
    assert [row["id"] for row in interpretation.list_defects(conn)] == [open_defect, closed_defect]
    assert [row["id"] for row in interpretation.list_defects(conn, "open")] == [open_defect]
    assert [row["id"] for row in interpretation.list_defects(conn, "closed")] == [closed_defect]
