"""Fixtures of the data layer tests.

``Builder`` stores plain values through the data layer API. These are tests of constraints: they do not
produce evidence, and the values they store are not results of a real run (CLAUDE.md, ADR-0016).
"""

import itertools

import pytest

from retroagent.memory import connect, design, execution, impact, interpretation, reporting, requirements, sessions

BASE_COMMIT = "b" * 40
CANDIDATE_COMMIT = "c" * 40


class Builder:
    def __init__(self, conn):
        self.conn = conn
        self._numbers = itertools.count(1)
        self.session_id = sessions.start_session(conn, model="fake/model", interactive=False, result_char_limit=8000)
        self.analysis_id = self.analysis()

    def analysis(self, files=("app/cart.py",)):
        return impact.add_analysis(
            self.conn,
            session_id=self.session_id,
            base_ref="v1.0",
            base_commit=BASE_COMMIT,
            candidate_ref="v1.1",
            candidate_commit=CANDIDATE_COMMIT,
            files=[{"path": p, "change": "modified", "lines_added": 3, "lines_removed": 1} for p in files],
        )

    def requirement(self, id="REQ-001"):
        return requirements.add_requirement(
            self.conn, id=id, title="Cart total", description="The total is the sum.", source_file="docs/req.md"
        )

    def test_case(self, implemented=True, requirement_ids=None):
        number = next(self._numbers)
        test_case_id = design.add_test_case(
            self.conn,
            title=f"case {number}",
            priority="high",
            designed_by="fake/model",
            requirement_ids=requirement_ids,
        )
        if implemented:
            design.mark_implemented(self.conn, test_case_id, f".retro/tests/test_case_{number}.py::test_case_{number}")
        return test_case_id

    def suite(self, *test_case_ids):
        suite_id = design.add_suite(self.conn, analysis_id=self.analysis_id, session_id=self.session_id)
        for position, test_case_id in enumerate(test_case_ids, start=1):
            design.add_to_suite(
                self.conn, suite_id, test_case_id=test_case_id, position=position, selection_reason="covers the change"
            )
        return suite_id

    def run(self, *, role="candidate", scope="all", suite_id=None, junit=True):
        commit = CANDIDATE_COMMIT if role == "candidate" else BASE_COMMIT
        run_id = execution.start_run(
            self.conn,
            version_role=role,
            ref="v1.1" if role == "candidate" else "v1.0",
            commit=commit,
            scope=scope,
            command="pytest",
            session_id=self.session_id,
            suite_id=suite_id,
        )
        if junit:
            execution.set_junit_path(self.conn, run_id, f".retro/runs/{run_id}/junit.xml")
        return run_id

    def execute(self, run_id, test_case_id, result="passed", *results):
        """An executed test execution; ``results`` are the reruns."""
        attempts = [
            {"result": r, "duration": 0.1, "failure_message": f"{r} line 1\nline 2"} for r in (result, *results)
        ]
        return execution.record_test_execution(
            self.conn,
            run_id=run_id,
            test_case_id=test_case_id,
            status="executed",
            result=result,
            duration=0.1,
            attempts=attempts,
        )

    def finished_run(self, *, role, test_case_id, result):
        run_id = self.run(role=role)
        execution_id = self.execute(run_id, test_case_id, result)
        execution.finish_run(self.conn, run_id, status="completed", exit_code=0)
        return run_id, execution_id

    def failed_execution(self):
        test_case_id = self.test_case()
        run_id = self.run()
        return run_id, test_case_id, self.execute(run_id, test_case_id, "failed")


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path)
    yield connection
    connection.close()


@pytest.fixture
def build(conn):
    return Builder(conn)


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
