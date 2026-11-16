"""The session lock between processes (runtime.md, Start step 4, and Robustness). No test command runs."""

import os
import signal
import subprocess
import sys

import pytest
from fixtures.example_project import example_project, start

from retroagent.memory import connect, execution
from retroagent.runtime.session import SessionError
from retroagent.servers.test_runner import worktree

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the holder is killed with SIGKILL")

# A session in another process that holds the lock until its standard input closes or it is killed.
HOLDER = """
import sys
from retroagent.runtime.session import Options, start
session = start(Options(project=sys.argv[1], interactive=False))
print(session.id, flush=True)
sys.stdin.read()
session.end()
"""


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def snapshot(path):
    conn = connect(path)
    try:
        tables = ("session", "run", "tool_call", "test_execution")
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        runs = [tuple(r) for r in conn.execute("SELECT id, status, error FROM run ORDER BY id")]
        sessions = [tuple(r) for r in conn.execute("SELECT * FROM session ORDER BY id")]
        return counts, runs, sessions
    finally:
        conn.close()


@pytest.fixture
def holder(tmp_path_factory, pip_cache):
    with example_project(tmp_path_factory, pip_cache) as path:
        child = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
        )
        try:
            session_id = int(child.stdout.readline())
            yield path, child, session_id
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()


def test_a_second_session_exits_2_names_the_holder_and_changes_nothing(holder):
    path, child, holder_session = holder
    # What a recovery would change, had it run without the lock: a running run and a worktree under the folder.
    commit = git(path, "rev-parse", "v1.0^{commit}").strip()
    conn = connect(path)
    run_id = execution.start_run(
        conn, version_role="base", ref="v1.0", commit=commit, scope="all", command="-", session_id=holder_session
    )
    conn.close()
    leftover = worktree.create(path, commit)
    before = snapshot(path)

    second = subprocess.run(
        [sys.executable, "-m", "retroagent.cli.main", "-C", str(path), "-p", "/status"],
        capture_output=True,
        text=True,
    )
    assert second.returncode == 2
    assert f"another session holds the lock {path / '.retro' / 'retro.lock'}: process {child.pid}" in second.stderr
    assert second.stdout == ""

    with pytest.raises(SessionError, match=f"process {child.pid}"):
        start(path, trust_commands=True)

    assert snapshot(path) == before  # no session record, no recovered run
    assert leftover.is_dir()  # no worktree removed

    # The holder crashes: the operating system releases the lock, and the file it leaves is taken over.
    os.kill(child.pid, signal.SIGKILL)
    child.wait()
    with start(path) as session:
        assert session.recovered_runs == [run_id]
        assert (path / ".retro" / "retro.lock").read_text() == f"{os.getpid()}\n"
    assert not leftover.exists()


def test_a_session_that_ends_releases_the_lock(holder):
    path, child, _ = holder
    child.stdin.close()
    assert child.wait(timeout=30) == 0
    with start(path) as session:
        assert session.recovered_runs == []
