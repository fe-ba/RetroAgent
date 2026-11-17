"""The runtime and the servers write the same SQLite file (runtime.md, Robustness): while the runtime keeps its
connection open, with rows read and tool_call rows written through it, every write tool of the servers succeeds
without waiting for the busy timeout."""

import json
import time

import pytest
from fixtures.example_project import example_project
from fixtures.mcp_project import error_of, open_session

from retroagent.mcp_client import Client
from retroagent.memory import connect, requirements, sessions

BUSY_TIMEOUT = 5.0  # seconds: the default of Python's sqlite3, used by memory.connect
QUICK = 1.0

CONFIG = """project:
  requirements: [docs/requirements.md]
versions: {base: v1.0, candidate: v1.1}
tests:
  command: "printf '<testsuite><testcase classname=\\"t\\" name=\\"test_one\\"/></testsuite>' > {junit}"
"""

PRICING = {"module": "pricing", "files": ["src/shop/pricing.py"], "risk_level": "high", "reason": "r"}
EVERY = [{"requirement_id": f"REQ-00{n}", "reason": "r"} for n in range(1, 9)]  # not impacted
DESIGN = {"title": "t", "objective": "o", "priority": "high", "preconditions": [], "input_data": [], "steps": ["s"],
          "expected_result": "e", "requirement_ids": ["REQ-002"], "selection_reason": "r"}  # fmt: skip


@pytest.fixture
def project(tmp_path_factory, pip_cache):
    with example_project(tmp_path_factory, pip_cache) as path:
        (path / ".retro" / "config.yaml").write_text(CONFIG, encoding="utf-8")
        session_id = open_session(path)
        conn = connect(path)  # the connection of the runtime, open for the whole session
        with Client(path, session_id) as client:
            yield conn, session_id, client
        conn.close()


def dispatch(conn, session_id, client, server, tool, arguments) -> tuple[dict | Exception, float]:
    """What the turn does around a call: read, record, dispatch with no transaction open, record the outcome."""
    sessions.get_session(conn, session_id)
    requirements.list_requirements(conn)
    assert not conn.in_transaction
    started = time.monotonic()
    try:
        outcome = client.call(server, tool, arguments)
    except Exception as error:  # noqa: BLE001 - returned to the test
        outcome = error
    elapsed = time.monotonic() - started
    sessions.record_tool_call(
        conn,
        session_id=session_id,
        server=server,
        tool=tool,
        arguments=json.dumps(arguments),
        outcome="error" if isinstance(outcome, Exception) else "ok",
    )
    assert not conn.in_transaction
    return outcome, elapsed


def test_every_write_tool_succeeds_while_the_runtime_connection_is_open(project):
    conn, session_id, client = project
    calls = [
        ("memory", "sync_requirements", {}),
        ("git", "analyze_changes", {}),
        ("memory", "save_impact", {"analysis_id": 1, "modules": [PRICING], "requirements": [], "not_impacted": EVERY}),
        ("memory", "add_risk", {"description": "Shipping charged wrongly.", "level": "high"}),
        ("memory", "save_suite", {"analysis_id": 1, "items": []}),
        ("memory", "design_test_case", DESIGN),
        ("memory", "update_test_case", {"test_case_id": "TC-001", "fields": {"priority": "low"}}),
        ("memory", "retire_test_case", {"test_case_id": "TC-001", "reason": "Obsolete."}),
    ]  # fmt: skip
    for server, tool, arguments in calls:
        outcome, elapsed = dispatch(conn, session_id, client, server, tool, arguments)
        assert not isinstance(outcome, Exception), f"{tool}: {outcome}"
        assert elapsed < QUICK, f"{tool} took {elapsed:.2f} s"
    outcome, elapsed = dispatch(
        conn, session_id, client, "test_runner", "run_tests", {"version": "base", "scope": "all"}
    )
    assert not isinstance(outcome, Exception), outcome
    assert outcome["status"] == "completed" and outcome["counts"]["passed"] == 1
    assert elapsed < BUSY_TIMEOUT
    assert conn.execute("SELECT COUNT(*) FROM tool_call").fetchone()[0] == len(calls) + 1


def test_a_read_left_open_by_the_runtime_would_make_a_server_wait(project):
    # The control of the test above: the measure detects a wait. A statement that is not finished keeps a shared
    # lock, so a server cannot commit until the busy timeout ends.
    conn, session_id, client = project
    client.call("git", "analyze_changes")
    cursor = conn.execute("SELECT * FROM analysis_file")
    cursor.fetchone()
    started = time.monotonic()
    error = error_of(lambda: client.call("memory", "add_risk", {"description": "d", "level": "low"}))
    assert time.monotonic() - started >= BUSY_TIMEOUT - 0.5
    assert "locked" in error.message
    cursor.close()
    assert client.call("memory", "add_risk", {"description": "d", "level": "low"})["risk_id"] == "RSK-001"
