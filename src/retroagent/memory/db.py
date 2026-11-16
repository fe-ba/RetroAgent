"""Connection to ``.retro/retro.db`` and transactions."""

import itertools
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from retroagent.memory import migrations
from retroagent.memory.errors import InvariantViolation

_savepoints = itertools.count(1)


def database_path(project_dir: str | Path) -> Path:
    return Path(project_dir) / ".retro" / "retro.db"


def connect(project_dir: str | Path) -> sqlite3.Connection:
    """Open the memory of a project, creating or migrating the database when needed.

    Foreign keys are on. Transactions are explicit: use ``transaction()``.
    """
    path = database_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        migrations.ensure_schema(conn)
    except BaseException:
        conn.close()
        raise
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Commit when the block ends, roll back everything when it raises. Nested use is a savepoint."""
    if conn.in_transaction:
        name = f"retro_sp_{next(_savepoints)}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield conn
        except BaseException:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            raise
        conn.execute(f"RELEASE {name}")
    else:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def utc_now() -> str:
    """Timestamp in ISO 8601, UTC."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def require_exists(conn: sqlite3.Connection, table: str, column: str, value, label: str) -> None:
    """INV-13: a reference made by the model must exist, otherwise the call fails."""
    row = conn.execute(f"SELECT 1 FROM {table} WHERE {column} = ?", (value,)).fetchone()
    if row is None:
        raise InvariantViolation(f"INV-13: {label} {value!r} does not exist")
