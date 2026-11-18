"""``/clear``, ``/mode``, ``/model``, ``/status``, ``/skills``, ``/mcp`` and ``/help`` change or show the session state
(runtime.md, Session state); the next state message shows the change."""

import dataclasses
import io

import pytest
from fixtures.agent_session import answer, call, calls
from rich.console import Console

from retroagent.cli.interactive import Shell
from retroagent.llm import FakeProvider, Message
from retroagent.memory import sessions

OTHER = "other"


def console() -> Console:
    return Console(file=io.StringIO(), record=True, width=200, color_system=None)


@pytest.fixture
def shell(agent):
    return Shell(agent, console(), console())


def text(shell: Shell) -> str:
    return shell.out.export_text(clear=False) + shell.err.export_text(clear=False)


def state_of(request) -> str:
    return request.messages[-1].content


@pytest.fixture
def two_models(agent):
    """A second profile, ``other``, and a provider for each profile."""
    profile = {**agent.profile, "name": "other-model"}
    agent.config = dataclasses.replace(agent.config, models={**agent.config.models, OTHER: profile})
    providers = {"test-model": FakeProvider([answer("First.")]), "other-model": FakeProvider([answer("Second.")])}
    agent.provider = providers["test-model"]
    agent.provider_factory = lambda profile, on_wait: providers[profile["name"]]
    return providers


def test_clear_empties_the_conversation_and_the_loaded_skill(agent, shell):
    agent.conversation.messages = [Message("user", "Hello."), Message("assistant", "Hi.")]
    agent.conversation.loaded_skill, agent.conversation.loaded_skill_call = "impact-analysis", "call-1"
    assert not shell.handle("/clear").usage_error
    assert agent.conversation.messages == []
    assert (agent.conversation.loaded_skill, agent.conversation.loaded_skill_call) == (None, None)
    assert "The conversation is cleared." in text(shell)


def test_mode_changes_the_state_message_and_the_tools(agent, shell):
    shell.handle("/mode")
    assert "Mode: default" in text(shell)
    shell.handle("/mode plan")
    assert agent.mode == "plan"
    provider = FakeProvider([answer()])
    agent.provider = provider
    shell.handle("What can you do?")
    request = provider.requests[0]
    assert "Mode: plan" in state_of(request)
    assert "test_runner__run_tests" not in {tool.name for tool in request.tools}
    assert shell.handle("/mode fast").usage_error and agent.mode == "plan"


def test_model_switches_the_provider_and_keeps_the_conversation(agent, shell, two_models):
    shell.handle("First question.")
    shell.handle(f"/model {OTHER}")
    assert agent.profile_name == OTHER and agent.model == "ollama/other-model"
    assert "Model: ollama/other-model, local" in text(shell)
    assert sessions.get_session(agent.conn, agent.id)["model"] == "ollama/other-model"
    shell.handle("Second question.")
    request = two_models["other-model"].requests[0]
    contents = [m.content for m in request.messages]
    assert "First question." in contents and "First." in contents and "Second question." in contents
    assert "Model: ollama/other-model" in state_of(request)
    assert two_models["test-model"].remaining == 0


def test_model_shows_the_current_profile(agent, shell, two_models):
    shell.handle("/model")
    assert "Model profile: local." in text(shell) and f"Profiles: local, {OTHER}" in text(shell)


def test_a_model_that_cannot_be_used_leaves_the_current_one(agent, shell, two_models, monkeypatch):
    assert shell.handle("/model nowhere").usage_error
    hosted = {**agent.profile, "provider": "google", "name": "hosted", "api_key_env": "RETRO_TEST_NO_SUCH_KEY"}
    agent.config = dataclasses.replace(agent.config, models={**agent.config.models, "hosted": hosted})
    monkeypatch.delenv("RETRO_TEST_NO_SUCH_KEY", raising=False)
    assert shell.handle("/model hosted").usage_error
    assert "RETRO_TEST_NO_SUCH_KEY" in text(shell)
    assert agent.profile_name == "local" and agent.model == "ollama/test-model"
    assert sessions.get_session(agent.conn, agent.id)["model"] == "ollama/test-model"


def test_status_shows_the_mode_and_the_model_calls_and_tokens_of_the_session(agent, shell):
    agent.provider = FakeProvider([calls(call("memory__get_requirements")), answer("Done.")])
    shell.handle("Read the requirements.")
    agent.mode = "auto"
    shell.handle("/status")
    output = text(shell)
    calls_line = next(line for line in output.splitlines() if "Model calls" in line)
    assert calls_line.split("│")[2].strip() == "2"
    tokens = f"{agent.usage.input_tokens:,} input, {agent.usage.output_tokens:,} output"
    assert agent.usage.input_tokens > 0 and tokens in output
    assert next(line for line in output.splitlines() if "Mode" in line).split("│")[2].strip() == "auto"


def test_skills_mcp_and_help_list_what_exists(shell):
    shell.handle("/skills")
    shell.handle("/mcp")
    shell.handle("/help")
    shell.handle("/help analyze")
    output = text(shell)
    for skill in ("impact-analysis", "test-selection", "test-design", "failure-triage", "test-reporting"):
        assert skill in output
    assert "bundled" in output
    for server in ("git", "memory", "test_runner", "reports", "runtime (built in, not an MCP server)"):
        assert server in output
    assert "analyze_changes" in output and "set_versions" in output
    assert "/cycle [base] [candidate]" in output and "Not available yet in this build." not in output
    assert shell.handle("/help nowhere").usage_error


def test_a_direct_command_is_not_added_to_the_conversation(agent, shell):
    for line in ("/status", "/history", "/mode", "/skills", "/mcp", "/help"):
        shell.handle(line)
    assert agent.conversation.messages == []


def test_init_in_a_session_keeps_existing_files(agent, shell):
    before = (agent.project_dir / ".retro" / "config.yaml").read_bytes()
    assert not shell.handle("/init").usage_error
    assert "Nothing to create: RETRO.md, .retro/config.yaml, .retro/.gitignore exist and are kept." in text(shell)
    assert (agent.project_dir / ".retro" / "config.yaml").read_bytes() == before
