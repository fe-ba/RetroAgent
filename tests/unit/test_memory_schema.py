import pathlib
import sqlite3

import pytest

from retroagent.memory import connect, database_path, migrations
from retroagent.memory.errors import SchemaTooNew

# Every table and column of spec/data-model.md.
TABLES = {
    "schema_info": ["key", "value"],
    "session": [
        "id",
        "started_at",
        "ended_at",
        "model",
        "interactive",
        "base_ref",
        "base_commit",
        "candidate_ref",
        "candidate_commit",
        "result_char_limit",
    ],
    "tool_call": ["id", "session_id", "server", "tool", "arguments", "outcome", "error", "started_at", "ended_at"],
    "requirement": [
        "id",
        "title",
        "description",
        "priority",
        "since",
        "removed",
        "source_file",
        "synced_at",
    ],
    "requirement_change": ["requirement_id", "version", "description"],
    "analysis": [
        "id",
        "base_ref",
        "base_commit",
        "candidate_ref",
        "candidate_commit",
        "session_id",
        "created_at",
    ],
    "analysis_file": ["analysis_id", "path", "old_path", "change", "lines_added", "lines_removed"],
    "analysis_module": ["analysis_id", "module", "files", "risk_level", "reason"],
    "analysis_requirement": ["analysis_id", "requirement_id", "reason"],
    "analysis_requirement_not_impacted": ["analysis_id", "requirement_id", "reason"],
    "risk": ["id", "description", "level", "analysis_id", "created_at"],
    "risk_requirement": ["risk_id", "requirement_id"],
    "test_case": [
        "id",
        "title",
        "objective",
        "priority",
        "status",
        "origin",
        "designed_by",
        "preconditions",
        "input_data",
        "steps",
        "expected_result",
        "test_id",
        "implementation",
        "revision",
        "retired_at",
        "retire_reason",
        "retired_by",
        "created_at",
        "updated_at",
    ],
    "test_case_requirement": ["test_case_id", "requirement_id", "link"],
    "suite": ["id", "analysis_id", "session_id", "created_at"],
    "suite_test_case": ["suite_id", "test_case_id", "position", "selection_reason"],
    "run": [
        "id",
        "version_role",
        "ref",
        "commit",
        "scope",
        "suite_id",
        "status",
        "command",
        "exit_code",
        "junit_path",
        "evidence_dir",
        "error",
        "session_id",
        "started_at",
        "ended_at",
    ],
    "test_execution": ["id", "run_id", "test_case_id", "status", "result", "reason", "duration", "test_revision"],
    "attempt": ["execution_id", "number", "result", "duration", "failure_message"],
    "triage": ["id", "execution_id", "classification", "justification", "triaged_by", "created_at"],
    "defect": [
        "id",
        "title",
        "severity",
        "status",
        "detected_run_id",
        "detected_at",
        "expected",
        "actual",
        "steps",
        "closed_at",
        "closed_by",
        "closed_run_id",
        "close_reason",
    ],
    "defect_execution": ["defect_id", "execution_id"],
    "evaluation": [
        "id",
        "run_id",
        "baseline_run_id",
        "full_base_run_id",
        "full_candidate_run_id",
        "analysis_id",
        "thresholds",
        "metrics",
        "criteria",
        "decision",
        "decision_details",
        "tool_version",
        "created_at",
    ],
    "report": ["id", "type", "status", "evaluation_id", "model", "path", "formats", "created_at"],
}


def test_database_from_scratch_has_every_table_and_column(tmp_path):
    assert not database_path(tmp_path).exists()
    conn = connect(tmp_path)
    assert database_path(tmp_path) == tmp_path / ".retro" / "retro.db"
    found = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert found == set(TABLES)
    for table, columns in TABLES.items():
        assert [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")] == columns, table


def test_schema_sql_is_read_through_importlib_resources():
    from importlib import resources

    sql = resources.files("retroagent.memory").joinpath("schema.sql").read_text(encoding="utf-8")
    assert migrations._schema_sql() == sql
    assert sql.count("CREATE TABLE ") == len(TABLES)
    assert "__file__" not in pathlib.Path(migrations.__file__).read_text(encoding="utf-8")


def test_schema_info_records_version_and_creator(conn):
    info = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM schema_info")}
    assert info == {"schema_version": str(migrations.SCHEMA_VERSION), "created_by": "0.1.0"}


def test_reopening_keeps_the_database(tmp_path):
    first = connect(tmp_path)
    first.execute("INSERT INTO session (started_at, model, interactive, result_char_limit) VALUES ('t', 'm', 0, 1)")
    first.close()
    second = connect(tmp_path)
    assert second.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1


def test_newer_schema_is_not_opened(tmp_path):
    connect(tmp_path).close()
    raw = sqlite3.connect(database_path(tmp_path))
    raw.execute("UPDATE schema_info SET value = '99' WHERE key = 'schema_version'")
    raw.commit()
    raw.close()
    with pytest.raises(SchemaTooNew, match="update RetroAgent"):
        connect(tmp_path)


def test_older_schema_is_backed_up_then_migrated(tmp_path, monkeypatch):
    connect(tmp_path).close()
    current = migrations.SCHEMA_VERSION
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", current + 1)
    monkeypatch.setitem(migrations.MIGRATIONS, current + 1, "CREATE TABLE added_later (x INTEGER);")
    conn = connect(tmp_path)
    assert (tmp_path / ".retro" / f"retro.db.bak-{current}").exists()
    assert conn.execute("SELECT value FROM schema_info WHERE key = 'schema_version'").fetchone()[0] == str(current + 1)
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'added_later'").fetchone()[0] == 1


def schema_objects(conn) -> set[tuple[str, str, str]]:
    return {(r[0], r[1], r[2]) for r in conn.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL")}


def test_a_version_1_database_migrates_to_version_2_and_equals_a_new_one(tmp_path):
    new = connect(tmp_path / "new")
    expected = schema_objects(new)
    new.close()
    old = tmp_path / "old"
    connect(old).close()
    raw = sqlite3.connect(database_path(old))  # what schema version 1 had: no table of not impacted requirements
    raw.executescript(
        "DROP TABLE analysis_requirement_not_impacted; UPDATE schema_info SET value = '1' WHERE key = 'schema_version';"
    )
    raw.close()
    migrated = connect(old)
    assert (old / ".retro" / "retro.db.bak-1").exists()
    assert migrated.execute("SELECT value FROM schema_info WHERE key = 'schema_version'").fetchone()[0] == "2"
    assert schema_objects(migrated) == expected


def test_enumerations_use_the_glossary_values(conn, build):
    run_id = build.run()
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE run SET scope = 'everything' WHERE id = ?", (run_id,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO defect (id, title, severity, detected_run_id, detected_at, actual)"
            " VALUES ('DEF-001', 't', 'urgent', ?, 't', 'a')",
            (run_id,),
        )


def test_unique_constraints(conn, build):
    first = build.test_case()
    conn.execute("UPDATE test_case SET test_id = 'tests.a::test_x' WHERE id = ?", (first,))
    second = build.test_case()
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("UPDATE test_case SET test_id = 'tests.a::test_x' WHERE id = ?", (second,))
    run_id = build.run()
    execution_id = build.execute(run_id, first)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        build.execute(run_id, first)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("INSERT INTO attempt (execution_id, number, result) VALUES (?, 1, 'passed')", (execution_id,))
