"""Interpretation: tables ``triage``, ``defect`` and ``defect_execution``.

A triage with classification ``expected_change``, ``flaky``, ``pre_existing`` or ``regression`` is stored only when its
evidence is found here (INV-15, mcp-tools.md ``memory.save_triage``). Whether a ``Changed`` or ``Removed`` entry applies
to the change needs git: the caller gives it as ``change_applies(version)``, so the data layer never runs git itself.

A defect is closed only by the user (``close_defect``) or by a completed run against the candidate in which every
linked test case passed (``close_defects_verified_by``, INV-14).
"""

import json
import sqlite3
from collections.abc import Callable

from retroagent.memory.db import require_exists, transaction, utc_now
from retroagent.memory.errors import InvariantViolation
from retroagent.memory.execution import is_flaky, list_attempts
from retroagent.memory.ids import next_id

FAILED = ("failed", "error")


def _failed_execution(conn: sqlite3.Connection, execution_id: int) -> sqlite3.Row:
    row = conn.execute(
        'SELECT e.*, r.version_role, r."commit" AS run_commit FROM test_execution e JOIN run r ON r.id = e.run_id'
        " WHERE e.id = ?",
        (execution_id,),
    ).fetchone()
    if row is None:
        raise InvariantViolation(f"INV-13: execution {execution_id!r} does not exist")
    if row["result"] not in FAILED:
        described = row["result"] or row["status"]
        raise InvariantViolation(
            f"INV-08: execution {execution_id} of {row['test_case_id']} is {described}, not failed or error"
        )
    return row


def _unique(execution_ids: list[int]) -> None:
    seen = set()
    for execution_id in execution_ids:
        if execution_id in seen:
            raise InvariantViolation(f"invalid_argument: execution {execution_id} is listed twice")
        seen.add(execution_id)


# Evidence of the classifications that code validates (INV-15). Each returns None when the evidence is found, or what
# is missing.


def _flaky_missing(conn: sqlite3.Connection, execution: sqlite3.Row) -> str | None:
    if is_flaky(conn, execution["id"]):
        return None
    different = conn.execute(
        'SELECT 1 FROM test_execution e JOIN run r ON r.id = e.run_id WHERE e.test_case_id = ? AND r."commit" = ?'
        " AND e.id < ? AND e.status = 'executed' AND e.result = 'passed' LIMIT 1",
        (execution["test_case_id"], execution["run_commit"], execution["id"]),
    ).fetchone()
    if different is not None:
        return None
    attempts = ", ".join(row["result"] for row in list_attempts(conn, execution["id"]))
    return (
        f"flaky needs a rerun that passed, or an earlier execution of {execution['test_case_id']} on the same commit"
        f" that passed: no rerun of execution {execution['id']} passed (attempts: {attempts}), and no earlier"
        f" execution of {execution['test_case_id']} on commit {execution['run_commit'][:12]} passed"
    )


def _against_candidate_missing(
    classification: str, execution: sqlite3.Row, base_commit: str | None, candidate_commit: str | None
) -> str | None:
    """A run against the candidate is a run on the candidate commit of the session versions (mcp-tools.md)."""
    if base_commit is None or candidate_commit is None:
        return f"{classification} needs the session versions, and they are not set"
    if execution["run_commit"] != candidate_commit:
        return (
            f"{classification} needs an execution of a run against the candidate: {execution['run_id']} is on commit"
            f" {execution['run_commit'][:12]}, not on the candidate commit {candidate_commit[:12]}"
        )
    return None


def _latest_baseline_execution(conn: sqlite3.Connection, test_case_id: str, base_commit: str) -> sqlite3.Row | None:
    """The execution of the test case in the latest completed run on the baseline commit that executed it."""
    return conn.execute(
        "SELECT e.result, r.id AS run_id FROM test_execution e JOIN run r ON r.id = e.run_id WHERE e.test_case_id = ?"
        " AND r.\"commit\" = ? AND r.status = 'completed' AND e.status = 'executed'"
        " ORDER BY r.started_at DESC, r.id DESC LIMIT 1",
        (test_case_id, base_commit),
    ).fetchone()


def _regression_missing(conn: sqlite3.Connection, execution: sqlite3.Row, base_commit: str | None) -> str | None:
    """A failure that the baseline already had is not caused by the change. Without session versions there is no
    baseline to check, and a test case that the baseline never executed may be a regression."""
    if base_commit is None:
        return None
    test_case_id = execution["test_case_id"]
    latest = _latest_baseline_execution(conn, test_case_id, base_commit)
    if latest is None or latest["result"] not in FAILED:
        return None
    return (
        f"regression needs {test_case_id} not to fail against the baseline, and its result was {latest['result']} in"
        f" {latest['run_id']}, the latest completed run on the baseline commit {base_commit[:12]} that executed it:"
        " a failure that the baseline already had is pre_existing"
    )


def _pre_existing_missing(
    conn: sqlite3.Connection, execution: sqlite3.Row, base_commit: str | None, candidate_commit: str | None
) -> str | None:
    missing = _against_candidate_missing("pre_existing", execution, base_commit, candidate_commit)
    if missing:
        return missing
    test_case_id = execution["test_case_id"]
    latest = _latest_baseline_execution(conn, test_case_id, base_commit)
    if latest is None:
        return (
            f"pre_existing needs a completed run on the baseline commit {base_commit[:12]} that executed"
            f" {test_case_id}, and there is none: run the baseline first"
        )
    if latest["result"] not in FAILED:
        return (
            f"pre_existing needs {test_case_id} to fail against the baseline: it {latest['result']} in"
            f" {latest['run_id']}, the latest completed run on the baseline commit that executed it"
        )
    return None


def _expected_change_missing(
    conn: sqlite3.Connection,
    execution: sqlite3.Row,
    base_commit: str | None,
    candidate_commit: str | None,
    change_applies: Callable[[str], bool] | None,
) -> str | None:
    missing = _against_candidate_missing("expected_change", execution, base_commit, candidate_commit)
    if missing:
        return missing
    if change_applies is None:
        return "expected_change needs the session versions, and they are not set"
    test_case_id = execution["test_case_id"]
    traced = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT requirement_id FROM test_case_requirement WHERE test_case_id = ? ORDER BY requirement_id",
            (test_case_id,),
        )
    ]
    if not traced:
        return f"expected_change needs a requirement traced to {test_case_id}, and it traces none"
    entries = conn.execute(
        "SELECT requirement_id, version FROM requirement_change"
        f" WHERE requirement_id IN ({', '.join('?' * len(traced))})"
        " UNION ALL SELECT id, removed FROM requirement"
        f" WHERE id IN ({', '.join('?' * len(traced))}) AND removed IS NOT NULL",
        (*traced, *traced),
    ).fetchall()
    if any(change_applies(entry["version"]) for entry in entries):
        return None
    names = ", ".join(traced)
    if not entries:
        found = f"{'it has' if len(traced) == 1 else 'none of them has'} no Changed or Removed entry"
    else:
        versions = ", ".join(sorted({f"{e['requirement_id']} {e['version']}" for e in entries}))
        found = f"its entries ({versions}) do not apply to the change between the session versions"
    return (
        f"expected_change needs a requirement traced to {test_case_id} with a Changed or Removed entry that applies"
        f" to the change between the session versions: {test_case_id} traces {names}, and {found}"
    )


def add_triage(
    conn: sqlite3.Connection,
    *,
    execution_id: int,
    classification: str,
    justification: str,
    triaged_by: str,
    base_commit: str | None = None,
    candidate_commit: str | None = None,
    change_applies: Callable[[str], bool] | None = None,
    replace: bool = False,
) -> int:
    """Classify a failed execution. Every triage is kept; the latest is the current one.

    ``base_commit`` and ``candidate_commit`` are the commits of the session versions, None while they are not set.
    ``change_applies(version)`` tells whether a ``Changed`` or ``Removed`` entry of that version applies to the change
    between them. An execution that already has a triage is triaged again only with ``replace``.
    """
    with transaction(conn):
        execution = _failed_execution(conn, execution_id)
        current = current_triage(conn, execution_id)
        if current is not None and not replace:
            raise InvariantViolation(
                f"invalid_state: execution {execution_id} of {execution['test_case_id']} is already triaged as"
                f" {current['classification']}; set replace to true to triage it again"
            )
        missing = None
        if classification == "flaky":
            missing = _flaky_missing(conn, execution)
        elif classification == "pre_existing":
            missing = _pre_existing_missing(conn, execution, base_commit, candidate_commit)
        elif classification == "expected_change":
            missing = _expected_change_missing(conn, execution, base_commit, candidate_commit, change_applies)
        elif classification == "regression":
            missing = _regression_missing(conn, execution, base_commit)
        if missing:
            raise InvariantViolation(f"INV-15: {missing}")
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


def triage_count(conn: sqlite3.Connection, execution_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM triage WHERE execution_id = ?", (execution_id,)).fetchone()[0]


# Defects -------------------------------------------------------------------------------------------------------------


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
        raise InvariantViolation("invalid_argument: a defect is linked to at least one execution")
    _unique(execution_ids)
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


def _open_defect(conn: sqlite3.Connection, defect_id: str) -> sqlite3.Row:
    require_exists(conn, "defect", "id", defect_id, "defect")
    row = get_defect(conn, defect_id)
    if row["status"] != "open":
        raise InvariantViolation(f"invalid_state: {defect_id} is already closed")
    return row


def link_executions(conn: sqlite3.Connection, defect_id: str, execution_ids: list[int]) -> None:
    """Link more failed executions to an open defect, when the same failure appears in a later run."""
    if not execution_ids:
        raise InvariantViolation("invalid_argument: give at least one execution")
    _unique(execution_ids)
    with transaction(conn):
        _open_defect(conn, defect_id)
        for execution_id in execution_ids:
            _failed_execution(conn, execution_id)
            linked = conn.execute(
                "SELECT 1 FROM defect_execution WHERE defect_id = ? AND execution_id = ?", (defect_id, execution_id)
            ).fetchone()
            if linked is not None:
                raise InvariantViolation(f"invalid_state: execution {execution_id} is already linked to {defect_id}")
            conn.execute(
                "INSERT INTO defect_execution (defect_id, execution_id) VALUES (?, ?)", (defect_id, execution_id)
            )


def close_defect(
    conn: sqlite3.Connection,
    defect_id: str,
    *,
    closed_by: str,
    close_reason: str,
    closed_run_id: str | None = None,
) -> None:
    """Close an open defect. Only a run that verifies the fix or the user closes a defect (INV-14)."""
    with transaction(conn):
        _open_defect(conn, defect_id)
        conn.execute(
            "UPDATE defect SET status = 'closed', closed_at = ?, closed_by = ?, closed_run_id = ?, close_reason = ?"
            " WHERE id = ? AND status = 'open'",
            (utc_now(), closed_by, closed_run_id, close_reason, defect_id),
        )


def close_defects_verified_by(conn: sqlite3.Connection, run_id: str) -> list[str]:
    """Close every open defect whose linked test cases all passed in ``run_id``, when it is a completed run against
    the candidate (``test_runner.run_tests`` with version ``candidate``). Returns the IDs of the closed defects.

    A flaky execution never closes a defect: its result is the one of its first attempt, which did not pass.
    """
    with transaction(conn):
        run = conn.execute("SELECT status, version_role FROM run WHERE id = ?", (run_id,)).fetchone()
        if run is None or run["status"] != "completed" or run["version_role"] != "candidate":
            return []
        passed = {
            row[0]
            for row in conn.execute(
                "SELECT test_case_id FROM test_execution WHERE run_id = ? AND result = 'passed'", (run_id,)
            )
        }
        closed = []
        for defect in conn.execute("SELECT id FROM defect WHERE status = 'open' ORDER BY id").fetchall():
            linked = linked_test_cases(conn, defect["id"])
            if linked and set(linked) <= passed:
                reason = f"Every linked test case passed in {run_id}: {', '.join(linked)}."
                close_defect(conn, defect["id"], closed_by="run", close_reason=reason, closed_run_id=run_id)
                closed.append(defect["id"])
    return closed


def linked_test_cases(conn: sqlite3.Connection, defect_id: str) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT e.test_case_id FROM defect_execution d JOIN test_execution e ON e.id = d.execution_id"
            " WHERE d.defect_id = ? ORDER BY e.test_case_id",
            (defect_id,),
        )
    ]


def linked_executions(conn: sqlite3.Connection, defect_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT e.id AS execution_id, e.run_id, e.test_case_id, e.result FROM defect_execution d"
        " JOIN test_execution e ON e.id = d.execution_id WHERE d.defect_id = ? ORDER BY e.id",
        (defect_id,),
    ).fetchall()


def get_defect(conn: sqlite3.Connection, defect_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM defect WHERE id = ?", (defect_id,)).fetchone()


def list_defects(conn: sqlite3.Connection, status: str | None = None) -> list[sqlite3.Row]:
    """Defects by ID, all of them or those with ``status`` ``open`` or ``closed``."""
    if status is None:
        return conn.execute("SELECT * FROM defect ORDER BY id").fetchall()
    return conn.execute("SELECT * FROM defect WHERE status = ? ORDER BY id", (status,)).fetchall()


def defects_closed_by(conn: sqlite3.Connection, run_id: str) -> list[str]:
    return [row[0] for row in conn.execute("SELECT id FROM defect WHERE closed_run_id = ? ORDER BY id", (run_id,))]
