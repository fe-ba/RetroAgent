"""Requirements: tables ``requirement`` and ``requirement_change``.

Identifiers come from the requirement documents (``REQ-NNN`` in the heading), not from a sequence.
"""

import sqlite3

from retroagent.memory.db import require_exists, transaction, utc_now


def add_requirement(
    conn: sqlite3.Connection,
    *,
    id: str,
    title: str,
    description: str,
    source_file: str,
    priority: str | None = None,
    since: str | None = None,
    removed: str | None = None,
) -> str:
    with transaction(conn):
        conn.execute(
            "INSERT INTO requirement (id, title, description, priority, since, removed, source_file, synced_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, title, description, priority, since, removed, source_file, utc_now()),
        )
    return id


def add_requirement_change(conn: sqlite3.Connection, *, requirement_id: str, version: str, description: str) -> None:
    with transaction(conn):
        require_exists(conn, "requirement", "id", requirement_id, "requirement")
        conn.execute(
            "INSERT INTO requirement_change (requirement_id, version, description) VALUES (?, ?, ?)",
            (requirement_id, version, description),
        )


def get_requirement(conn: sqlite3.Connection, requirement_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM requirement WHERE id = ?", (requirement_id,)).fetchone()
