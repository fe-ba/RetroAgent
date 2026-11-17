"""``test_runner.run_tests`` through a real server process and the real client, on shop-api: a real run, and each
error code the tool can return."""

from types import SimpleNamespace

import pytest
from fixtures.example_project import example_project
from fixtures.mcp_project import error_of, open_session

from retroagent.config import retro_home, worktrees_dir
from retroagent.mcp_client import Client
from retroagent.memory import connect, execution


@pytest.fixture(scope="module")
def shop(tmp_path_factory, pip_cache):
    with example_project(tmp_path_factory, pip_cache) as path:
        with Client(path, open_session(path)) as client, Client(path, open_session(path, "v1.0", None)) as base_only:
            yield SimpleNamespace(path=path, client=client, base_only=base_only)


def runs(path) -> list:
    conn = connect(path)
    try:
        return execution.list_runs(conn, 100)
    finally:
        conn.close()


def code(client, arguments) -> str:
    return error_of(lambda: client.call("test_runner", "run_tests", arguments)).code


def test_run_tests_errors_store_no_run(shop):
    assert code(shop.client, {"version": "base", "scope": "selected"}) == "invalid_argument"
    assert code(shop.client, {"version": "base", "scope": "all", "test_case_ids": ["TC-001"]}) == "invalid_argument"
    assert code(shop.client, {"version": "head", "scope": "all"}) == "invalid_argument"
    assert code(shop.client, {"version": "base", "scope": "selected", "test_case_ids": ["TC-999"]}) == "not_found"
    assert code(shop.client, {"version": "candidate", "scope": "suite"}) == "invalid_state"  # no current suite
    assert code(shop.base_only, {"version": "candidate", "scope": "all"}) == "invalid_state"  # candidate not set
    assert runs(shop.path) == []


def test_a_worktree_that_cannot_be_created_is_execution_failed(shop):
    worktrees = retro_home() / "worktrees"
    worktrees.mkdir(parents=True, exist_ok=True)
    worktrees.chmod(0o500)
    try:
        assert code(shop.client, {"version": "base", "scope": "all"}) == "execution_failed"
    finally:
        worktrees.chmod(0o700)
    assert runs(shop.path) == []


@pytest.mark.network
def test_a_full_run_against_the_baseline(shop):
    result = shop.client.call("test_runner", "run_tests", {"version": "base", "scope": "all"})
    assert result["run_id"] == "RUN-0001"
    assert result["status"] == "completed"
    assert result["counts"] == {"executed": 22, "blocked": 0, "skipped": 0, "passed": 20, "failed": 2, "error": 0}
    assert not any(worktrees_dir(shop.path).iterdir())  # removed after the run
