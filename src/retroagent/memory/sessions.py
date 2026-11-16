"""Sessions and audit: tables ``session`` and ``tool_call``."""

import sqlite3

from retroagent.memory.db import transaction, utc_now


def start_session(
    conn: sqlite3.Connection,
    *,
    model: str,
    interactive: bool,
    result_char_limit: int,
    base_ref: str | None = None,
    base_commit: str | None = None,
    candidate_ref: str | None = None,
    candidate_commit: str | None = None,
) -> int:
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO session (started_at, model, interactive, base_ref, base_commit, candidate_ref,"
            " candidate_commit, result_char_limit) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                utc_now(),
                model,
                int(interactive),
                base_ref,
                base_commit,
                candidate_ref,
                candidate_commit,
                result_char_limit,
            ),
        )
        return cursor.lastrowid


def get_session(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM session WHERE id = ?", (session_id,)).fetchone()


def record_tool_call(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    server: str,
    tool: str,
    arguments: str,
    outcome: str,
    error: str | None = None,
) -> int:
    now = utc_now()
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO tool_call (session_id, server, tool, arguments, outcome, error, started_at, ended_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, server, tool, arguments, outcome, error, now, now),
        )
        return cursor.lastrowid
