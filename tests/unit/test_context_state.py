"""The state message: the session state and the digest of project memory, for the reference scenario (snapshot)
and for memory in other states of the cycle."""

import datetime
from pathlib import Path

import pytest
from fixtures import reference_scenario as ref
from fixtures.memory_records import BASE_COMMIT, CANDIDATE_COMMIT

from retroagent.context.state import CycleStep, Digest, SessionState, Version, read_digest, state_message
from retroagent.memory import impact
from retroagent.metrics import Thresholds, evaluate

SNAPSHOT = Path(__file__).parent / "snapshots" / "state_message.md"
EMPTY = Digest(None, None, None, None, None, dict.fromkeys(("critical", "high", "medium", "low"), 0), None)


BASE = Version("v1.0", ref.BASE_COMMIT)
CANDIDATE = Version("v1.1", ref.CANDIDATE_COMMIT)


def session(base=BASE, candidate=CANDIDATE, **changes):
    values = dict(
        date=datetime.date(2026, 11, 19),
        project_name="shop-api",
        project_path="/work/shop-api",
        base=base,
        candidate=candidate,
        mode="default",
        permissions={"run_tests": "ask", "write_tests": "ask", "start_service": "ask"},
        commands_approved=False,
        model="google/gemini-3.1-flash-lite",
        language="en",
    )
    values.update(changes)
    return SessionState(**values)


def reference_state_message(conn) -> str:
    ref.load_reference_scenario(conn)
    evaluate(conn, ref.CANDIDATE_COMMIT, thresholds=Thresholds(min_pass_rate=ref.MIN_PASS_RATE))
    return state_message(session(), read_digest(conn, ref.BASE_COMMIT, ref.CANDIDATE_COMMIT)).content


def lines(message) -> dict[str, str]:
    body = message.content.splitlines()
    return dict(line.split(": ", 1) for line in body[3:-1] if ": " in line)


def test_reference_scenario_matches_the_snapshot(conn):
    assert reference_state_message(conn).encode("utf-8") == SNAPSHOT.read_bytes()


def test_same_memory_and_session_give_the_same_bytes(conn):
    ref.load_reference_scenario(conn)
    digest = read_digest(conn, ref.BASE_COMMIT, ref.CANDIDATE_COMMIT)
    first = state_message(session(), digest)
    again = state_message(session(), read_digest(conn, ref.BASE_COMMIT, ref.CANDIDATE_COMMIT))
    assert first == again
    assert first.role == "user"
    assert first.content.startswith("<session-state>\nWritten by the runtime of RetroAgent, not by the user.")
    assert first.content.endswith("\n</session-state>")


def test_empty_memory(conn):
    message = state_message(session(), read_digest(conn, BASE_COMMIT, CANDIDATE_COMMIT))
    fields = lines(message)
    for field in ("Analysis", "Current suite", "Runs", "Triage", "Evaluation"):
        assert fields[field] == "none"
    assert fields["Defects"] == "open: 0 critical, 0 high, 0 medium, 0 low"


def test_versions_not_set(build):
    build.failed_execution()
    message = state_message(session(base=None, candidate=None), read_digest(build.conn, None, None))
    fields = lines(message)
    assert fields["Versions"] == "not set"
    for field in ("Analysis", "Current suite", "Runs", "Triage", "Evaluation"):
        assert fields[field] == "none"


def test_only_the_baseline_set(build):
    run_id, _ = build.finished_run(role="base", test_case_id=build.test_case(), result="passed")
    digest = read_digest(build.conn, BASE_COMMIT, None)
    fields = lines(state_message(session(candidate=None), digest))
    assert fields["Versions"] == f"base v1.0 ({ref.BASE_COMMIT[:7]}), candidate not set"
    assert fields["Analysis"] == "none"
    assert fields["Runs"] == f"base {run_id} (all, completed): 1 passed, 0 failed, 0 error, 0 blocked; candidate none"
    assert fields["Triage"] == "none"


def test_analysis_without_impact_and_without_suite(build):
    digest = read_digest(build.conn, BASE_COMMIT, CANDIDATE_COMMIT)
    fields = lines(state_message(session(), digest))
    assert (
        fields["Analysis"] == f"ID {build.analysis_id}, 1 changed files, impact not recorded, 0 impacted requirements"
    )
    assert fields["Current suite"] == "none"


def test_analysis_with_impact_and_a_suite_with_a_designed_test_case(build):
    build.requirement("REQ-001")
    impact.record_impact(
        build.conn,
        build.analysis_id,
        modules=[{"module": "cart", "files": ["app/cart.py"], "risk_level": "high", "reason": "Totals"}],
        requirements=[{"requirement_id": "REQ-001", "reason": "Totals"}],
    )
    suite_id = build.suite(build.test_case(), build.test_case(implemented=False))
    fields = lines(state_message(session(), read_digest(build.conn, BASE_COMMIT, CANDIDATE_COMMIT)))
    assert fields["Analysis"] == f"ID {build.analysis_id}, 1 changed files, impact recorded, 1 impacted requirements"
    assert fields["Current suite"] == f"ID {suite_id}, 2 test cases, 1 designed only"


def test_failed_execution_without_triage(build):
    run_id, _, _ = build.failed_execution()
    fields = lines(state_message(session(), read_digest(build.conn, BASE_COMMIT, CANDIDATE_COMMIT)))
    assert fields["Runs"] == f"base none; candidate {run_id} (all, running): 0 passed, 1 failed, 0 error, 0 blocked"
    assert fields["Triage"] == f"{run_id} has 1 failed or error executions without triage"


def test_cycle_step_and_session_values():
    message = state_message(
        session(
            cycle_step=CycleStep("select", 3, 8),
            mode="auto",
            permissions={"run_tests": "allow", "write_tests": "deny", "start_service": "ask"},
            commands_approved=True,
        ),
        EMPTY,
    )
    fields = lines(message)
    assert fields["Cycle step"] == "select (3 of 8). Do only this step, then end the turn."
    assert fields["Mode"] == "auto"
    assert fields["Permissions"] == "run_tests allow, write_tests deny, start_service ask"
    assert fields["Project commands"] == "approved"
    keys = list(fields)
    assert keys.index("Project commands") < keys.index("Cycle step") < keys.index("Model")


@pytest.mark.parametrize("missing", ["run_tests", "write_tests", "start_service"])
def test_every_permission_is_required(missing):
    permissions = {"run_tests": "ask", "write_tests": "ask", "start_service": "ask"}
    del permissions[missing]
    with pytest.raises(KeyError):
        state_message(session(permissions=permissions), EMPTY)
