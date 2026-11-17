"""An interactive session without a terminal: the turn runs in a worker thread while ``Keys`` watches a pipe input.
Esc interrupts the model call; a permission question of the turn is answered from the main thread; with no model
set, the session asks for a profile."""

import io
import threading

import pytest
from fixtures.agent_session import USER_CONFIG, answer, call, calls, factory, tool_results
from prompt_toolkit.input import create_pipe_input
from rich.console import Console

from retroagent.cli.interactive import Keys, Shell
from retroagent.llm import FakeProvider
from retroagent.runtime import session as session_module

RUN_MISSING = {"version": "candidate", "scope": "selected", "test_case_ids": ["TC-999"]}


def console() -> Console:
    return Console(file=io.StringIO(), record=True, width=200, color_system=None)


@pytest.fixture
def terminal():
    with create_pipe_input() as pipe:
        yield pipe


class EscDuringTheCall(FakeProvider):
    """The user presses Esc while the model call is in progress; the call never returns by itself."""

    def __init__(self, terminal):
        super().__init__()
        self.terminal, self.release = terminal, threading.Event()

    def complete(self, request):
        self.requests.append(request)
        self.terminal.send_text("\x1b")
        self.release.wait(30)
        raise AssertionError("the turn should not have waited for this call")


def test_esc_interrupts_the_model_call_of_a_turn(agent, terminal):
    provider = EscDuringTheCall(terminal)
    agent.provider = provider
    out = console()
    try:
        outcome = Shell(agent, out, out, keys=Keys(terminal)).handle("Analyze the change.")
    finally:
        provider.release.set()
    assert outcome.runtime_error and not outcome.end
    assert "Interrupted." in out.export_text()
    assert agent.conversation.messages[0].content == "Analyze the change."


def test_a_permission_question_of_the_turn_is_answered_with_the_keys(agent, terminal):
    run = call("test_runner__run_tests", RUN_MISSING)
    agent.provider = FakeProvider([calls(run), answer("The test case does not exist.")])
    out = console()
    threading.Timer(1.0, terminal.send_text, ["1"]).start()  # allow once, after the question is shown
    outcome = Shell(agent, out, out, keys=Keys(terminal), render_markdown=False).handle("Run TC-999.")
    text = out.export_text()
    assert "Permission needed: test_runner__run_tests needs run_tests and start_service." in text
    assert "Allow once" in text and "The test case does not exist." in text
    assert '"not_found"' in tool_results(agent.conversation)[run.id]  # dispatched: the server answered
    assert not outcome.runtime_error


def test_with_no_model_set_the_interactive_session_asks_for_a_profile(agent_project, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(USER_CONFIG.replace("model: local\n", ""))
    monkeypatch.setenv("RETRO_HOME", str(home))
    offered = []

    def choose(names):
        offered.append(names)
        return "local"

    options = session_module.Options(project=agent_project)
    with session_module.start(options, provider_factory=factory(), choose_profile=choose) as started:
        assert offered == [["local"]]
        assert started.profile_name == "local" and started.model == "ollama/test-model"
    with pytest.raises(session_module.SessionError, match="no model was chosen"):
        session_module.start(options, provider_factory=factory(), choose_profile=lambda names: None)
