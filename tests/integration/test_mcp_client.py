"""The MCP client: the environment of the servers, their tools, and a server that dies, does not answer or cannot
start, which is an error the caller can report and never a hang."""

import os
import signal
import sys
import time

import mcp.client.stdio as mcp_stdio
import pytest
from fixtures.example_project import example_project
from fixtures.mcp_project import children, environment_of, error_of, open_session

from retroagent.config import load_config, retro_home
from retroagent.context.tools import tool_definitions
from retroagent.mcp_client import BUNDLED, Client, run_tests_timeout
from retroagent.mcp_client import client as client_module
from retroagent.memory import connect, execution

pytestmark = pytest.mark.skipif(not os.path.isdir("/proc"), reason="reads /proc")

USER_CONFIG = """models:
  mine:
    provider: google
    name: some-model
    api_key_env: MY_PROVIDER_KEY
"""


@pytest.fixture
def shop(tmp_path_factory, pip_cache):
    with example_project(tmp_path_factory, pip_cache) as path:
        yield path


def test_no_model_credential_reaches_a_server(shop, monkeypatch):
    (retro_home() / "config.yaml").write_text(USER_CONFIG, encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini")
    monkeypatch.setenv("MY_PROVIDER_KEY", "secret-profile")
    monkeypatch.setenv("RETRO_TEST_MARKER", "kept")
    credentials = load_config(shop).credential_env_names
    assert credentials == ("MY_PROVIDER_KEY",)
    with Client(shop, open_session(shop), credentials):
        servers = children(b"retroagent.servers.")
        assert len(servers) == len(BUNDLED)
        for pid in servers:
            environment = environment_of(pid)
            assert "GEMINI_API_KEY" not in environment
            assert "MY_PROVIDER_KEY" not in environment
            assert not any("secret-" in value for value in environment.values())
            assert environment["RETRO_TEST_MARKER"] == "kept"  # the rest of the environment of retro is kept
            assert environment["RETRO_HOME"] == str(retro_home())


def test_the_tools_feed_the_tool_definitions(shop):
    with Client(shop, open_session(shop)) as client:
        names = [d.name for d in tool_definitions(client.tools(), mode="plan", tool_set="analyze")]
    # the read tools of git and memory, and the write tools of the analysis; never a user-only tool
    assert names == [
        "git__analyze_changes", "git__get_diff", "git__list_files", "git__read_file", "git__resolve_ref",
        "memory__add_risk", "memory__get_analysis", "memory__get_defects", "memory__get_executions",
        "memory__get_requirements", "memory__get_risks", "memory__get_runs", "memory__get_suite",
        "memory__get_test_case_history", "memory__get_test_cases", "memory__save_impact",
        "memory__sync_requirements",
    ]  # fmt: skip


def test_stop_leaves_no_server_process(shop):
    client = Client(shop, open_session(shop))
    client.start()
    pids = children(b"retroagent.servers.")
    assert len(pids) == len(BUNDLED)
    client.stop()
    client.stop()  # a second stop does nothing
    assert children(b"retroagent.servers.") == []
    assert error_of(lambda: client.call("git", "resolve_ref", {"ref": "v1.0"})).code == "unavailable"


def test_a_server_that_dies_is_unavailable_at_once_and_is_not_restarted(shop):
    with Client(shop, open_session(shop)) as client:
        (git_server,) = children(b"retroagent.servers.git")
        os.kill(git_server, signal.SIGKILL)
        started = time.monotonic()
        error = error_of(lambda: client.call("git", "resolve_ref", {"ref": "v1.0"}))
        assert error.code == "unavailable" and "server git" in error.message
        assert time.monotonic() - started < 5
        assert error_of(lambda: client.call("git", "resolve_ref", {"ref": "v1.0"})).code == "unavailable"
        assert client.call("memory", "get_risks") == {"risks": []}  # the other servers keep working


def test_a_server_that_does_not_start_is_reported_with_its_message(shop):
    started = time.monotonic()
    error = error_of(lambda: Client(shop, 1).start())
    assert error.code == "unavailable"
    assert "retro.db does not exist" in error.message  # servers never create project memory
    open_session(shop)
    error = error_of(lambda: Client(shop, 999).start())
    assert error.code == "unavailable"
    assert "session 999 does not exist" in error.message
    assert time.monotonic() - started < 10
    assert children(b"retroagent.servers.") == []


def test_a_server_that_never_answers_is_unavailable_after_the_timeout(shop, monkeypatch):
    monkeypatch.setattr(client_module, "START_TIMEOUT", 1.0)
    silent = [sys.executable, "-c", "import sys; sys.stdin.read()"]  # reads its input and never answers
    started = time.monotonic()
    error = error_of(lambda: Client(shop, open_session(shop), commands={"silent": silent}).start())
    assert error.code == "unavailable" and "server silent" in error.message
    assert time.monotonic() - started < 10


def test_a_call_that_does_not_answer_in_time_is_unavailable_and_its_run_interrupted(shop):
    (shop / ".retro" / "config.yaml").write_text(
        "versions: {base: v1.0, candidate: v1.1}\ntests:\n  command: exec sleep 300\n", encoding="utf-8"
    )
    with Client(shop, open_session(shop)) as client:
        started = time.monotonic()
        error = error_of(
            lambda: client.call("test_runner", "run_tests", {"version": "base", "scope": "all"}, timeout=2)
        )
        assert error.code == "unavailable" and "did not answer run_tests within 2 seconds" in error.message
        assert time.monotonic() - started < 15
        assert error_of(lambda: client.call("test_runner", "run_tests", {"version": "base", "scope": "all"})).code == (
            "unavailable"
        )
    conn = connect(shop)
    assert execution.list_runs(conn, 1)[0]["status"] == "interrupted"
    conn.close()


def test_a_stop_during_a_run_is_not_cut_short_by_the_sdk(shop):
    # The SDK signals a server this long after closing its input; the client raises it so that a server stopped
    # during a run can end both process groups of the run (up to GRACE_SECONDS each) before any SIGKILL.
    assert hasattr(mcp_stdio, "PROCESS_TERMINATION_TIMEOUT"), "the SDK no longer has this constant: see client.py"
    with Client(shop, open_session(shop)):
        assert mcp_stdio.PROCESS_TERMINATION_TIMEOUT >= client_module.SHUTDOWN_WAIT > 2 * client_module.GRACE_SECONDS


def test_the_bound_of_a_run_follows_the_configuration(shop):
    config = load_config(shop)
    # setup, the test command and two reruns, each up to tests.timeout; the service; a margin.
    assert run_tests_timeout(config) == 4 * 900 + 30 + 60
