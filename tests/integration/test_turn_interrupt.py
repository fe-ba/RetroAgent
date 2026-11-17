"""Interruption of the current model call or tool call (runtime.md, Interruption).

During ``run_tests`` the server that runs it is stopped, which ends the process groups of the run and stores it as
``interrupted`` (the stop path of the server), and is started again for the rest of the session.
"""

import threading
import time

from fixtures.agent_session import answer, call, calls, tool_results, tool_rows

from retroagent.config import worktrees_dir
from retroagent.llm import FakeProvider
from retroagent.memory import connect, execution
from retroagent.runtime.turn import NOT_COMPLETED, run_turn
from retroagent.servers.errors import ToolError


class Blocking(FakeProvider):
    """A provider whose first call sets ``interrupt`` and then blocks until the test releases it."""

    def __init__(self, interrupt: threading.Event):
        super().__init__()
        self.interrupt, self.release = interrupt, threading.Event()

    def complete(self, request):
        self.requests.append(request)
        self.interrupt.set()
        self.release.wait(30)
        raise AssertionError("the turn should not have waited for this call")


def test_an_interrupted_model_call_ends_the_turn_and_keeps_the_user_message(agent):
    interrupt = threading.Event()
    provider = Blocking(interrupt)
    try:
        result = run_turn(agent, "Analyze.", provider=provider, client=agent.client, ask=None, interrupt=interrupt)
    finally:
        provider.release.set()
    assert result.interrupted
    assert [(m.role, m.content) for m in agent.conversation.messages] == [("user", "Analyze.")]
    assert tool_rows(agent.conn, agent.id) == []


def test_an_interruption_between_tool_calls_answers_the_rest_as_not_completed(agent):
    interrupt = threading.Event()
    first, second = call("git__resolve_ref", {"ref": "v1.0"}), call("git__resolve_ref", {"ref": "v1.1"})
    events = []

    def listener(event):
        events.append(event)
        if type(event).__name__ == "ToolCalled":
            interrupt.set()  # the user presses Esc while the first result is shown

    result = run_turn(
        agent,
        "Go.",
        provider=FakeProvider([calls(first, second), answer()]),
        client=agent.client,
        ask=None,
        listener=listener,
        interrupt=interrupt,
    )
    assert result.interrupted
    rows = tool_rows(agent.conn, agent.id)
    assert [(r["outcome"], r["error"]) for r in rows] == [("ok", None), ("error", NOT_COMPLETED)]
    results = tool_results(agent.conversation)
    assert results[second.id] == NOT_COMPLETED and first.id in results


def running_run(project, timeout=600):
    """Wait until a run is ``running`` with its worktree in place, as the server writes it."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        conn = connect(project)
        try:
            runs = execution.running_runs(conn)
        finally:
            conn.close()
        here = worktrees_dir(project)
        if runs and here.is_dir() and any(here.iterdir()):
            return runs[0]["id"]
        time.sleep(0.2)
    raise AssertionError("no run started")


def test_an_interrupted_run_tests_ends_the_run_interrupted_and_the_server_answers_again(agent):
    agent.mode = "auto"
    interrupt = threading.Event()
    run_call = call("test_runner__run_tests", {"version": "base", "scope": "all"})
    after = call("git__resolve_ref", {"ref": "v1.0"})
    seen: dict = {}

    def press_escape():
        seen["run_id"] = running_run(agent.project_dir)
        interrupt.set()

    watcher = threading.Thread(target=press_escape, daemon=True)
    watcher.start()
    result = run_turn(
        agent,
        "Run everything.",
        provider=FakeProvider([calls(run_call, after), answer("never")]),
        client=agent.client,
        ask=None,
        interrupt=interrupt,
    )
    watcher.join(5)

    assert result.interrupted
    run = execution.get_run(agent.conn, seen["run_id"])
    assert run["status"] == "interrupted"
    assert not worktrees_dir(agent.project_dir).exists() or not any(worktrees_dir(agent.project_dir).iterdir())
    rows = tool_rows(agent.conn, agent.id)
    assert [(r["tool"], r["outcome"], r["error"]) for r in rows] == [
        ("run_tests", "error", NOT_COMPLETED),
        ("resolve_ref", "error", NOT_COMPLETED),
    ]
    assert all(r["ended_at"] for r in rows)
    results = tool_results(agent.conversation)
    assert results[run_call.id] == NOT_COMPLETED and results[after.id] == NOT_COMPLETED
    # The server was started again: it answers, here with an error of the tool, not with unavailable.
    try:
        agent.client.call(
            "test_runner", "run_tests", {"version": "base", "scope": "selected", "test_case_ids": ["TC-999"]}
        )
    except ToolError as error:
        assert error.code == "not_found"
    else:
        raise AssertionError("TC-999 does not exist")
