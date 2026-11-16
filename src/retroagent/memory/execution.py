"""Execution: tables ``run``, ``test_execution`` and ``attempt``.

The test runner is the only caller of ``record_test_execution``, and only with values parsed from the run's
JUnit XML or with the blocking reason it observed (INV-03). The data layer cannot check that; the tests of the
invariants call it with plain values to prove the constraints.
"""

import sqlite3

from retroagent.memory.db import require_exists, transaction, utc_now
from retroagent.memory.errors import InvariantViolation
from retroagent.memory.ids import next_id


def start_run(
    conn: sqlite3.Connection,
    *,
    version_role: str,
    ref: str,
    commit: str,
    scope: str,
    command: str,
    session_id: int,
    suite_id: int | None = None,
) -> str:
    with transaction(conn):
        run_id = next_id(conn, "RUN")
        conn.execute(
            'INSERT INTO run (id, version_role, ref, "commit", scope, suite_id, status, command, evidence_dir,'
            " session_id, started_at) VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)",
            (
                run_id,
                version_role,
                ref,
                commit,
                scope,
                suite_id,
                command,
                f".retro/runs/{run_id}/",
                session_id,
                utc_now(),
            ),
        )
    return run_id


def set_command(conn: sqlite3.Connection, run_id: str, command: str) -> None:
    """Store the test command of the first attempt once its placeholders, which name the run, are expanded."""
    with transaction(conn):
        conn.execute("UPDATE run SET command = ? WHERE id = ?", (command, run_id))


def set_junit_path(conn: sqlite3.Connection, run_id: str, junit_path: str) -> None:
    """Store the JUnit XML of a run that is still running. Needed before any execution can be ``executed``."""
    with transaction(conn):
        conn.execute("UPDATE run SET junit_path = ? WHERE id = ?", (junit_path, run_id))


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    exit_code: int | None = None,
    error: str | None = None,
) -> None:
    """Move a running run to ``completed``, ``error`` or ``interrupted``. After this the run never changes."""
    with transaction(conn):
        conn.execute(
            "UPDATE run SET status = ?, exit_code = ?, error = ?, ended_at = ? WHERE id = ?",
            (status, exit_code, error, utc_now(), run_id),
        )


def record_test_execution(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    test_case_id: str,
    status: str,
    result: str | None = None,
    reason: str | None = None,
    duration: float | None = None,
    test_revision: int | None = None,
    attempts: list[dict] | None = None,
) -> int:
    """Store one test execution with its attempts, in one transaction.

    An executed execution needs its attempts: the first gives the result (INV-04). Each attempt is
    ``{number, result, duration, failure_message}``. The number is the round of the run that produced it, so a
    round without a result for the test case leaves a gap; without ``number``, the position from 1 is used.
    """
    attempts = attempts or []
    with transaction(conn):
        require_exists(conn, "run", "id", run_id, "run")
        require_exists(conn, "test_case", "id", test_case_id, "test case")
        if status == "executed" and not attempts:
            raise InvariantViolation("INV-04: an executed test execution needs its first attempt")
        if status != "executed" and attempts:
            raise InvariantViolation("INV-04: only an executed test execution has attempts")
        cursor = conn.execute(
            "INSERT INTO test_execution (run_id, test_case_id, status, result, reason, duration, test_revision)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, test_case_id, status, result, reason, duration, test_revision),
        )
        execution_id = cursor.lastrowid
        for position, attempt in enumerate(attempts, start=1):
            conn.execute(
                "INSERT INTO attempt (execution_id, number, result, duration, failure_message) VALUES (?, ?, ?, ?, ?)",
                (
                    execution_id,
                    attempt.get("number", position),
                    attempt["result"],
                    attempt.get("duration"),
                    attempt.get("failure_message"),
                ),
            )
    return execution_id


def get_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()


def list_runs(conn: sqlite3.Connection, limit: int, *, session_id: int | None = None) -> list[sqlite3.Row]:
    """The latest runs first, of every session or of one."""
    sql, params = "SELECT * FROM run", []
    if session_id is not None:
        sql, params = sql + " WHERE session_id = ?", [session_id]
    return conn.execute(sql + " ORDER BY started_at DESC, id DESC LIMIT ?", (*params, limit)).fetchall()


def running_runs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM run WHERE status = 'running' ORDER BY id").fetchall()


# Counts of the executions of a run: by status, then by result.
COUNTS = ("executed", "blocked", "skipped", "passed", "failed", "error")


def execution_counts(conn: sqlite3.Connection, run_id: str) -> dict[str, int]:
    counts = dict.fromkeys(COUNTS, 0)
    for row in conn.execute(
        "SELECT status, result, COUNT(*) AS n FROM test_execution WHERE run_id = ? GROUP BY status, result", (run_id,)
    ):
        counts[row["status"]] += row["n"]
        if row["result"]:
            counts[row["result"]] += row["n"]
    return counts


def list_executions(conn: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM test_execution WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()


def list_attempts(conn: sqlite3.Connection, execution_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM attempt WHERE execution_id = ? ORDER BY number", (execution_id,)).fetchall()


def is_flaky(conn: sqlite3.Connection, execution_id: int) -> bool:
    """A test execution is flaky when at least one of its reruns passed. Computed, not stored."""
    row = conn.execute(
        "SELECT 1 FROM attempt WHERE execution_id = ? AND number > 1 AND result = 'passed' LIMIT 1", (execution_id,)
    ).fetchone()
    return row is not None
