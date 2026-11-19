"""One test per invariant of spec/data-model.md that the data layer enforces. Each shows the refused write
and the allowed one. INV-03 and INV-14 are tool contracts, tested through the servers and the runtime; the git check
of the ``expected_change`` evidence of INV-15 is given to the data layer as ``change_applies`` and tested with git in
``tests/integration/test_mcp_triage.py``."""

import inspect
import sqlite3

import pytest
from fixtures.memory_records import BASE_COMMIT, CANDIDATE_COMMIT, count_rows, no_removal, populate_every_table

from retroagent.memory import design, execution, impact, interpretation, reporting, requirements
from retroagent.memory.errors import InvariantViolation


def insert_execution(conn, run_id, test_case_id, status, result=None, reason=None):
    return conn.execute(
        "INSERT INTO test_execution (run_id, test_case_id, status, result, reason) VALUES (?, ?, ?, ?, ?)",
        (run_id, test_case_id, status, result, reason),
    ).lastrowid


def test_inv_01_result_exists_only_when_executed(conn, build):
    run_id = build.run()
    first, second, third = build.test_case(), build.test_case(), build.test_case()
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        insert_execution(conn, run_id, first, "executed")  # executed without a result
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        insert_execution(conn, run_id, first, "blocked", "failed", "no_junit")  # blocked with a result
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        insert_execution(conn, run_id, first, "skipped", "passed", "not supported")
    insert_execution(conn, run_id, first, "executed", "passed")
    insert_execution(conn, run_id, second, "blocked", reason="no_junit")
    insert_execution(conn, run_id, third, "skipped", reason="not supported on this platform")


def test_inv_02_executed_needs_run_with_junit(conn, build):
    test_case_id = build.test_case()
    without_junit = build.run(junit=False)
    with pytest.raises(sqlite3.IntegrityError, match="INV-02"):
        insert_execution(conn, without_junit, test_case_id, "executed", "passed")
    insert_execution(conn, without_junit, test_case_id, "blocked", reason="no_junit")  # no evidence needed to block
    with_junit = build.run()
    insert_execution(conn, with_junit, test_case_id, "executed", "passed")


def test_inv_04_first_attempt_gives_the_result(conn, build):
    run_id = build.run()
    first, second, third = build.test_case(), build.test_case(), build.test_case()
    # allowed: failed, then passed on a rerun. The result is the first attempt: a flaky execution is a failure.
    flaky = build.execute(run_id, first, "failed", "passed")
    assert conn.execute("SELECT result FROM test_execution WHERE id = ?", (flaky,)).fetchone()[0] == "failed"
    assert execution.is_flaky(conn, flaky)
    # failed, error, failed: the reruns have the same verdict, so it is not flaky
    same_verdict = build.execute(run_id, build.test_case(), "failed", "error", "failed")
    assert not execution.is_flaky(conn, same_verdict)
    # refused: the first attempt does not match the result
    mismatch = insert_execution(conn, run_id, second, "executed", "passed")
    with pytest.raises(sqlite3.IntegrityError, match="INV-04"):
        conn.execute("INSERT INTO attempt (execution_id, number, result) VALUES (?, 1, 'failed')", (mismatch,))
    # refused: a rerun after a pass
    passed = build.execute(run_id, third, "passed")
    with pytest.raises(sqlite3.IntegrityError, match="INV-04"):
        conn.execute("INSERT INTO attempt (execution_id, number, result) VALUES (?, 2, 'failed')", (passed,))
    # refused: an executed execution without attempts, and attempts for an execution that did not run
    with pytest.raises(InvariantViolation, match="INV-04"):
        execution.record_test_execution(
            conn, run_id=build.run(), test_case_id=first, status="executed", result="passed"
        )
    blocked = insert_execution(conn, build.run(), first, "blocked", reason="timeout")
    with pytest.raises(sqlite3.IntegrityError, match="INV-04"):
        conn.execute("INSERT INTO attempt (execution_id, number, result) VALUES (?, 1, 'passed')", (blocked,))


def test_inv_04_attempt_numbers_are_rounds_and_may_leave_gaps(conn, build):
    run_id = build.run()
    gap = execution.record_test_execution(
        conn,
        run_id=run_id,
        test_case_id=build.test_case(),
        status="executed",
        result="failed",
        attempts=[{"number": 1, "result": "failed"}, {"number": 3, "result": "passed"}],
    )
    assert [a["number"] for a in execution.list_attempts(conn, gap)] == [1, 3]
    assert execution.is_flaky(conn, gap)
    # refused: an execution whose first round has no attempt
    with pytest.raises(sqlite3.IntegrityError, match="INV-04"):
        execution.record_test_execution(
            conn,
            run_id=run_id,
            test_case_id=build.test_case(),
            status="executed",
            result="failed",
            attempts=[{"number": 2, "result": "failed"}],
        )


def test_inv_05_status_matches_implementation_fields(conn, build):
    designed = build.test_case(implemented=False)
    implemented = build.test_case()
    row = conn.execute("SELECT * FROM test_case WHERE id = ?", (designed,)).fetchone()
    assert (row["implementation"], row["test_id"], row["revision"]) == (None, None, None)
    row = conn.execute("SELECT * FROM test_case WHERE id = ?", (implemented,)).fetchone()
    assert row["implementation"] and row["revision"] == 1
    for assignment in ("implementation = 'f.py::t'", "test_id = 'c::t'", "revision = 1"):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute(f"UPDATE test_case SET {assignment} WHERE id = ?", (designed,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE test_case SET implementation = NULL WHERE id = ?", (implemented,))


def test_inv_06_designed_test_case_has_no_executions(conn, build):
    run_id = build.run()
    designed = build.test_case(implemented=False)
    with pytest.raises(sqlite3.IntegrityError, match="INV-06"):
        insert_execution(conn, run_id, designed, "blocked", reason="not_reported")
    design.mark_implemented(conn, designed, "test_late.py::test_late")
    insert_execution(conn, run_id, designed, "blocked", reason="not_reported")


def test_inv_07_identifiers_are_sequential_and_never_reused(conn, build):
    first, second = build.test_case(), build.test_case()
    assert (first, second) == ("TC-001", "TC-002")
    assert build.run() == "RUN-0001"
    assert build.run() == "RUN-0002"
    # records are never deleted, so the next identifier is always past the last one
    third = build.test_case()
    assert third == "TC-003"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM test_case WHERE id = ?", (third,))
    assert build.test_case() == "TC-004"
    # a stored identifier cannot be taken again, and its format is checked
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute(
            "INSERT INTO test_case (id, title, priority, status, origin, created_at, updated_at)"
            " VALUES ('TC-001', 't', 'low', 'designed', 'designed', 't', 't')"
        )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO test_case (id, title, priority, status, origin, created_at, updated_at)"
            " VALUES ('TC-1', 't', 'low', 'designed', 'designed', 't', 't')"
        )
    # no creating call takes an identifier
    for function in (design.add_test_case, execution.start_run, interpretation.add_defect, reporting.add_report):
        assert "id" not in inspect.signature(function).parameters


def test_inv_08_triage_and_defect_link_need_failed_execution(conn, build):
    run_id = build.run()
    passed = build.execute(run_id, build.test_case(), "passed")
    failed = build.execute(run_id, build.test_case(), "failed")
    errored = build.execute(run_id, build.test_case(), "error")
    skipped = insert_execution(conn, run_id, build.test_case(), "skipped", reason="not supported")
    for execution_id in (passed, skipped):
        with pytest.raises(sqlite3.IntegrityError, match="INV-08"):
            conn.execute(
                "INSERT INTO triage (execution_id, classification, justification, triaged_by, created_at)"
                " VALUES (?, 'regression', 'x', 'm', 't')",
                (execution_id,),
            )
    for execution_id in (failed, errored):
        interpretation.add_triage(
            conn, execution_id=execution_id, classification="regression", justification="x", triaged_by="m"
        )
    defect_id = interpretation.add_defect(conn, title="d", severity="low", execution_ids=[failed])
    with pytest.raises(sqlite3.IntegrityError, match="INV-08"):
        conn.execute("INSERT INTO defect_execution (defect_id, execution_id) VALUES (?, ?)", (defect_id, passed))
    conn.execute("INSERT INTO defect_execution (defect_id, execution_id) VALUES (?, ?)", (defect_id, errored))
    with pytest.raises(InvariantViolation, match="INV-08"):
        interpretation.add_defect(conn, title="d", severity="low", execution_ids=[passed])


def test_inv_09_suite_run_executions_belong_to_the_suite(conn, build):
    inside, outside = build.test_case(), build.test_case()
    suite_id = build.suite(inside)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):  # a suite run has a suite
        conn.execute(
            'INSERT INTO run (id, version_role, ref, "commit", scope, status, command, evidence_dir, session_id,'
            " started_at) VALUES ('RUN-0099', 'base', 'r', 'c', 'suite', 'running', 'x', 'd', ?, 't')",
            (build.session_id,),
        )
    suite_run = build.run(scope="suite", suite_id=suite_id)
    with pytest.raises(sqlite3.IntegrityError, match="INV-09"):
        build.execute(suite_run, outside)
    build.execute(suite_run, inside)
    # other scopes take any test case
    build.execute(build.run(scope="selected"), outside)
    build.execute(build.run(scope="all"), outside)


def test_inv_10_closed_records_are_never_updated(conn, build):
    # a run that is running can change; once it is not running it never does
    run_id = build.run()
    failed_case = build.test_case()
    execution_id = build.execute(run_id, failed_case, "failed")
    execution.finish_run(conn, run_id, status="completed", exit_code=1)
    for statement in ("UPDATE run SET command = 'other' WHERE id = ?", "UPDATE run SET junit_path = NULL WHERE id = ?"):
        with pytest.raises(sqlite3.IntegrityError, match="INV-10"):
            conn.execute(statement, (run_id,))
    with pytest.raises(sqlite3.IntegrityError, match="INV-10"):
        execution.finish_run(conn, run_id, status="error")
    # no execution or attempt is added to a run that is not running
    with pytest.raises(sqlite3.IntegrityError, match="INV-10"):
        build.execute(run_id, build.test_case(), "passed")
    with pytest.raises(sqlite3.IntegrityError, match="INV-10"):
        conn.execute("INSERT INTO attempt (execution_id, number, result) VALUES (?, 2, 'passed')", (execution_id,))
    # executions, attempts, triage
    with pytest.raises(sqlite3.IntegrityError, match="INV-10"):
        conn.execute("UPDATE test_execution SET status = 'blocked', result = NULL WHERE id = ?", (execution_id,))
    with pytest.raises(sqlite3.IntegrityError, match="INV-10"):
        conn.execute("UPDATE attempt SET result = 'passed' WHERE execution_id = ?", (execution_id,))
    triage_id = interpretation.add_triage(
        conn, execution_id=execution_id, classification="regression", justification="x", triaged_by="m"
    )
    with pytest.raises(sqlite3.IntegrityError, match="INV-10"):
        conn.execute("UPDATE triage SET classification = 'environment' WHERE id = ?", (triage_id,))
    # the impact of an analysis is written once and never changes
    requirement_id = build.requirement()
    module = {"module": "cart", "files": ["app/cart.py"], "risk_level": "high", "reason": "changed"}
    other_requirement = build.requirement("REQ-002")
    impact.record_impact(
        conn,
        build.analysis_id,
        modules=[module],
        requirements=[{"requirement_id": requirement_id, "reason": "r"}],
        not_impacted=[{"requirement_id": other_requirement, "reason": "r"}],
        removal_applies=no_removal,
    )
    decided = {
        "requirements": [],
        "not_impacted": [{"requirement_id": r, "reason": "r"} for r in ("REQ-001", "REQ-002")],
    }
    with pytest.raises(InvariantViolation, match="INV-10"):
        impact.record_impact(conn, build.analysis_id, modules=[module], removal_applies=no_removal, **decided)
    with pytest.raises(sqlite3.IntegrityError, match="INV-10"):
        conn.execute("UPDATE analysis_module SET risk_level = 'low'")
    with pytest.raises(sqlite3.IntegrityError, match="INV-10"):
        conn.execute("UPDATE analysis_requirement SET reason = 'other'")
    with pytest.raises(sqlite3.IntegrityError, match="INV-10"):
        conn.execute("UPDATE analysis_requirement_not_impacted SET reason = 'other'")
    other_analysis = build.analysis()  # a corrected impact needs a new analysis
    impact.record_impact(conn, other_analysis, modules=[module], removal_applies=no_removal, **decided)
    # evaluations and rendered reports
    evaluation_id = reporting.add_evaluation(
        conn,
        run_id=run_id,
        thresholds={},
        metrics={},
        criteria=[],
        decision="do_not_release",
        decision_details={"reasons": [], "conditions": []},
        tool_version="0.1.0",
    )
    with pytest.raises(sqlite3.IntegrityError, match="INV-10"):
        conn.execute("UPDATE evaluation SET decision = 'release' WHERE id = ?", (evaluation_id,))
    report_id = reporting.add_report(conn, type="completion", model="m", evaluation_id=evaluation_id)
    conn.execute("UPDATE report SET model = 'other' WHERE id = ?", (report_id,))  # a draft can still change
    reporting.mark_rendered(conn, report_id, ["md"])
    with pytest.raises(sqlite3.IntegrityError, match="INV-10"):
        conn.execute("UPDATE report SET model = 'other' WHERE id = ?", (report_id,))


def test_inv_11_records_are_never_deleted(conn, build):
    populate_every_table(build)
    counts = count_rows(conn)
    assert len(counts) == 25 and all(counts.values()), counts  # every table has a row to delete
    for table in counts:
        with pytest.raises(sqlite3.IntegrityError, match="INV-11"):
            conn.execute(f"DELETE FROM {table}")  # for test_case_requirement, the name link refuses the statement
    assert count_rows(conn) == counts
    # The one exception: design links can be deleted, so that they are replaced; name links never are.
    links = "SELECT link FROM test_case_requirement ORDER BY link"
    assert [r[0] for r in conn.execute(links)] == ["design", "name"]
    with pytest.raises(sqlite3.IntegrityError, match="INV-11"):
        conn.execute("DELETE FROM test_case_requirement WHERE link = 'name'")
    conn.execute("DELETE FROM test_case_requirement WHERE link = 'design'")
    assert [r[0] for r in conn.execute(links)] == ["name"]


def test_defect_actual_is_the_first_line_or_the_result_without_a_message(conn, build):
    run_id = build.run()
    with_message = build.execute(run_id, build.test_case(), "failed")
    no_message = execution.record_test_execution(
        conn,
        run_id=run_id,
        test_case_id=build.test_case(),
        status="executed",
        result="error",
        attempts=[{"result": "error"}],
    )
    for execution_id in (with_message, no_message):  # a defect needs a product fault
        triage(conn, execution_id, "regression")
    first = interpretation.add_defect(conn, title="a", severity="low", execution_ids=[with_message])
    second = interpretation.add_defect(conn, title="b", severity="low", execution_ids=[no_message])
    assert interpretation.get_defect(conn, first)["actual"] == "failed line 1"
    assert interpretation.get_defect(conn, second)["actual"] == "error without a message"


def test_inv_12_defect_closing_fields(conn, build):
    _, _, execution_id = build.failed_execution()
    triage(conn, execution_id, "regression")  # a defect needs a product fault
    open_defect = interpretation.add_defect(conn, title="d", severity="high", execution_ids=[execution_id])
    row = interpretation.get_defect(conn, open_defect)
    assert row["status"] == "open" and row["closed_at"] is None and row["closed_by"] is None
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):  # closed without its fields
        conn.execute("UPDATE defect SET status = 'closed' WHERE id = ?", (open_defect,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):  # open with a closing field
        conn.execute("UPDATE defect SET close_reason = 'x' WHERE id = ?", (open_defect,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):  # closed by a run without the run
        interpretation.close_defect(conn, open_defect, closed_by="run", close_reason="verified")
    interpretation.close_defect(conn, open_defect, closed_by="user", close_reason="obsolete")
    assert interpretation.get_defect(conn, open_defect)["status"] == "closed"
    by_run = interpretation.add_defect(conn, title="e", severity="low", execution_ids=[execution_id])
    run_id = build.run()
    interpretation.close_defect(conn, by_run, closed_by="run", close_reason="passed in a run", closed_run_id=run_id)
    assert interpretation.get_defect(conn, by_run)["closed_run_id"] == run_id


def test_inv_13_failed_call_writes_nothing(conn, build):
    requirement_id = build.requirement()
    suite_id = build.suite()
    _, _, execution_id = build.failed_execution()
    module = {"module": "cart", "files": ["app/cart.py"], "risk_level": "high", "reason": "changed"}
    before = count_rows(conn)

    calls = [
        # the first module is valid, the second names a file that is not in the change set
        lambda: impact.record_impact(
            conn,
            build.analysis_id,
            modules=[module, {**module, "module": "x", "files": ["nope.py"]}],
            requirements=[],
            not_impacted=[{"requirement_id": requirement_id, "reason": "r"}],
            removal_applies=no_removal,
        ),
        # valid module, then a requirement that does not exist
        lambda: impact.record_impact(
            conn,
            build.analysis_id,
            modules=[module],
            requirements=[{"requirement_id": requirement_id, "reason": "r"}],
            not_impacted=[{"requirement_id": "REQ-404", "reason": "r"}],
            removal_applies=no_removal,
        ),
        lambda: design.add_test_case(
            conn, title="t", priority="low", designed_by="m", requirement_ids=[requirement_id, "REQ-404"]
        ),
        lambda: impact.add_risk(
            conn,
            description="d",
            level="low",
            analysis_id=build.analysis_id,
            requirement_ids=[requirement_id, "REQ-404"],
        ),
        lambda: design.add_to_suite(conn, suite_id, test_case_id="TC-404", position=1, selection_reason="r"),
        lambda: interpretation.add_defect(conn, title="d", severity="low", execution_ids=[execution_id, 999]),
        lambda: interpretation.add_triage(
            conn, execution_id=999, classification="regression", justification="x", triaged_by="m"
        ),
    ]
    for call in calls:
        with pytest.raises(InvariantViolation, match="INV-13"):
            call()
        assert count_rows(conn) == before
        assert not conn.in_transaction

    # the same calls with valid references work
    impact.record_impact(
        conn,
        build.analysis_id,
        modules=[module],
        requirements=[{"requirement_id": requirement_id, "reason": "r"}],
        not_impacted=[],
        removal_applies=no_removal,
    )
    assert count_rows(conn)["analysis_module"] == 1


def triage(conn, execution_id, classification, **options):
    return interpretation.add_triage(
        conn, execution_id=execution_id, classification=classification, justification="x", triaged_by="m", **options
    )


SESSION = {"base_commit": BASE_COMMIT, "candidate_commit": CANDIDATE_COMMIT}


def test_inv_15_judgments_need_no_evidence(conn, build):
    # environment and test_defect are judgments of the model
    _, _, execution_id = build.failed_execution()
    triage(conn, execution_id, "environment")
    triage(conn, execution_id, "test_defect", replace=True)
    assert interpretation.current_triage(conn, execution_id)["classification"] == "test_defect"


def test_inv_15_regression_is_accepted_when_the_baseline_never_executed_the_test_case(conn, build):
    case = build.test_case()
    build.finished_run(role="base", test_case_id=build.test_case(), result="failed")  # another test case failed
    candidate_failure = build.execute(build.run(), case, "failed")
    triage(conn, candidate_failure, "regression", **SESSION)
    assert interpretation.current_triage(conn, candidate_failure)["classification"] == "regression"


def test_inv_15_regression_is_accepted_without_session_versions(conn, build):
    # no session versions, no baseline to check: as for a test case the baseline never executed
    case = build.test_case()
    build.finished_run(role="base", test_case_id=case, result="failed")
    candidate_failure = build.execute(build.run(), case, "failed")
    triage(conn, candidate_failure, "regression")
    assert interpretation.current_triage(conn, candidate_failure)["classification"] == "regression"


def test_inv_15_regression_is_accepted_when_the_baseline_passed(conn, build):
    case = build.test_case()
    build.finished_run(role="base", test_case_id=case, result="failed")
    build.finished_run(role="base", test_case_id=case, result="passed")  # the latest baseline run passed
    candidate_failure = build.execute(build.run(), case, "failed")
    triage(conn, candidate_failure, "regression", **SESSION)
    assert interpretation.current_triage(conn, candidate_failure)["classification"] == "regression"


def test_inv_15_regression_is_refused_when_the_baseline_failed(conn, build):
    case = build.project_test()  # a generated one is a soft check
    build.finished_run(role="base", test_case_id=case, result="passed")
    baseline, _ = build.finished_run(role="base", test_case_id=case, result="error")  # the latest one did not pass
    candidate_failure = build.execute(build.run(), case, "failed")
    before = count_rows(conn)
    with pytest.raises(
        InvariantViolation,
        match=f"INV-15: regression needs {case} not to fail against the baseline, and its result was error in"
        f" {baseline}, .* that executed it: a failure that the baseline already had is pre_existing",
    ):
        triage(conn, candidate_failure, "regression", **SESSION)
    assert count_rows(conn) == before
    # the same execution is accepted as pre_existing
    triage(conn, candidate_failure, "pre_existing", **SESSION)
    # another baseline commit has no execution of the test case: regression is accepted there
    triage(conn, candidate_failure, "regression", base_commit="a" * 40, candidate_commit=CANDIDATE_COMMIT, replace=True)


def test_inv_15_flaky_needs_a_rerun_that_passed_or_history(conn, build):
    run_id, _, execution_id = build.failed_execution()
    with pytest.raises(InvariantViolation, match=r"INV-15: flaky needs .*\(attempts: failed\)"):
        triage(conn, execution_id, "flaky")
    triage(conn, build.execute(run_id, build.test_case(), "failed", "passed"), "flaky")
    # flaky from history: an earlier execution of the same test case on the same commit had another result
    history_case = build.test_case()
    build.execute(build.run(), history_case, "passed")
    triage(conn, build.execute(build.run(), history_case, "failed"), "flaky")

    # failed, error, failed is not flaky: the verdict is the same in every attempt
    same_verdict = build.execute(run_id, build.test_case(), "failed", "error", "failed")
    with pytest.raises(InvariantViolation, match="INV-15"):
        triage(conn, same_verdict, "flaky")
    # an earlier error does not justify flaky for a failed execution: both are 'not passed'
    error_then_failed = build.test_case()
    build.execute(build.run(), error_then_failed, "error")
    with pytest.raises(InvariantViolation, match="INV-15"):
        triage(conn, build.execute(build.run(), error_then_failed, "failed"), "flaky")
    # a pass on another commit is not history of this one
    other_commit = build.test_case()
    build.finished_run(role="base", test_case_id=other_commit, result="passed")
    with pytest.raises(InvariantViolation, match="INV-15"):
        triage(conn, build.execute(build.run(), other_commit, "failed"), "flaky")


def test_inv_15_pre_existing_needs_a_failure_in_the_latest_baseline_run(conn, build):
    case = build.project_test()  # a generated one is a soft check
    candidate_failure = build.execute(build.run(), case, "failed")
    with pytest.raises(InvariantViolation, match="INV-15: pre_existing needs the session versions"):
        triage(conn, candidate_failure, "pre_existing")
    with pytest.raises(InvariantViolation, match="INV-15: pre_existing needs a completed run on the baseline"):
        triage(conn, candidate_failure, "pre_existing", **SESSION)
    baseline, _ = build.finished_run(role="base", test_case_id=case, result="passed")
    with pytest.raises(InvariantViolation, match=f"INV-15: pre_existing needs {case} to fail .* passed in {baseline}"):
        triage(conn, candidate_failure, "pre_existing", **SESSION)
    build.finished_run(role="base", test_case_id=case, result="failed")  # the latest baseline run failed
    with pytest.raises(InvariantViolation, match="INV-15"):  # another baseline commit
        triage(conn, candidate_failure, "pre_existing", base_commit="a" * 40, candidate_commit=CANDIDATE_COMMIT)
    with pytest.raises(InvariantViolation, match="INV-15: .* a run against the candidate"):  # another candidate commit
        triage(conn, candidate_failure, "pre_existing", base_commit=BASE_COMMIT, candidate_commit="a" * 40)
    triage(conn, candidate_failure, "pre_existing", **SESSION)
    # a failure on the baseline itself is not "pre-existing"
    _, base_failure = build.finished_run(role="base", test_case_id=build.test_case(), result="failed")
    with pytest.raises(InvariantViolation, match="INV-15: .* a run against the candidate"):
        triage(conn, base_failure, "pre_existing", **SESSION)
    assert interpretation.current_triage(conn, candidate_failure)["classification"] == "pre_existing"
    assert CANDIDATE_COMMIT != BASE_COMMIT


def test_inv_15_expected_change_needs_a_documented_change_that_applies(conn, build):
    changed = build.requirement("REQ-001")
    requirements.add_requirement_change(conn, requirement_id=changed, version="v1.1", description="combined")
    unchanged = build.requirement("REQ-002")
    old_change = build.requirement("REQ-003")
    requirements.add_requirement_change(conn, requirement_id=old_change, version="v0.9", description="older")
    removed = requirements.add_requirement(
        conn, id="REQ-004", title="Gift wrap", description="Gift wrap.", source_file="docs/req.md", removed="v1.1"
    )

    def applies(version):
        return version == "v1.1"

    def failure(requirement_ids, role="candidate"):
        case = build.test_case(requirement_ids=requirement_ids)
        _, execution_id = build.finished_run(role=role, test_case_id=case, result="failed")
        return case, execution_id

    session = {**SESSION, "change_applies": applies}
    case, execution_id = failure([unchanged])
    with pytest.raises(
        InvariantViolation, match=f"INV-15: expected_change .*: {case} traces REQ-002, and it has no Changed or Removed"
    ):
        triage(conn, execution_id, "expected_change", **session)
    _, execution_id = failure([old_change])  # REQ-003 changed in v0.9, before the baseline
    with pytest.raises(InvariantViolation, match=r"its entries \(REQ-003 v0.9\) do not apply"):
        triage(conn, execution_id, "expected_change", **session)
    _, execution_id = failure([])
    with pytest.raises(InvariantViolation, match="traces none"):
        triage(conn, execution_id, "expected_change", **session)
    _, execution_id = failure([changed])
    with pytest.raises(InvariantViolation, match="INV-15: expected_change needs the session versions"):
        triage(conn, execution_id, "expected_change")
    triage(conn, execution_id, "expected_change", **session)
    _, execution_id = failure([unchanged, removed])  # a Removed entry applies as well
    triage(conn, execution_id, "expected_change", **session)
    _, base_failure = failure([changed], role="base")
    with pytest.raises(InvariantViolation, match="a run against the candidate"):
        triage(conn, base_failure, "expected_change", **session)


def test_a_triaged_execution_is_triaged_again_only_with_replace(conn, build):
    _, _, execution_id = build.failed_execution()
    first = triage(conn, execution_id, "regression")
    before = count_rows(conn)
    with pytest.raises(InvariantViolation, match="invalid_state: .* already triaged as regression; set replace"):
        triage(conn, execution_id, "environment")
    assert count_rows(conn) == before
    second = triage(conn, execution_id, "environment", replace=True)
    rows = conn.execute("SELECT id, classification FROM triage WHERE execution_id = ? ORDER BY id", (execution_id,))
    assert [tuple(row) for row in rows] == [(first, "regression"), (second, "environment")]
    assert interpretation.current_triage(conn, execution_id)["id"] == second
    assert interpretation.triage_count(conn, execution_id) == 2
    # replace on an execution without a triage is a first triage
    _, _, untriaged = build.failed_execution()
    triage(conn, untriaged, "regression", replace=True)
    assert interpretation.triage_count(conn, untriaged) == 1


def test_inv_16_retired_test_case_is_never_added_to_a_suite(conn, build):
    active, retired = build.test_case(), build.test_case()
    design.retire_test_case(conn, retired, reason="obsolete", retired_by="fake/model")
    suite_id = build.suite()
    design.add_to_suite(conn, suite_id, test_case_id=active, position=1, selection_reason="covers the change")
    before = count_rows(conn)
    with pytest.raises(InvariantViolation, match="INV-16"):
        design.add_to_suite(conn, suite_id, test_case_id=retired, position=2, selection_reason="again")
    assert count_rows(conn) == before
    row = design.get_test_case(conn, retired)
    assert row["retired_at"] and row["retire_reason"] == "obsolete" and row["retired_by"] == "fake/model"


def test_a_rewrite_changes_the_code_fields_with_the_revision_in_one_transaction(conn, build):
    """mcp-tools.md, ``test_runner.write_test``: the design fields that describe the code change with it; the others
    belong to ``memory.update_test_case``. A refused rewrite changes nothing."""
    build.requirement("REQ-001")
    build.requirement("REQ-002")
    test_case = build.test_case(implemented=False, requirement_ids=["REQ-001"])
    design.mark_implemented(conn, test_case, "test_a.py::test_req_001_a")
    fields = {"steps": ["Add 6 units"], "expected_result": "Refused with 409.", "requirement_ids": ["REQ-002"]}
    assert design.rewrite_generated_test(conn, test_case, "test_a.py::test_req_001_a", fields) == 2
    row = design.get_test_case(conn, test_case)
    assert (row["steps"], row["expected_result"]) == ('["Add 6 units"]', "Refused with 409.")
    assert [link["requirement_id"] for link in design.test_case_requirements(conn, test_case)] == ["REQ-002"]
    before = count_rows(conn)
    with pytest.raises(InvariantViolation, match="invalid_argument: title cannot change with the code"):
        design.rewrite_generated_test(conn, test_case, "test_a.py::test_req_001_a", {"title": "new"})
    with pytest.raises(InvariantViolation, match="INV-13"):
        design.rewrite_generated_test(conn, test_case, "test_a.py::test_req_001_a", {"requirement_ids": ["REQ-404"]})
    assert count_rows(conn) == before
    assert design.get_test_case(conn, test_case)["revision"] == 2


def test_a_retired_test_case_is_neither_implemented_nor_rewritten(conn, build):
    designed = build.test_case(implemented=False)
    implemented = build.test_case(implemented=True)
    for test_case in (designed, implemented):
        design.retire_test_case(conn, test_case, reason="obsolete", retired_by="fake/model")
    with pytest.raises(InvariantViolation, match="invalid_state: .* is retired"):
        design.mark_implemented(conn, designed, "test_r.py::test_r")
    with pytest.raises(InvariantViolation, match="invalid_state: .* is retired"):
        design.rewrite_generated_test(conn, implemented, design.get_test_case(conn, implemented)["implementation"])


def test_inv_17_generated_test_name_and_file_are_unique_and_kept(conn, build):
    first = build.test_case(implemented=False)
    second = build.test_case(implemented=False)
    design.mark_implemented(conn, first, "test_a.py::test_a")
    with pytest.raises(InvariantViolation, match="INV-17"):  # same file
        design.mark_implemented(conn, second, "test_a.py::test_b")
    with pytest.raises(InvariantViolation, match="INV-17"):  # same function name
        design.mark_implemented(conn, second, "test_b.py::test_a")
    design.mark_implemented(conn, second, "test_b.py::test_b")
    # a rewrite keeps both and increments the revision
    assert design.rewrite_generated_test(conn, first, "test_a.py::test_a") == 2
    assert design.rewrite_generated_test(conn, first, "test_a.py::test_a") == 3
    for changed in ("test_c.py::test_a", "test_a.py::test_c"):
        with pytest.raises(InvariantViolation, match="INV-17"):
            design.rewrite_generated_test(conn, first, changed)
    assert design.get_test_case(conn, first)["revision"] == 3
    # tests found in the project are not generated tests and do not take part
    design.add_project_suite_test_case(conn, test_id="tests.test_x::test_a", implementation="tests/test_x.py::test_a")
