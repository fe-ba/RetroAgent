"""SC-07: a result needs evidence. A designed test case cannot get an execution, through a command, the runner or
the data layer, and it shows as designed in /status. Nothing here runs a test command."""

import inspect
import sqlite3
from dataclasses import fields

import pytest
from fixtures.example_project import example_project, start

from retroagent.memory import connect, design, execution
from retroagent.runtime import commands
from retroagent.servers.test_runner import runner

# Parameter names that would let a caller give a result, a status or attempts instead of a run producing them.
RESULT_NAMES = {"result", "results", "status", "outcome", "attempts", "attempt", "passed", "failed", "executions"}


@pytest.fixture
def shop(tmp_path_factory, pip_cache):
    with example_project(tmp_path_factory, pip_cache) as path:
        conn = connect(path)
        designed = design.add_test_case(conn, title="Quantity above stock", priority="high", designed_by="user")
        conn.close()
        yield path, designed


def executions_of(path, test_case_id):
    conn = connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM test_execution WHERE test_case_id = ?", (test_case_id,)).fetchone()[0]
    finally:
        conn.close()


def test_no_command_and_no_runner_function_accepts_a_result():
    functions = [f for _, f in inspect.getmembers(commands, inspect.isfunction) if f.__module__ == commands.__name__]
    functions.append(runner.run_tests)
    assert {f.__name__ for f in functions} >= {"run", "status", "history", "parse", "run_tests"}
    for function in functions:
        assert not set(inspect.signature(function).parameters) & RESULT_NAMES, function.__name__
    assert not {field.name for field in fields(commands.Command)} & RESULT_NAMES


def test_run_refuses_a_designed_test_case_and_stores_nothing(shop):
    path, designed = shop
    with start(path, trust_commands=True) as session:
        outcome = commands.run(session, [designed], "both")
        assert outcome.runs == []
        assert (outcome.error.code, outcome.error.message) == (
            "invalid_state",
            "none of the selected test cases is implemented and active",
        )
        assert session.conn.execute("SELECT COUNT(*) FROM run").fetchone()[0] == 0
        call = session.conn.execute("SELECT tool, outcome, arguments FROM tool_call").fetchall()
        assert [tuple(c) for c in call] == [("run_tests", "error", f'{{"version": "base", "scope": "selected", '
                                                                    f'"test_case_ids": ["{designed}"]}}')]  # fmt: skip
    assert executions_of(path, designed) == 0


def test_the_data_layer_refuses_an_execution_of_a_designed_test_case(shop):
    path, designed = shop
    with start(path) as session:
        conn = session.conn
        run_id = execution.start_run(
            conn, version_role="candidate", ref="v1.1", commit="0" * 40, scope="all", command="-", session_id=session.id
        )
        execution.set_junit_path(conn, run_id, f".retro/runs/{run_id}/junit-1.xml")
        # INV-06: a designed test case gets no execution at all, whatever its status and result.
        for status, result, attempts in (
            ("executed", "passed", [{"number": 1, "result": "passed"}]),
            ("blocked", None, None),
            ("skipped", None, None),
        ):
            with pytest.raises(sqlite3.IntegrityError, match="INV-06"):
                execution.record_test_execution(
                    conn, run_id=run_id, test_case_id=designed, status=status, result=result, attempts=attempts
                )
        # INV-01: even for an implemented test case, a result exists only with status executed.
        implemented = design.add_project_suite_test_case(
            conn, test_id="tests.test_cart::test_cart_total", implementation="tests/test_cart.py::test_cart_total"
        )
        for status in ("blocked", "skipped"):
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                execution.record_test_execution(
                    conn, run_id=run_id, test_case_id=implemented, status=status, result="passed", reason="-"
                )
        execution.finish_run(conn, run_id, status="error", error="test: no evidence")
        assert execution.list_executions(conn, run_id) == []
    assert executions_of(path, designed) == 0


def test_status_shows_the_test_case_as_designed(shop):
    path, designed = shop
    with start(path) as session:
        status = commands.status(session)
    assert status.test_cases == {"designed": 1, "implemented": 0}
    assert status.latest_run is None
    assert executions_of(path, designed) == 0
