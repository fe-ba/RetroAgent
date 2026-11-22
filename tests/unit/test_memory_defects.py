"""Defects in the data layer: links, closing by the user, and closing by a run that verifies the fix (INV-14,
mcp-tools.md ``test_runner.run_tests``, Closing defects)."""

import pytest
from fixtures.memory_records import count_rows

from retroagent.memory import execution, interpretation
from retroagent.memory.errors import InvariantViolation


def regression(conn, *execution_ids):
    """Triage each untriaged execution as ``regression``: a defect needs a product fault (mcp-tools.md)."""
    for execution_id in dict.fromkeys(execution_ids):
        if interpretation.current_triage(conn, execution_id) is None:
            interpretation.add_triage(
                conn, execution_id=execution_id, classification="regression", justification="x", triaged_by="m"
            )


def defect(conn, *execution_ids, severity="high"):
    regression(conn, *execution_ids)
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
    regression(conn, failed)
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
    regression(conn, later)
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


def test_a_defect_needs_every_execution_triaged_as_a_product_fault_and_names_each_one(conn, build):
    run_id, case, faulty = build.failed_execution()
    wrong_test = build.execute(run_id, build.test_case(), "failed")
    untriaged = build.execute(run_id, build.test_case(), "error")
    regression(conn, faulty)
    interpretation.add_triage(
        conn, execution_id=wrong_test, classification="test_defect", justification="x", triaged_by="m"
    )
    names = {
        execution_id: conn.execute("SELECT test_case_id FROM test_execution WHERE id = ?", (execution_id,)).fetchone()[
            0
        ]
        for execution_id in (wrong_test, untriaged)
    }
    message = (
        "invalid_state: a defect describes a fault of the product, so every execution needs a current triage"
        f" regression or pre_existing: execution {wrong_test} of {names[wrong_test]} (test_defect), execution"
        f" {untriaged} of {names[untriaged]} (not triaged); triage each one first"
    )
    before = count_rows(conn)
    with pytest.raises(InvariantViolation) as error:
        interpretation.add_defect(conn, title="t", severity="high", execution_ids=[faulty, wrong_test, untriaged])
    assert str(error.value) == message
    assert count_rows(conn) == before
    defect_id = interpretation.add_defect(conn, title="t", severity="high", execution_ids=[faulty])
    before = count_rows(conn)
    with pytest.raises(InvariantViolation) as error:
        interpretation.link_executions(conn, defect_id, [wrong_test, untriaged])
    assert str(error.value) == message
    assert count_rows(conn) == before


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


# A test case with an open defect gets no second one: the same failure is linked to that defect (mcp-tools.md,
# register_defect). No argument overrides it.


def has_open_defect(*named: str) -> str:
    return (
        f"a test case with an open defect gets no second one: {', '.join(named)}; link each one to its defect instead"
    )


def test_a_second_defect_for_a_test_case_with_an_open_defect_is_refused_and_names_it(conn, build):
    _, case, failed = build.failed_execution()
    open_defect = defect(conn, failed)
    again = build.execute(build.run(), case, "failed")
    regression(conn, again)
    before = count_rows(conn)
    with pytest.raises(InvariantViolation) as error:
        defect(conn, again)
    assert str(error.value) == "invalid_state: " + has_open_defect(f"execution {again} of {case} ({open_defect})")
    assert count_rows(conn) == before
    interpretation.link_executions(conn, open_defect, [again])  # the same failure goes to the open defect
    assert [row["execution_id"] for row in interpretation.linked_executions(conn, open_defect)] == [failed, again]


def test_after_the_open_defect_is_closed_a_new_defect_is_accepted(conn, build):
    _, case, failed = build.failed_execution()
    closed = defect(conn, failed)
    interpretation.close_defect(conn, closed, closed_by="user", close_reason="fixed outside the tested scope")
    again = build.execute(build.run(), case, "failed")
    new = defect(conn, again)
    assert new != closed and interpretation.get_defect(conn, new)["status"] == "open"


def test_a_call_with_one_refused_execution_is_refused_as_a_whole_and_names_every_refused_one(conn, build):
    _, case, failed = build.failed_execution()
    open_defect = defect(conn, failed)
    run_id = build.run()
    again = build.execute(run_id, case, "failed")
    allowed = build.execute(run_id, build.test_case(), "failed")
    untriaged = build.execute(run_id, build.test_case(), "error")
    regression(conn, again, allowed)
    untriaged_case = conn.execute("SELECT test_case_id FROM test_execution WHERE id = ?", (untriaged,)).fetchone()[0]
    before = count_rows(conn)
    with pytest.raises(InvariantViolation) as error:
        interpretation.add_defect(conn, title="t", severity="high", execution_ids=[allowed, again])
    assert str(error.value) == "invalid_state: " + has_open_defect(f"execution {again} of {case} ({open_defect})")
    with pytest.raises(InvariantViolation) as error:
        interpretation.add_defect(conn, title="t", severity="high", execution_ids=[allowed, again, untriaged])
    assert str(error.value) == (
        "invalid_state: a defect describes a fault of the product, so every execution needs a current triage"
        f" regression or pre_existing: execution {untriaged} of {untriaged_case} (not triaged); triage each one"
        f" first; {has_open_defect(f'execution {again} of {case} ({open_defect})')}"
    )
    assert count_rows(conn) == before
    assert interpretation.linked_test_cases(conn, open_defect) == [case]
