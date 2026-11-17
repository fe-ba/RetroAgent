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


def set_versions(
    conn: sqlite3.Connection,
    session_id: int,
    *,
    base_ref: str | None,
    base_commit: str | None,
    candidate_ref: str | None,
    candidate_commit: str | None,
) -> None:
    """Write the session versions. A ref is written together with its commit, never one without the other."""
    for role, ref, commit in (("base", base_ref, base_commit), ("candidate", candidate_ref, candidate_commit)):
        if (ref is None) != (commit is None):
            raise ValueError(f"the {role} ref and its commit are written together")
    with transaction(conn):
        conn.execute(
            "UPDATE session SET base_ref = ?, base_commit = ?, candidate_ref = ?, candidate_commit = ? WHERE id = ?",
            (base_ref, base_commit, candidate_ref, candidate_commit, session_id),
        )


def set_model(conn: sqlite3.Connection, session_id: int, model: str) -> None:
    """The model in use, ``<provider>/<model name>``, after ``/model`` switched it."""
    with transaction(conn):
        conn.execute("UPDATE session SET model = ? WHERE id = ?", (model, session_id))


def set_result_limit(conn: sqlite3.Connection, session_id: int, result_char_limit: int) -> None:
    """The largest tool result of the session, once the context window of the model is known."""
    with transaction(conn):
        conn.execute("UPDATE session SET result_char_limit = ? WHERE id = ?", (result_char_limit, session_id))


def end_session(conn: sqlite3.Connection, session_id: int) -> None:
    with transaction(conn):
        conn.execute("UPDATE session SET ended_at = ? WHERE id = ? AND ended_at IS NULL", (utc_now(), session_id))


def record_tool_call(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    server: str,
    tool: str,
    arguments: str,
    outcome: str,
    error: str | None = None,
    started_at: str | None = None,
) -> int:
    """Store one tool call once it is answered. ``started_at`` defaults to now, for calls that take no time."""
    now = utc_now()
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO tool_call (session_id, server, tool, arguments, outcome, error, started_at, ended_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, server, tool, arguments, outcome, error, started_at or now, now),
        )
        return cursor.lastrowid


# What a tool_call row says until the call is answered: a session that dies during the call leaves it so.
UNANSWERED = "no answer: the session ended during the call"


def start_tool_call(conn: sqlite3.Connection, *, session_id: int, server: str, tool: str, arguments: str) -> int:
    """Store a tool call before it is dispatched, as ``error`` with ``UNANSWERED`` and no ``ended_at``."""
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO tool_call (session_id, server, tool, arguments, outcome, error, started_at)"
            " VALUES (?, ?, ?, ?, 'error', ?, ?)",
            (session_id, server, tool, arguments, UNANSWERED, utc_now()),
        )
        return cursor.lastrowid


def finish_tool_call(conn: sqlite3.Connection, tool_call_id: int, *, outcome: str, error: str | None = None) -> None:
    """Store the outcome of a tool call once it is answered."""
    with transaction(conn):
        conn.execute(
            "UPDATE tool_call SET outcome = ?, error = ?, ended_at = ? WHERE id = ?",
            (outcome, error, utc_now(), tool_call_id),
        )
