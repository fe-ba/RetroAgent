"""Recovery (runtime.md, Testing): a run left ``running``, a leftover worktree and a lock file in place, then a new
session starts. No test command runs."""

import os
import subprocess

import pytest
from fixtures.example_project import example_project, start

from retroagent.config import worktrees_dir
from retroagent.memory import connect, execution, sessions
from retroagent.servers.test_runner import worktree


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def git_worktree_entries(path):
    metadata = path / ".git" / "worktrees"
    return sorted(p.name for p in metadata.iterdir()) if metadata.is_dir() else []


@pytest.fixture
def crashed(tmp_path_factory, pip_cache):
    """What a session killed during a run leaves behind."""
    with example_project(tmp_path_factory, pip_cache) as path:
        commit = git(path, "rev-parse", "v1.0^{commit}").strip()
        conn = connect(path)
        session_id = sessions.start_session(conn, model="none", interactive=True, result_char_limit=20000)
        run_id = execution.start_run(
            conn, version_role="base", ref="v1.0", commit=commit, scope="all", command="-", session_id=session_id
        )
        conn.close()
        leftover = worktree.create(path, commit)
        (path / ".retro" / "retro.lock").write_text("999999999\n")
        assert leftover.is_dir() and len(git_worktree_entries(path)) == 1
        yield path, session_id, run_id, leftover


def test_a_new_session_recovers(crashed):
    path, crashed_session, run_id, leftover = crashed

    with start(path) as session:
        assert session.recovered_runs == [run_id]
        assert (path / ".retro" / "retro.lock").read_text() == f"{os.getpid()}\n"
        run = execution.get_run(session.conn, run_id)
        assert run["status"] == "interrupted"
        assert run["error"].startswith("session: the session that started the run ended before it")
        assert run["ended_at"] is not None
        assert execution.list_executions(session.conn, run_id) == []  # no execution is added
        assert sessions.get_session(session.conn, crashed_session)["ended_at"] is None  # its record is not changed

    assert not leftover.exists()
    assert not any(worktrees_dir(path).iterdir())
    assert git_worktree_entries(path) == []
    assert git(path, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_metadata_whose_worktree_directory_is_gone_is_removed(crashed):
    path, _, _, leftover = crashed
    subprocess.run(["rm", "-rf", str(leftover)], check=True)
    assert len(git_worktree_entries(path)) == 1

    with start(path):
        assert git_worktree_entries(path) == []
