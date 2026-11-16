"""Shared values and helpers of the data layer tests: the commits of ``Builder`` and two whole-database helpers."""

from retroagent.memory import design, execution, impact, interpretation, reporting, requirements, sessions

BASE_COMMIT = "b" * 40
CANDIDATE_COMMIT = "c" * 40


def count_rows(conn):
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def populate_every_table(build):
    """One row in each of the 23 tables, through the API."""
    conn = build.conn
    requirement_id = build.requirement()
    requirements.add_requirement_change(conn, requirement_id=requirement_id, version="v1.1", description="changed")
    impact.record_impact(
        conn,
        build.analysis_id,
        modules=[{"module": "cart", "files": ["app/cart.py"], "risk_level": "high", "reason": "changed"}],
        requirements=[{"requirement_id": requirement_id, "reason": "total changed"}],
    )
    impact.add_risk(
        conn, description="rounding", level="medium", analysis_id=build.analysis_id, requirement_ids=[requirement_id]
    )
    test_case_id = build.test_case(requirement_ids=[requirement_id])  # a design link
    design.add_project_suite_test_case(  # a name link
        conn, test_id="tests.test_cart::test_req_001_total", implementation="tests/test_cart.py::test_req_001_total"
    )
    suite_id = build.suite(test_case_id)
    run_id = build.run(scope="suite", suite_id=suite_id)
    execution_id = build.execute(run_id, test_case_id, "failed")
    execution.finish_run(conn, run_id, status="completed", exit_code=1)
    interpretation.add_triage(
        conn, execution_id=execution_id, classification="regression", justification="x", triaged_by="fake/model"
    )
    interpretation.add_defect(conn, title="wrong total", severity="high", execution_ids=[execution_id])
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
    reporting.add_report(conn, type="completion", model="fake/model", evaluation_id=evaluation_id)
    sessions.record_tool_call(
        conn, session_id=build.session_id, server="memory", tool="x", arguments="{}", outcome="ok"
    )
