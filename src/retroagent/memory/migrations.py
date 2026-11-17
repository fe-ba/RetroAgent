"""Schema version and migrations of the project database."""

import sqlite3
from importlib import resources
from pathlib import Path

import retroagent
from retroagent.memory.errors import SchemaTooNew

SCHEMA_VERSION = 2

# SQL script that takes a database from version N - 1 to version N, keyed by N. Each one creates exactly what
# schema.sql has for that version, with the same text, so a migrated database equals a new one.
MIGRATIONS: dict[int, str] = {
    # The requirements judged not impacted by an analysis (save_impact decides every requirement in effect).
    2: """
CREATE TABLE analysis_requirement_not_impacted (
    analysis_id    INTEGER NOT NULL REFERENCES analysis (id),
    requirement_id TEXT NOT NULL REFERENCES requirement (id),
    reason         TEXT NOT NULL,
    PRIMARY KEY (analysis_id, requirement_id)
);

CREATE TRIGGER inv_10_analysis_requirement_not_impacted_is_final
BEFORE UPDATE ON analysis_requirement_not_impacted
BEGIN
    SELECT RAISE(ABORT, 'INV-10: the impact of an analysis is never updated');
END;

CREATE TRIGGER inv_11_analysis_requirement_not_impacted BEFORE DELETE ON analysis_requirement_not_impacted
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
""",
}


def _schema_sql() -> str:
    return resources.files("retroagent.memory").joinpath("schema.sql").read_text(encoding="utf-8")


def _stored_version(conn: sqlite3.Connection) -> int | None:
    has_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_info'").fetchone()
    if has_table is None:
        return None
    row = conn.execute('SELECT "value" FROM schema_info WHERE "key" = \'schema_version\'').fetchone()
    return int(row[0])


def _create(conn: sqlite3.Connection) -> None:
    script = (
        "BEGIN;\n"
        + _schema_sql()
        + f"\nINSERT INTO schema_info (\"key\", \"value\") VALUES ('schema_version', '{SCHEMA_VERSION}');\n"
        + f"INSERT INTO schema_info (\"key\", \"value\") VALUES ('created_by', '{retroagent.__version__}');\n"
        + "COMMIT;"
    )
    conn.executescript(script)


def _backup(conn: sqlite3.Connection, version: int) -> None:
    main_file = conn.execute("PRAGMA database_list").fetchone()[2]
    backup = sqlite3.connect(Path(main_file).with_name(f"retro.db.bak-{version}"))
    try:
        conn.backup(backup)
    finally:
        backup.close()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the schema in a new database; migrate an older one after a backup; refuse a newer one."""
    stored = _stored_version(conn)
    if stored is None:
        _create(conn)
        return
    if stored > SCHEMA_VERSION:
        raise SchemaTooNew(
            f"the database has schema version {stored} but this RetroAgent supports up to {SCHEMA_VERSION}; "
            "update RetroAgent"
        )
    if stored < SCHEMA_VERSION:
        _backup(conn, stored)
        for version in range(stored + 1, SCHEMA_VERSION + 1):
            conn.executescript(
                "BEGIN;\n"
                + MIGRATIONS[version]
                + f"\nUPDATE schema_info SET \"value\" = '{version}' WHERE \"key\" = 'schema_version';\nCOMMIT;"
            )
