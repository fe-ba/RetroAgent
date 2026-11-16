import pytest

from retroagent.memory import transaction


def test_foreign_keys_are_enforced(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(Exception, match="FOREIGN KEY"):
        conn.execute("INSERT INTO requirement_change VALUES ('REQ-999', 'v1.1', 'x')")


def test_transaction_commits_on_success(conn):
    with transaction(conn):
        conn.execute("INSERT INTO session (started_at, model, interactive, result_char_limit) VALUES ('t', 'm', 0, 1)")
    assert not conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1


def test_transaction_rolls_back_on_error(conn):
    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute(
                "INSERT INTO session (started_at, model, interactive, result_char_limit) VALUES ('t', 'm', 0, 1)"
            )
            raise RuntimeError("boom")
    assert not conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 0


def test_nested_transaction_rolls_back_only_the_inner_part(conn):
    insert = "INSERT INTO session (started_at, model, interactive, result_char_limit) VALUES ('t', 'm', 0, 1)"
    with transaction(conn):
        conn.execute(insert)
        with pytest.raises(RuntimeError):
            with transaction(conn):
                conn.execute(insert)
                raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1


def test_timestamps_are_utc_with_milliseconds():
    import re

    from retroagent.memory.db import utc_now

    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00", utc_now())


def test_evaluation_needs_a_decision_and_its_details(conn, build):
    run_id = build.run()
    columns = "run_id, thresholds, metrics, criteria, decision, decision_details, tool_version, created_at"
    insert = f"INSERT INTO evaluation ({columns}) VALUES (?, '{{}}', '{{}}', '[]', ?, ?, '0.1.0', 't')"
    with pytest.raises(Exception, match="NOT NULL"):
        conn.execute(insert, (run_id, None, "{}"))
    with pytest.raises(Exception, match="NOT NULL"):
        conn.execute(insert, (run_id, "release", None))
    with pytest.raises(Exception, match="CHECK"):
        conn.execute(insert, (run_id, "maybe", "{}"))
