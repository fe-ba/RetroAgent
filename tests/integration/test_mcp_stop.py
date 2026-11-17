"""A server stopped in the middle of a run ends the process groups of the run and stores it as ``interrupted``
before it exits (runtime.md, Robustness): when the client stops it, and when it receives SIGTERM."""

import os
import signal
import threading
import time

import pytest
from fixtures.example_project import example_project
from fixtures.mcp_project import children, group_alive, open_session

from retroagent.config import worktrees_dir
from retroagent.mcp_client import Client
from retroagent.memory import connect, execution
from retroagent.servers.errors import ToolError

pytestmark = pytest.mark.skipif(not os.path.isdir("/proc"), reason="reads /proc")

CONFIG = """project:
  requirements: [docs/requirements.md]
versions: {base: v1.0, candidate: v1.1}
tests:
  command: echo $$ > {run_dir}/command.pid && exec sleep 300
"""


def start_run(path):
    """A client and a run in progress whose test command sleeps: the client, the thread, the outcome and the pid."""
    (path / ".retro" / "config.yaml").write_text(CONFIG, encoding="utf-8")
    client = Client(path, open_session(path))
    client.start()
    outcome: dict = {}

    def run():
        try:
            outcome["result"] = client.call("test_runner", "run_tests", {"version": "base", "scope": "all"})
        except ToolError as error:
            outcome["error"] = error

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 30
    while not list((path / ".retro" / "runs").glob("*/command.pid")):
        assert time.monotonic() < deadline, "the test command did not start"
        time.sleep(0.05)
    pid_file = next((path / ".retro" / "runs").glob("*/command.pid"))
    time.sleep(0.1)  # the file is written before the shell replaces itself with sleep
    return client, thread, outcome, int(pid_file.read_text())


def check_interrupted(path, thread, outcome, group):
    thread.join(30)
    assert not thread.is_alive()
    assert outcome["error"].code == "unavailable"
    assert not group_alive(group)
    conn = connect(path)
    (run,) = execution.list_runs(conn, 10)
    assert run["status"] == "interrupted"
    assert run["error"] == "test command: the server was stopped"
    conn.close()
    leftovers = worktrees_dir(path)
    assert not leftovers.exists() or not any(leftovers.iterdir())


def test_stop_during_a_run_ends_its_process_groups_and_stores_it_interrupted(tmp_path_factory, pip_cache):
    with example_project(tmp_path_factory, pip_cache) as path:
        client, thread, outcome, group = start_run(path)
        assert group_alive(group)
        client.stop()
        check_interrupted(path, thread, outcome, group)


def test_sigterm_during_a_run_ends_its_process_groups_and_stores_it_interrupted(tmp_path_factory, pip_cache):
    with example_project(tmp_path_factory, pip_cache) as path:
        client, thread, outcome, group = start_run(path)
        try:
            (server,) = children(b"retroagent.servers.test_runner")
            os.kill(server, signal.SIGTERM)
            check_interrupted(path, thread, outcome, group)
        finally:
            client.stop()
