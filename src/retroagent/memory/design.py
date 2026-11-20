"""Test design and selection: tables ``test_case``, ``test_case_requirement``, ``suite``, ``suite_test_case`` and
``suite_left_out``."""

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


_PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}


def discovered_priority(conn: sqlite3.Connection, test_id: str) -> str:
    """The priority a discovered test starts with: the highest priority of the requirements in memory that its name
    links it to, or ``medium`` when it has none (data-model.md, ``test_case``). A requirement without a documented
    priority does not count."""
    priorities = [
        row["priority"]
        for requirement_id in requirements_in_name(test_id)
        if (row := conn.execute("SELECT priority FROM requirement WHERE id = ?", (requirement_id,)).fetchone())
        and row["priority"] is not None
    ]
    return max(priorities, key=_PRIORITY_RANK.__getitem__) if priorities else "medium"


def add_project_suite_test_case(conn: sqlite3.Connection, *, test_id: str, implementation: str) -> str:
    """Create a test case for a test found in the project's own tests (``<classname>::<name>``).

    The requirements named in the test name that are in memory are linked by name (project-contract.md), and the test
    case starts with the highest priority among them.
    """
    now = utc_now()
    with transaction(conn):
        test_case_id = next_id(conn, "TC")
        conn.execute(
            "INSERT INTO test_case (id, title, priority, status, origin, test_id, implementation, created_at,"
            " updated_at) VALUES (?, ?, ?, 'implemented', 'project_suite', ?, ?, ?, ?)",
            (
                test_case_id,
                test_id.split("::")[-1],
                discovered_priority(conn, test_id),
                test_id,
                implementation,
                now,
                now,
            ),
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

    Called again when requirements are synchronized, so the order of discovery and synchronization does not matter. A
    test that gets its first name links here gets its priority again, by the rule of discovery; a test that already
    had name links keeps its priority, which the model may have changed (data-model.md, ``test_case.priority``).
    """
    with transaction(conn):
        rows = conn.execute("SELECT id, test_id FROM test_case WHERE origin = 'project_suite' ORDER BY id").fetchall()
        added = 0
        for row in rows:
            had_links = conn.execute(
                "SELECT 1 FROM test_case_requirement WHERE test_case_id = ? AND link = 'name' LIMIT 1", (row["id"],)
            ).fetchone()
            linked = _link_by_name(conn, row["id"], row["test_id"])
            if linked and not had_links:
                conn.execute(
                    "UPDATE test_case SET priority = ?, updated_at = ? WHERE id = ?",
                    (discovered_priority(conn, row["test_id"]), utc_now(), row["id"]),
                )
            added += linked
        return added


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
        _write_fields(conn, test_case_id, fields)
        conn.execute("UPDATE test_case SET updated_at = ? WHERE id = ?", (utc_now(), test_case_id))


def _write_fields(conn: sqlite3.Connection, test_case_id: str, fields: dict) -> None:
    """Write design fields of a test case, inside the caller's transaction. ``requirement_ids`` replaces the design
    links and keeps the links found in the test name."""
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
                    "INSERT INTO test_case_requirement (test_case_id, requirement_id, link) VALUES (?, ?, 'design')",
                    (test_case_id, requirement_id),
                )
        else:
            stored = json.dumps(value) if name in _JSON_FIELDS else value
            conn.execute(f"UPDATE test_case SET {name} = ? WHERE id = ?", (stored, test_case_id))


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
        if row["retired_at"] is not None:
            raise InvariantViolation(f"invalid_state: test case {test_case_id} is retired")
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


# Design fields that describe the code of a generated test: they change only together with it (mcp-tools.md,
# ``test_runner.write_test``).
REWRITE_FIELDS = ("preconditions", "input_data", "steps", "expected_result", "requirement_ids")


def rewrite_generated_test(
    conn: sqlite3.Connection, test_case_id: str, implementation: str, fields: dict | None = None
) -> int:
    """A new revision of the code of a generated test, with the design fields that change with it, in one
    transaction. It keeps the function name and the file (INV-17). Returns the new revision."""
    fields = fields or {}
    with transaction(conn):
        row = _generated(conn, test_case_id)
        if row["status"] != "implemented":
            raise InvariantViolation(f"{test_case_id} has no generated test to rewrite")
        if row["retired_at"] is not None:
            raise InvariantViolation(f"invalid_state: test case {test_case_id} is retired")
        if implementation != row["implementation"]:
            raise InvariantViolation(
                f"INV-17: a rewrite keeps the function name and the file of {test_case_id}: {row['implementation']!r}"
            )
        refused = [name for name in fields if name not in REWRITE_FIELDS]
        if refused:
            raise InvariantViolation(
                f"invalid_argument: {', '.join(refused)} cannot change with the code; use memory.update_test_case"
            )
        _write_fields(conn, test_case_id, fields)
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


def add_left_out(conn: sqlite3.Connection, suite_id: int, *, test_case_id: str, reason: str) -> None:
    with transaction(conn):
        require_exists(conn, "suite", "id", suite_id, "suite")
        require_exists(conn, "test_case", "id", test_case_id, "test case")
        conn.execute(
            "INSERT INTO suite_left_out (suite_id, test_case_id, reason) VALUES (?, ?, ?)",
            (suite_id, test_case_id, reason),
        )


def test_cases_to_decide(conn: sqlite3.Connection, analysis_id: int) -> dict[str, list[str]]:
    """The active, implemented test cases traced to an impacted requirement of the analysis, by a design or a name
    link, each with those requirements: ``save_suite`` must find each one in its items or in its left_out."""
    decide: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT DISTINCT tc.id, ar.requirement_id FROM test_case tc"
        " JOIN test_case_requirement tr ON tr.test_case_id = tc.id"
        " JOIN analysis_requirement ar ON ar.requirement_id = tr.requirement_id AND ar.analysis_id = ?"
        " WHERE tc.status = 'implemented' AND tc.retired_at IS NULL ORDER BY tc.id, ar.requirement_id",
        (analysis_id,),
    ):
        decide.setdefault(row["id"], []).append(row["requirement_id"])
    return decide


def _latest_full_run(conn: sqlite3.Connection, commit: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM run WHERE \"commit\" = ? AND scope = 'all' AND status = 'completed'"
        " ORDER BY started_at DESC, id DESC LIMIT 1",
        (commit,),
    ).fetchone()
    return None if row is None else row["id"]


def verdict_changes(conn: sqlite3.Connection, base_commit: str, candidate_commit: str) -> dict[str, tuple[str, ...]]:
    """The active test cases whose verdict differs between the latest completed full runs on the two commits, when
    both exist: passed in one and failed or error in the other. Each maps to ``(base_run, base_result,
    candidate_run, candidate_result)``. The result of an execution is the one of its first attempt, so a flaky one
    is a failure (ADR-0022); a test case that one of the runs did not execute has no verdict there."""
    base_run, candidate_run = _latest_full_run(conn, base_commit), _latest_full_run(conn, candidate_commit)
    if base_run is None or candidate_run is None:
        return {}
    changes = {}
    for row in conn.execute(
        "SELECT b.test_case_id, b.result AS base_result, c.result AS candidate_result FROM test_execution b"
        " JOIN test_execution c ON c.test_case_id = b.test_case_id AND c.run_id = ? AND c.status = 'executed'"
        " JOIN test_case tc ON tc.id = b.test_case_id AND tc.retired_at IS NULL"
        " WHERE b.run_id = ? AND b.status = 'executed' ORDER BY b.test_case_id",
        (candidate_run, base_run),
    ):
        if (row["base_result"] == "passed") != (row["candidate_result"] == "passed"):
            changes[row["test_case_id"]] = (base_run, row["base_result"], candidate_run, row["candidate_result"])
    return changes


def _repeated(values: list) -> list:
    return sorted({value for value in values if values.count(value) > 1})


def _not_in_candidate_full_run(
    conn: sqlite3.Connection, candidate_commit: str, test_case_ids: list[str]
) -> tuple[str | None, list[str]]:
    """The latest completed full run on the candidate commit, and the test cases of the project suite among
    ``test_case_ids`` that it has no execution for: in a full run, a project test that the JUnit XML does not report
    has no execution. Generated test cases are not checked. Without that run, ``(None, [])``."""
    run_id = _latest_full_run(conn, candidate_commit)
    if run_id is None or not test_case_ids:
        return run_id, []
    marks = ",".join("?" * len(test_case_ids))
    missing = [
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM test_case tc WHERE id IN ({marks}) AND origin = 'project_suite' AND NOT EXISTS"
            " (SELECT 1 FROM test_execution e WHERE e.run_id = ? AND e.test_case_id = tc.id) ORDER BY id",
            (*test_case_ids, run_id),
        )
    ]
    return run_id, missing


def save_suite(
    conn: sqlite3.Connection,
    *,
    analysis_id: int,
    session_id: int,
    items: list[dict],
    left_out: list[dict],
    confirm: bool = False,
) -> int:
    """A new suite for an analysis with its items ``{test_case_id, position, selection_reason}`` and the test cases it
    leaves out ``{test_case_id, reason}``, in one transaction.

    Unknown references fail first (INV-13). Then every problem is refused at once as ``invalid_argument``, naming each
    test case: repeated test cases or positions, retired items (INV-16), a test case in both lists, and in neither a
    test case of an impacted requirement or one whose verdict differs between the latest full runs on the commits of
    the analysis (mcp-tools.md, ``memory.save_suite``). A test case that passed in the baseline full run and failed or
    had an error in the candidate full run has already shown a difference: in left_out it is refused. Any other test
    case may be left out.

    Then one soft check, passed only with ``confirm``: a test case of the project suite in items that the latest
    completed full run on the candidate commit has no execution for is refused as ``invalid_state``. Its test does
    not exist in the candidate version, or its file could not be loaded there: selected, it would only be blocked.
    """
    with transaction(conn):
        require_exists(conn, "analysis", "id", analysis_id, "analysis")
        analysis = conn.execute(
            "SELECT base_commit, candidate_commit, candidate_ref FROM analysis WHERE id = ?", (analysis_id,)
        ).fetchone()
        test_case_ids = [item["test_case_id"] for item in items]
        left_out_ids = [entry["test_case_id"] for entry in left_out]
        for test_case_id in dict.fromkeys(test_case_ids + left_out_ids):
            require_exists(conn, "test_case", "id", test_case_id, "test case")
        problems = []
        if repeated := _repeated(test_case_ids):
            problems.append(f"repeated test cases: {', '.join(repeated)}")
        if repeated_positions := _repeated([item["position"] for item in items]):
            problems.append(f"repeated positions: {', '.join(map(str, repeated_positions))}")
        if repeated_left_out := _repeated(left_out_ids):
            problems.append(f"repeated test cases in left_out: {', '.join(repeated_left_out)}")
        marks = ",".join("?" * len(test_case_ids))
        retired = [
            row["id"]
            for row in conn.execute(
                f"SELECT id FROM test_case WHERE retired_at IS NOT NULL AND id IN ({marks}) ORDER BY id", test_case_ids
            )
        ]
        if retired:
            problems.append(f"INV-16: retired test cases cannot be added to a suite: {', '.join(retired)}")
        if in_both := sorted(set(test_case_ids) & set(left_out_ids)):
            problems.append(f"test cases in both items and left_out: {', '.join(in_both)}")
        decided = set(test_case_ids) | set(left_out_ids)
        undecided = [
            f"{test_case_id} ({', '.join(requirement_ids)})"
            for test_case_id, requirement_ids in test_cases_to_decide(conn, analysis_id).items()
            if test_case_id not in decided
        ]
        if undecided:
            problems.append(
                "test cases traced to an impacted requirement are in neither items nor left_out:"
                f" {', '.join(undecided)}; select each one or add it to left_out with a reason"
            )
        changes = verdict_changes(conn, analysis["base_commit"], analysis["candidate_commit"])

        def named(test_case_id: str) -> str:
            base_run, base_result, candidate_run, candidate_result = changes[test_case_id]
            return (
                f"{test_case_id} ({base_result} in {base_run} on the baseline, {candidate_result} in {candidate_run}"
                " on the candidate)"
            )

        if changed := [named(test_case_id) for test_case_id in changes if test_case_id not in decided]:
            problems.append(
                "test cases whose verdict differs between the latest full runs of the baseline and the candidate are"
                f" in neither items nor left_out: {', '.join(changed)}; select each one or add it to left_out with a"
                " reason"
            )
        broken = [
            named(test_case_id)
            for test_case_id, (_, base_result, _, _) in changes.items()
            if base_result == "passed" and test_case_id in left_out_ids
        ]
        if broken:
            problems.append(
                "test cases that passed in the latest full run of the baseline and failed or had an error in the"
                f" latest full run of the candidate cannot be left out: {', '.join(broken)}; select each one"
            )
        if problems:
            raise InvariantViolation("invalid_argument: " + "; ".join(problems))
        full_run, missing = _not_in_candidate_full_run(conn, analysis["candidate_commit"], test_case_ids)
        if missing and not confirm:
            raise InvariantViolation(
                f"invalid_state: test cases of the project suite have no execution in {full_run}, the latest completed"
                f" full run on the candidate {analysis['candidate_ref']}: {', '.join(missing)}. Their tests do not"
                " exist in the candidate version, or their files could not be loaded there (see the error of"
                f" {full_run}): selected, they would only be blocked. Leave each one out with that reason, or call"
                " again with confirm true if the evidence shows otherwise"
            )
        suite_id = add_suite(conn, analysis_id=analysis_id, session_id=session_id)
        for item in items:
            add_to_suite(
                conn,
                suite_id,
                test_case_id=item["test_case_id"],
                position=item["position"],
                selection_reason=item["selection_reason"],
            )
        for entry in left_out:
            add_left_out(conn, suite_id, test_case_id=entry["test_case_id"], reason=entry["reason"])
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


def suite_left_out(conn: sqlite3.Connection, suite_id: int) -> list[sqlite3.Row]:
    """The test cases a suite leaves out, with the reason of each, by test case ID."""
    return conn.execute(
        "SELECT test_case_id, reason FROM suite_left_out WHERE suite_id = ? ORDER BY test_case_id", (suite_id,)
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


def uncovered_requirements(conn: sqlite3.Connection, suite_id: int) -> list[str]:
    """The impacted requirements of the analysis of a suite that no active test case of the suite is traced to, by a
    design or a name link. Computed from the records, never stored (mcp-tools.md, save_suite and get_suite)."""
    return [
        row["requirement_id"]
        for row in conn.execute(
            "SELECT ar.requirement_id FROM analysis_requirement ar JOIN suite s ON s.analysis_id = ar.analysis_id"
            " WHERE s.id = ? AND NOT EXISTS (SELECT 1 FROM suite_test_case st"
            " JOIN test_case tc ON tc.id = st.test_case_id AND tc.retired_at IS NULL"
            " JOIN test_case_requirement tr ON tr.test_case_id = tc.id AND tr.requirement_id = ar.requirement_id"
            " WHERE st.suite_id = s.id) ORDER BY ar.requirement_id",
            (suite_id,),
        )
    ]
