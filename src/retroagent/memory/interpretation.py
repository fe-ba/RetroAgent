"""Interpretation: tables ``triage``, ``defect`` and ``defect_execution``."""

import json
import sqlite3

from retroagent.memory.db import require_exists, transaction, utc_now
from retroagent.memory.errors import InvariantViolation
from retroagent.memory.execution import is_flaky
from retroagent.memory.ids import next_id


def _failed_execution(conn: sqlite3.Connection, execution_id: int) -> sqlite3.Row:
    row = conn.execute(
        'SELECT e.*, r.version_role, r."commit" AS run_commit FROM test_execution e JOIN run r ON r.id = e.run_id'
        " WHERE e.id = ?",
        (execution_id,),
    ).fetchone()
    if row is None:
        raise InvariantViolation(f"INV-13: execution {execution_id!r} does not exist")
    if row["result"] not in ("failed", "error"):
        raise InvariantViolation(f"INV-08: execution {execution_id} did not fail")
    return row


def _flaky_evidence(conn: sqlite3.Connection, execution: sqlite3.Row) -> bool:
    if is_flaky(conn, execution["id"]):
        return True
    different = conn.execute(
        'SELECT 1 FROM test_execution e JOIN run r ON r.id = e.run_id WHERE e.test_case_id = ? AND r."commit" = ?'
        " AND e.id < ? AND e.status = 'executed' AND e.result = 'passed' LIMIT 1",
        (execution["test_case_id"], execution["run_commit"], execution["id"]),
    ).fetchone()
    return different is not None


def _pre_existing_evidence(conn: sqlite3.Connection, execution: sqlite3.Row, base_commit: str | None) -> bool:
    if execution["version_role"] != "candidate" or base_commit is None:
        return False
    latest = conn.execute(
        "SELECT e.result FROM test_execution e JOIN run r ON r.id = e.run_id WHERE e.test_case_id = ?"
        " AND r.\"commit\" = ? AND r.status = 'completed' AND e.status = 'executed'"
        " ORDER BY r.started_at DESC, r.id DESC LIMIT 1",
        (execution["test_case_id"], base_commit),
    ).fetchone()
    return latest is not None and latest["result"] in ("failed", "error")


def add_triage(
    conn: sqlite3.Connection,
    *,
    execution_id: int,
    classification: str,
    justification: str,
    triaged_by: str,
    base_commit: str | None = None,
) -> int:
    """Classify a failed execution. Every triage is kept; the latest is the current one.

    ``base_commit`` is the baseline commit of the session versions. ``expected_change`` needs git to find its
    evidence (slice 4); until then it is refused.
    """
    with transaction(conn):
        execution = _failed_execution(conn, execution_id)
        if classification == "expected_change":
            raise InvariantViolation("INV-15: the evidence for expected_change is not available yet")
        if classification == "flaky" and not _flaky_evidence(conn, execution):
            raise InvariantViolation(
                "INV-15: flaky needs a rerun that passed, or an earlier execution of the same test case"
                " against the same commit that passed"
            )
        if classification == "pre_existing" and not _pre_existing_evidence(conn, execution, base_commit):
            raise InvariantViolation(
                "INV-15: pre_existing needs a candidate execution whose test case failed in the latest completed"
                " run on the baseline commit"
            )
        cursor = conn.execute(
            "INSERT INTO triage (execution_id, classification, justification, triaged_by, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (execution_id, classification, justification, triaged_by, utc_now()),
        )
        return cursor.lastrowid


def current_triage(conn: sqlite3.Connection, execution_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM triage WHERE execution_id = ? ORDER BY id DESC LIMIT 1", (execution_id,)
    ).fetchone()


def add_defect(
    conn: sqlite3.Connection,
    *,
    title: str,
    severity: str,
    execution_ids: list[int],
    steps: list | None = None,
) -> str:
    """Register an open defect linked to failed executions. The first one gives run, expected and actual."""
    if not execution_ids:
        raise InvariantViolation("a defect is linked to at least one execution")
    with transaction(conn):
        executions = [_failed_execution(conn, execution_id) for execution_id in execution_ids]
        first = executions[0]
        expected = conn.execute(
            "SELECT expected_result FROM test_case WHERE id = ?", (first["test_case_id"],)
        ).fetchone()[0]
        message = conn.execute(
            "SELECT failure_message FROM attempt WHERE execution_id = ? AND number = 1", (first["id"],)
        ).fetchone()
        lines = ((message[0] if message else None) or "").splitlines()
        actual = lines[0] if lines and lines[0].strip() else f"{first['result']} without a message"
        defect_id = next_id(conn, "DEF")
        conn.execute(
            "INSERT INTO defect (id, title, severity, detected_run_id, detected_at, expected, actual, steps)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                defect_id,
                title,
                severity,
                first["run_id"],
                utc_now(),
                expected,
                actual,
                json.dumps(steps or []),
            ),
        )
        for execution_id in execution_ids:
            conn.execute(
                "INSERT INTO defect_execution (defect_id, execution_id) VALUES (?, ?)", (defect_id, execution_id)
            )
    return defect_id


def close_defect(
    conn: sqlite3.Connection,
    defect_id: str,
    *,
    closed_by: str,
    close_reason: str,
    closed_run_id: str | None = None,
) -> None:
    """Close an open defect. Only a run that verifies the fix or the user closes a defect (INV-14, slice 4)."""
    with transaction(conn):
        require_exists(conn, "defect", "id", defect_id, "defect")
        conn.execute(
            "UPDATE defect SET status = 'closed', closed_at = ?, closed_by = ?, closed_run_id = ?, close_reason = ?"
            " WHERE id = ? AND status = 'open'",
            (utc_now(), closed_by, closed_run_id, close_reason, defect_id),
        )


def get_defect(conn: sqlite3.Connection, defect_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM defect WHERE id = ?", (defect_id,)).fetchone()
