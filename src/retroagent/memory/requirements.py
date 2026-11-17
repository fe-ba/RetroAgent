"""Requirements: tables ``requirement`` and ``requirement_change``.

Identifiers come from the requirement documents (``REQ-NNN`` in the heading), not from a sequence.
"""

import sqlite3

from retroagent.memory import design
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


_FIELDS = ("title", "description", "priority", "since", "removed", "source_file")


def sync_requirements(conn: sqlite3.Connection, requirements: list[dict]) -> dict[str, int]:
    """Write requirements read from the documents, in one transaction, and add the missing name links of the
    project tests (project-contract.md, Traceability).

    A requirement is ``{id, title, description, source_file, priority, since, removed, changes}``, where ``changes``
    is a list of ``{version, description}``. A requirement read again gets its fields and ``synced_at`` updated; a
    change entry is added when its version and description are new. Nothing is deleted (INV-11): an entry removed
    from a document stays. Returns the counts ``read``, ``added``, ``changed`` and ``name_links_added``.
    """
    added = changed = 0
    now = utc_now()
    with transaction(conn):
        for requirement in requirements:
            values = tuple(requirement[name] for name in _FIELDS)
            existing = get_requirement(conn, requirement["id"])
            if existing is None:
                conn.execute(
                    "INSERT INTO requirement (title, description, priority, since, removed, source_file, synced_at, id)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (*values, now, requirement["id"]),
                )
                added += 1
                known = set()
            else:
                conn.execute(
                    "UPDATE requirement SET title = ?, description = ?, priority = ?, since = ?, removed = ?,"
                    " source_file = ?, synced_at = ? WHERE id = ?",
                    (*values, now, requirement["id"]),
                )
                known = {(c["version"], c["description"]) for c in list_changes(conn, requirement["id"])}
            new_changes = [c for c in requirement["changes"] if (c["version"], c["description"]) not in known]
            for change in new_changes:
                conn.execute(
                    "INSERT INTO requirement_change (requirement_id, version, description) VALUES (?, ?, ?)",
                    (requirement["id"], change["version"], change["description"]),
                )
            if existing is not None and (tuple(existing[name] for name in _FIELDS) != values or new_changes):
                changed += 1
        links = design.link_tests_by_name(conn)
    return {"read": len(requirements), "added": added, "changed": changed, "name_links_added": links}


def list_requirements(conn: sqlite3.Connection, ids: list[str] | None = None) -> list[sqlite3.Row]:
    if ids is None:
        return conn.execute("SELECT * FROM requirement ORDER BY id").fetchall()
    return [row for row in (get_requirement(conn, i) for i in ids) if row is not None]


def list_changes(conn: sqlite3.Connection, requirement_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT version, description FROM requirement_change WHERE requirement_id = ? ORDER BY rowid",
        (requirement_id,),
    ).fetchall()
