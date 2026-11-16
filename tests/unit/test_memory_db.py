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
