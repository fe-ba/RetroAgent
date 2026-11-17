"""Test design and selection: tables ``test_case``, ``test_case_requirement``, ``suite`` and ``suite_test_case``."""

import json
import re
import sqlite3

from retroagent.memory.db import require_exists, transaction, utc_now
from retroagent.memory.errors import InvariantViolation
from retroagent.memory.ids import next_id


def add_test_case(
    conn: sqlite3.Connection,
    *,
    title: str,
    priority: str,
    designed_by: str,
    objective: str | None = None,
    preconditions: list | None = None,
    input_data: list | None = None,
    steps: list | None = None,
    expected_result: str | None = None,
    requirement_ids: list[str] | None = None,
) -> str:
    """Create a ``designed`` test case. The identifier is assigned here, never given."""
    requirement_ids = requirement_ids or []
    now = utc_now()
    with transaction(conn):
        for requirement_id in requirement_ids:
            require_exists(conn, "requirement", "id", requirement_id, "requirement")
        test_case_id = next_id(conn, "TC")
        conn.execute(
            "INSERT INTO test_case (id, title, objective, priority, status, origin, designed_by, preconditions,"
            " input_data, steps, expected_result, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'designed', 'designed', ?, ?, ?, ?, ?, ?, ?)",
            (
                test_case_id,
                title,
                objective,
                priority,
                designed_by,
                json.dumps(preconditions or []),
                json.dumps(input_data or []),
                json.dumps(steps or []),
                expected_result,
                now,
                now,
            ),
        )
        for requirement_id in requirement_ids:
            conn.execute(
                "INSERT INTO test_case_requirement (test_case_id, requirement_id, link) VALUES (?, ?, 'design')",
                (test_case_id, requirement_id),
            )
    return test_case_id


def add_project_suite_test_case(conn: sqlite3.Connection, *, test_id: str, implementation: str) -> str:
    """Create a test case for a test found in the project's own tests (``<classname>::<name>``).

    The requirements named in the test name that are in memory are linked by name (project-contract.md).
    """
    now = utc_now()
    with transaction(conn):
        test_case_id = next_id(conn, "TC")
        conn.execute(
            "INSERT INTO test_case (id, title, priority, status, origin, test_id, implementation, created_at,"
            " updated_at) VALUES (?, ?, 'medium', 'implemented', 'project_suite', ?, ?, ?, ?)",
            (test_case_id, test_id.split("::")[-1], test_id, implementation, now, now),
        )
        _link_by_name(conn, test_case_id, test_id)
    return test_case_id


# REQ-004, REQ_004 or req004, case-insensitive (project-contract.md, Traceability).
_REQUIREMENT_IN_NAME = re.compile(r"req[-_]?(\d{3,})", re.IGNORECASE)


def requirements_in_name(test_id: str) -> list[str]:
    """Requirement identifiers referenced by the name of a test (the part after ``::``), in order, once each."""
    name = test_id.rpartition("::")[2]
    return list(dict.fromkeys(f"REQ-{digits}" for digits in _REQUIREMENT_IN_NAME.findall(name)))


def _link_by_name(conn: sqlite3.Connection, test_case_id: str, test_id: str) -> int:
    added = 0
    for requirement_id in requirements_in_name(test_id):
        cursor = conn.execute(
            "INSERT OR IGNORE INTO test_case_requirement (test_case_id, requirement_id, link)"
            " SELECT ?, id, 'name' FROM requirement WHERE id = ?",
            (test_case_id, requirement_id),
        )
        added += cursor.rowcount
    return added


def link_tests_by_name(conn: sqlite3.Connection) -> int:
    """Add the missing name links of every project test; returns how many were added.

    Called again when requirements are synchronized, so the order of discovery and synchronization does not matter.
    """
    with transaction(conn):
        rows = conn.execute("SELECT id, test_id FROM test_case WHERE origin = 'project_suite' ORDER BY id").fetchall()
        return sum(_link_by_name(conn, row["id"], row["test_id"]) for row in rows)


_DESIGN_FIELDS = (
    "title",
    "objective",
    "priority",
    "preconditions",
    "input_data",
    "steps",
    "expected_result",
    "requirement_ids",
)
_JSON_FIELDS = ("preconditions", "input_data", "steps")


def update_test_case(conn: sqlite3.Connection, test_case_id: str, fields: dict) -> None:
    """Change the description of a test case, within the limits of ``memory.update_test_case`` (mcp-tools.md).

    A designed test case and a project test can change every design field; a generated test that is implemented
    only ``title``, ``objective`` and ``priority``. A retired test case cannot change. ``requirement_ids`` replaces
    the design links and keeps the links found in the test name. A failed call changes nothing.
    """
    with transaction(conn):
        row = conn.execute("SELECT * FROM test_case WHERE id = ?", (test_case_id,)).fetchone()
        if row is None:
            raise InvariantViolation(f"INV-13: test case {test_case_id!r} does not exist")
        if row["retired_at"] is not None:
            raise InvariantViolation(f"invalid_state: test case {test_case_id} is retired")
        if row["origin"] == "designed" and row["status"] == "implemented":
            allowed = ("title", "objective", "priority")
        else:
            allowed = _DESIGN_FIELDS
        refused = [name for name in fields if name not in allowed]
        if refused:
            why = (
                ": its generated test is implemented, so they change only with its code, through test_runner.write_test"
                if allowed != _DESIGN_FIELDS
                else ""
            )
            raise InvariantViolation(f"invalid_state: {', '.join(refused)} cannot change for {test_case_id}{why}")
        for requirement_id in fields.get("requirement_ids", []):
            require_exists(conn, "requirement", "id", requirement_id, "requirement")
        for name, value in fields.items():
            if name == "requirement_ids":
                # The one exception to INV-11: design links are replaced; name links are never deleted.
                conn.execute(
                    "DELETE FROM test_case_requirement WHERE test_case_id = ? AND link = 'design'", (test_case_id,)
                )
                for requirement_id in dict.fromkeys(value):
                    conn.execute(
                        "INSERT INTO test_case_requirement (test_case_id, requirement_id, link)"
                        " VALUES (?, ?, 'design')",
                        (test_case_id, requirement_id),
                    )
            else:
                stored = json.dumps(value) if name in _JSON_FIELDS else value
                conn.execute(f"UPDATE test_case SET {name} = ? WHERE id = ?", (stored, test_case_id))
        conn.execute("UPDATE test_case SET updated_at = ? WHERE id = ?", (utc_now(), test_case_id))


def _split_implementation(implementation: str) -> tuple[str, str]:
    file, separator, name = implementation.rpartition("::")
    if not separator or not file or not name:
        raise InvariantViolation(f"INV-17: implementation {implementation!r} is not '<file>::<test name>'")
    return file, name


def _generated(conn: sqlite3.Connection, test_case_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM test_case WHERE id = ?", (test_case_id,)).fetchone()
    if row is None:
        raise InvariantViolation(f"INV-13: test case {test_case_id!r} does not exist")
    if row["origin"] != "designed":
        raise InvariantViolation(f"{test_case_id} was not designed by the agent and has no generated test")
    return row


def mark_implemented(conn: sqlite3.Connection, test_case_id: str, implementation: str) -> None:
    """The first time test code is written for a designed test case: revision 1.

    The function name and the file must not belong to another generated test (INV-17).
    """
    file, name = _split_implementation(implementation)
    with transaction(conn):
        row = _generated(conn, test_case_id)
        if row["status"] == "implemented":
            raise InvariantViolation(f"{test_case_id} is already implemented; use a rewrite")
        for other_id, other in conn.execute(
            "SELECT id, implementation FROM test_case WHERE origin = 'designed' AND implementation IS NOT NULL"
        ):
            other_file, other_name = _split_implementation(other)
            if other_file == file or other_name == name:
                raise InvariantViolation(
                    f"INV-17: the file or the function name of {implementation!r} belongs to {other_id}"
                )
        conn.execute(
            "UPDATE test_case SET status = 'implemented', implementation = ?, revision = 1, updated_at = ?"
            " WHERE id = ?",
            (implementation, utc_now(), test_case_id),
        )


def rewrite_generated_test(conn: sqlite3.Connection, test_case_id: str, implementation: str) -> int:
    """A new revision of the code of a generated test. It keeps the function name and the file (INV-17)."""
    with transaction(conn):
        row = _generated(conn, test_case_id)
        if row["status"] != "implemented":
            raise InvariantViolation(f"{test_case_id} has no generated test to rewrite")
        if implementation != row["implementation"]:
            raise InvariantViolation(
                f"INV-17: a rewrite keeps the function name and the file of {test_case_id}: {row['implementation']!r}"
            )
        revision = row["revision"] + 1
        conn.execute(
            "UPDATE test_case SET revision = ?, updated_at = ? WHERE id = ?", (revision, utc_now(), test_case_id)
        )
    return revision


def retire_test_case(conn: sqlite3.Connection, test_case_id: str, *, reason: str, retired_by: str) -> str:
    """Take an active test case out of use. Retiring is permanent; returns the time it was retired."""
    now = utc_now()
    with transaction(conn):
        row = conn.execute("SELECT retired_at FROM test_case WHERE id = ?", (test_case_id,)).fetchone()
        if row is None:
            raise InvariantViolation(f"INV-13: test case {test_case_id!r} does not exist")
        if row["retired_at"] is not None:
            raise InvariantViolation(
                f"invalid_state: test case {test_case_id} was already retired at {row['retired_at']}"
            )
        conn.execute(
            "UPDATE test_case SET retired_at = ?, retire_reason = ?, retired_by = ?, updated_at = ? WHERE id = ?",
            (now, reason, retired_by, now, test_case_id),
        )
    return now


def bind_test_id(conn: sqlite3.Connection, test_case_id: str, test_id: str) -> None:
    """Bind a generated test to its JUnit entry, the first time a run reports it (project-contract.md)."""
    with transaction(conn):
        row = _generated(conn, test_case_id)
        if row["status"] != "implemented":
            raise InvariantViolation(f"{test_case_id} has no generated test to bind")
        if row["test_id"] is not None:
            raise InvariantViolation(f"{test_case_id} is already bound to {row['test_id']!r}")
        conn.execute(
            "UPDATE test_case SET test_id = ?, updated_at = ? WHERE id = ?", (test_id, utc_now(), test_case_id)
        )


def get_test_case(conn: sqlite3.Connection, test_case_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM test_case WHERE id = ?", (test_case_id,)).fetchone()


def active_implemented_test_cases(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM test_case WHERE status = 'implemented' AND retired_at IS NULL ORDER BY id"
    ).fetchall()


def count_active_test_cases(conn: sqlite3.Connection) -> dict[str, int]:
    """Active test cases by status: ``designed`` and ``implemented``."""
    counts = {"designed": 0, "implemented": 0}
    for row in conn.execute(
        "SELECT status, COUNT(*) AS n FROM test_case WHERE retired_at IS NULL GROUP BY status"
    ).fetchall():
        counts[row["status"]] = row["n"]
    return counts


def current_suite(conn: sqlite3.Connection, base_commit: str, candidate_commit: str) -> int | None:
    """The latest suite of the latest analysis of these versions; None when that analysis has no suite yet."""
    row = conn.execute(
        "SELECT id FROM suite WHERE analysis_id = (SELECT id FROM analysis WHERE base_commit = ?"
        " AND candidate_commit = ? ORDER BY id DESC LIMIT 1) ORDER BY id DESC LIMIT 1",
        (base_commit, candidate_commit),
    ).fetchone()
    return row["id"] if row else None


def suite_test_cases(conn: sqlite3.Connection, suite_id: int) -> list[sqlite3.Row]:
    """The test cases of a suite, in the order of their position."""
    return conn.execute(
        "SELECT tc.* FROM suite_test_case AS s JOIN test_case AS tc ON tc.id = s.test_case_id"
        " WHERE s.suite_id = ? ORDER BY s.position, tc.id",
        (suite_id,),
    ).fetchall()


def add_suite(conn: sqlite3.Connection, *, analysis_id: int, session_id: int) -> int:
    with transaction(conn):
        require_exists(conn, "analysis", "id", analysis_id, "analysis")
        cursor = conn.execute(
            "INSERT INTO suite (analysis_id, session_id, created_at) VALUES (?, ?, ?)",
            (analysis_id, session_id, utc_now()),
        )
        return cursor.lastrowid


def add_to_suite(
    conn: sqlite3.Connection, suite_id: int, *, test_case_id: str, position: int, selection_reason: str
) -> None:
    with transaction(conn):
        require_exists(conn, "suite", "id", suite_id, "suite")
        row = conn.execute("SELECT retired_at FROM test_case WHERE id = ?", (test_case_id,)).fetchone()
        if row is None:
            raise InvariantViolation(f"INV-13: test case {test_case_id!r} does not exist")
        if row["retired_at"] is not None:
            raise InvariantViolation(f"INV-16: test case {test_case_id} is retired and cannot be added to a suite")
        conn.execute(
            "INSERT INTO suite_test_case (suite_id, test_case_id, position, selection_reason) VALUES (?, ?, ?, ?)",
            (suite_id, test_case_id, position, selection_reason),
        )


def save_suite(conn: sqlite3.Connection, *, analysis_id: int, session_id: int, items: list[dict]) -> int:
    """A new suite for an analysis with its items ``{test_case_id, position, selection_reason}``, in one transaction.

    Unknown references fail first (INV-13); then duplicated test cases or positions, and retired test cases (INV-16),
    are refused as ``invalid_argument``, naming each one.
    """
    with transaction(conn):
        require_exists(conn, "analysis", "id", analysis_id, "analysis")
        test_case_ids = [item["test_case_id"] for item in items]
        for test_case_id in dict.fromkeys(test_case_ids):
            require_exists(conn, "test_case", "id", test_case_id, "test case")
        positions = [item["position"] for item in items]
        problems = []
        repeated = sorted({t for t in test_case_ids if test_case_ids.count(t) > 1})
        if repeated:
            problems.append(f"repeated test cases: {', '.join(repeated)}")
        repeated_positions = sorted({p for p in positions if positions.count(p) > 1})
        if repeated_positions:
            problems.append(f"repeated positions: {', '.join(map(str, repeated_positions))}")
        marks = ",".join("?" * len(test_case_ids))
        retired = [
            row["id"]
            for row in conn.execute(
                f"SELECT id FROM test_case WHERE retired_at IS NOT NULL AND id IN ({marks}) ORDER BY id", test_case_ids
            )
        ]
        if retired:
            problems.append(f"INV-16: retired test cases cannot be added to a suite: {', '.join(retired)}")
        if problems:
            raise InvariantViolation("invalid_argument: " + "; ".join(problems))
        suite_id = add_suite(conn, analysis_id=analysis_id, session_id=session_id)
        for item in items:
            add_to_suite(
                conn,
                suite_id,
                test_case_id=item["test_case_id"],
                position=item["position"],
                selection_reason=item["selection_reason"],
            )
    return suite_id


def design_test_case(
    conn: sqlite3.Connection, *, suite_id: int, selection_reason: str, designed_by: str, **fields
) -> tuple[str, int]:
    """Create a ``designed`` test case and add it to the suite after its last position, in one transaction.

    ``fields`` are the design fields of ``add_test_case``. ``requirement_ids`` may be empty only when memory holds no
    requirement. Returns the test case ID and its position.
    """
    with transaction(conn):
        require_exists(conn, "suite", "id", suite_id, "suite")
        has_requirements = conn.execute("SELECT 1 FROM requirement LIMIT 1").fetchone() is not None
        if has_requirements and not fields.get("requirement_ids"):
            raise InvariantViolation(
                "invalid_argument: requirement_ids is empty, but the project has requirements: trace the test case"
                " to every requirement it verifies"
            )
        test_case_id = add_test_case(conn, designed_by=designed_by, **fields)
        position = conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM suite_test_case WHERE suite_id = ?", (suite_id,)
        ).fetchone()[0]
        add_to_suite(conn, suite_id, test_case_id=test_case_id, position=position, selection_reason=selection_reason)
    return test_case_id, position


def suite_items(conn: sqlite3.Connection, suite_id: int) -> list[sqlite3.Row]:
    """The items of a suite with the test case of each, in the order of their position."""
    return conn.execute(
        "SELECT s.position, s.test_case_id, s.selection_reason, tc.title, tc.priority, tc.status, tc.origin,"
        " tc.retired_at FROM suite_test_case AS s JOIN test_case AS tc ON tc.id = s.test_case_id"
        " WHERE s.suite_id = ? ORDER BY s.position, tc.id",
        (suite_id,),
    ).fetchall()


def get_suite(conn: sqlite3.Connection, suite_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM suite WHERE id = ?", (suite_id,)).fetchone()


def list_test_cases(
    conn: sqlite3.Connection,
    *,
    ids: list[str] | None = None,
    status: str | None = None,
    requirement_id: str | None = None,
    include_retired: bool = False,
) -> list[sqlite3.Row]:
    """Test cases by ID, filtered by every criterion given. Test cases asked for by ID are returned even when
    retired; otherwise retired ones only with ``include_retired``."""
    sql, params = "SELECT * FROM test_case WHERE 1 = 1", []
    if ids is not None:
        sql += f" AND id IN ({','.join('?' * len(ids))})"
        params += ids
    elif not include_retired:
        sql += " AND retired_at IS NULL"
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    if requirement_id is not None:
        sql += " AND id IN (SELECT test_case_id FROM test_case_requirement WHERE requirement_id = ?)"
        params.append(requirement_id)
    return conn.execute(sql + " ORDER BY id", params).fetchall()


def test_case_requirements(conn: sqlite3.Connection, test_case_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT requirement_id, link FROM test_case_requirement WHERE test_case_id = ? ORDER BY requirement_id, link",
        (test_case_id,),
    ).fetchall()
