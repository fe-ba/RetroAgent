"""Schema version and migrations of the project database."""

import sqlite3
from importlib import resources
from pathlib import Path

import retroagent
from retroagent.memory.errors import SchemaTooNew

SCHEMA_VERSION = 4

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
    # The test cases a suite leaves out, with the reason (save_suite decides every test case of an impacted
    # requirement).
    3: """
CREATE TABLE suite_left_out (
    suite_id     INTEGER NOT NULL REFERENCES suite (id),
    test_case_id TEXT NOT NULL REFERENCES test_case (id),
    reason       TEXT NOT NULL,
    PRIMARY KEY (suite_id, test_case_id)
);

CREATE TRIGGER inv_11_suite_left_out BEFORE DELETE ON suite_left_out
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
""",
    # triage.confirmed (save_triage keeps a classification that a soft check refused with confirm). The table is
    # rebuilt, so that the column has the place and the text it has in schema.sql; dropping the old table drops its
    # triggers without firing them, and they are created again on the new one.
    4: """
ALTER TABLE triage RENAME TO triage_old;

CREATE TABLE triage (
    id             INTEGER PRIMARY KEY,
    execution_id   INTEGER NOT NULL REFERENCES test_execution (id),
    classification TEXT NOT NULL
                   CHECK (classification IN
                          ('regression', 'expected_change', 'flaky', 'environment', 'test_defect', 'pre_existing')),
    justification  TEXT NOT NULL,
    confirmed      INTEGER NOT NULL DEFAULT 0 CHECK (confirmed IN (0, 1)),
    triaged_by     TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

INSERT INTO triage (id, execution_id, classification, justification, confirmed, triaged_by, created_at)
SELECT id, execution_id, classification, justification, 0, triaged_by, created_at FROM triage_old;

DROP TABLE triage_old;

CREATE TRIGGER inv_08_triage_of_failure
BEFORE INSERT ON triage
WHEN COALESCE((SELECT result FROM test_execution WHERE id = NEW.execution_id), '') NOT IN ('failed', 'error')
BEGIN
    SELECT RAISE(ABORT, 'INV-08: a triage refers only to an execution with result failed or error');
END;

CREATE TRIGGER inv_10_triage_is_final
BEFORE UPDATE ON triage
BEGIN
    SELECT RAISE(ABORT, 'INV-10: a triage is never updated');
END;

CREATE TRIGGER inv_11_triage BEFORE DELETE ON triage
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
