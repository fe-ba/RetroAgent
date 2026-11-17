"""Impact analysis: tables ``analysis``, ``analysis_file``, ``analysis_module``, ``analysis_requirement``,
``risk`` and ``risk_requirement``."""

import json
import sqlite3

from retroagent.memory.db import require_exists, transaction, utc_now
from retroagent.memory.errors import InvariantViolation
from retroagent.memory.ids import next_id


def add_analysis(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    base_ref: str,
    base_commit: str,
    candidate_ref: str,
    candidate_commit: str,
    files: list[dict],
) -> int:
    """Store an analysis with its change set; a file is ``{path, change, lines_added, lines_removed[, old_path]}``."""
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO analysis (base_ref, base_commit, candidate_ref, candidate_commit, session_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (base_ref, base_commit, candidate_ref, candidate_commit, session_id, utc_now()),
        )
        analysis_id = cursor.lastrowid
        for file in files:
            conn.execute(
                "INSERT INTO analysis_file (analysis_id, path, old_path, change, lines_added, lines_removed)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    analysis_id,
                    file["path"],
                    file.get("old_path"),
                    file["change"],
                    file["lines_added"],
                    file["lines_removed"],
                ),
            )
    return analysis_id


def record_impact(
    conn: sqlite3.Connection,
    analysis_id: int,
    *,
    modules: list[dict],
    requirements: list[dict],
) -> None:
    """Write the impact of an analysis, once (INV-10). Every reference must exist (INV-13), or nothing is written.

    A module is ``{module, files, risk_level, reason}``; a requirement is ``{requirement_id, reason}``.
    """
    with transaction(conn):
        require_exists(conn, "analysis", "id", analysis_id, "analysis")
        already = conn.execute(
            "SELECT (SELECT COUNT(*) FROM analysis_module WHERE analysis_id = ?)"
            " + (SELECT COUNT(*) FROM analysis_requirement WHERE analysis_id = ?)",
            (analysis_id, analysis_id),
        ).fetchone()[0]
        if already:
            raise InvariantViolation(
                "INV-10: the impact of an analysis is written once; a corrected impact needs a new analysis"
            )
        known_files = {
            row[0] for row in conn.execute("SELECT path FROM analysis_file WHERE analysis_id = ?", (analysis_id,))
        }
        for module in modules:
            for path in module["files"]:
                if path not in known_files:
                    raise InvariantViolation(
                        f"INV-13: file {path!r} is not in the change set of analysis {analysis_id}"
                    )
            conn.execute(
                "INSERT INTO analysis_module (analysis_id, module, files, risk_level, reason) VALUES (?, ?, ?, ?, ?)",
                (analysis_id, module["module"], json.dumps(module["files"]), module["risk_level"], module["reason"]),
            )
        for requirement in requirements:
            require_exists(conn, "requirement", "id", requirement["requirement_id"], "requirement")
            conn.execute(
                "INSERT INTO analysis_requirement (analysis_id, requirement_id, reason) VALUES (?, ?, ?)",
                (analysis_id, requirement["requirement_id"], requirement["reason"]),
            )


def add_risk(
    conn: sqlite3.Connection,
    *,
    description: str,
    level: str,
    analysis_id: int,
    requirement_ids: list[str],
) -> str:
    with transaction(conn):
        require_exists(conn, "analysis", "id", analysis_id, "analysis")
        for requirement_id in requirement_ids:
            require_exists(conn, "requirement", "id", requirement_id, "requirement")
        risk_id = next_id(conn, "RSK")
        conn.execute(
            "INSERT INTO risk (id, description, level, analysis_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (risk_id, description, level, analysis_id, utc_now()),
        )
        for requirement_id in requirement_ids:
            conn.execute(
                "INSERT INTO risk_requirement (risk_id, requirement_id) VALUES (?, ?)", (risk_id, requirement_id)
            )
    return risk_id


def get_analysis(conn: sqlite3.Connection, analysis_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM analysis WHERE id = ?", (analysis_id,)).fetchone()


def list_modules(conn: sqlite3.Connection, analysis_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM analysis_module WHERE analysis_id = ? ORDER BY module", (analysis_id,)
    ).fetchall()


def latest_analysis(conn: sqlite3.Connection, base_commit: str, candidate_commit: str) -> int | None:
    """The latest analysis of a version pair: the one whose commits equal them."""
    row = conn.execute(
        "SELECT id FROM analysis WHERE base_commit = ? AND candidate_commit = ? ORDER BY id DESC LIMIT 1",
        (base_commit, candidate_commit),
    ).fetchone()
    return row["id"] if row else None


def list_files(conn: sqlite3.Connection, analysis_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM analysis_file WHERE analysis_id = ? ORDER BY path", (analysis_id,)).fetchall()


def get_file(conn: sqlite3.Connection, analysis_id: int, path: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM analysis_file WHERE analysis_id = ? AND path = ?", (analysis_id, path)
    ).fetchone()


def list_requirements(conn: sqlite3.Connection, analysis_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM analysis_requirement WHERE analysis_id = ? ORDER BY requirement_id", (analysis_id,)
    ).fetchall()


def list_risks(conn: sqlite3.Connection) -> list[dict]:
    """Every risk, oldest first, with the IDs of its requirements."""
    risks = []
    for row in conn.execute("SELECT * FROM risk ORDER BY id").fetchall():
        requirement_ids = [
            link["requirement_id"]
            for link in conn.execute(
                "SELECT requirement_id FROM risk_requirement WHERE risk_id = ? ORDER BY requirement_id", (row["id"],)
            ).fetchall()
        ]
        risks.append({**dict(row), "requirement_ids": requirement_ids})
    return risks
