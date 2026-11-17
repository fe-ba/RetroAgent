"""Non-interactive mode, ``retro -p "<prompt>"`` (runtime.md, Non-interactive mode; cli.md, Exit codes).

Code ``4`` and the field ``denied`` count only the calls refused by the mode, by a permission or by a missing approval
of the project commands; a call refused because it is outside the tools of the step does not count.
"""

import json

import pytest
from fixtures.agent_session import USER_CONFIG, answer, call, calls, write_user_config

from retroagent.cli.main import main
from retroagent.llm import FakeProvider, ProviderUnavailable
from retroagent.memory import connect

FIELDS = {"result", "session_id", "runs", "reports", "decision", "denied", "exit_code"}
RUN_MISSING = {"version": "candidate", "scope": "selected", "test_case_ids": ["TC-999"]}


def run_json(project, *argv) -> tuple[int, dict]:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(["-C", str(project), "--output-format", "json", *argv])
    output = json.loads(buffer.getvalue())
    assert set(output) == FIELDS and output["exit_code"] == code
    return code, output


def test_a_free_message_prints_the_answer(agent_project, fake_model, capsys):
    provider = fake_model(FakeProvider([answer("# Title\n\nThe **answer**.")]))
    assert main(["-C", str(agent_project), "-p", "What is this project?"]) == 0
    assert capsys.readouterr().out == "# Title\n\nThe **answer**.\n"  # Markdown source, so it can be piped
    assert provider.requests[0].messages[1].content == "What is this project?"
    assert len(provider.requests[0].tools) > 10  # a free message has every tool of the mode


def test_a_free_message_in_json(agent_project, fake_model):
    fake_model(FakeProvider([answer("Done.")]))
    code, output = run_json(agent_project, "-p", "Hello.")
    assert code == 0
    assert output["result"] == "Done." and output["runs"] == [] and output["reports"] == []
    assert output["decision"] is None and output["denied"] == 0 and isinstance(output["session_id"], int)


def test_a_direct_command_in_text_and_json(agent_project, fake_model, capsys):
    provider = fake_model(FakeProvider())
    assert main(["-C", str(agent_project), "-p", "/mcp"]) == 0
    assert "test_runner" in capsys.readouterr().out
    code, output = run_json(agent_project, "-p", "/status")
    assert code == 0 and "Model calls" in output["result"] and "Baseline" in output["result"]
    assert provider.requests == []


def test_a_model_command_in_json(agent_project, fake_model):
    from fixtures.agent_session import Scripted, analyze_script

    fake_model(Scripted(analyze_script("Impact recorded.")))
    code, output = run_json(agent_project, "-p", "/analyze v1.0 v1.1")
    assert (code, output["result"], output["denied"]) == (0, "Impact recorded.", 0)


def test_a_tool_outside_the_step_is_refused_and_the_session_still_exits_0(agent_project, fake_model):
    from fixtures.agent_session import Scripted, analyze_script

    outside = call("test_runner__run_tests", RUN_MISSING)
    fake_model(Scripted([calls(outside), *analyze_script("Impact recorded.")]))
    code, output = run_json(agent_project, "--trust-commands", "--mode", "auto", "-p", "/analyze")
    assert (code, output["denied"]) == (0, 0)
    assert output["result"] == "Impact recorded."
    conn = connect(agent_project)
    try:
        row = conn.execute(
            "SELECT outcome, error FROM tool_call WHERE session_id = ? AND tool = 'run_tests'", (output["session_id"],)
        ).fetchone()
    finally:
        conn.close()
    assert row["outcome"] == "denied" and "is not a tool of the step analyze" in row["error"]


def test_run_tests_refused_for_lack_of_permission_exits_4(agent_project, fake_model):
    fake_model(FakeProvider([calls(call("test_runner__run_tests", RUN_MISSING)), answer("I could not run them.")]))
    code, output = run_json(agent_project, "--trust-commands", "-p", "Run the test TC-999.")  # mode default
    assert (code, output["denied"], output["result"]) == (4, 1, "I could not run them.")


def test_direct_run_without_approved_commands_exits_4(agent_project, fake_model, capsys):
    fake_model(FakeProvider())
    assert main(["-C", str(agent_project), "--mode", "auto", "-p", "/run TC-999"]) == 4
    assert "not approved" in capsys.readouterr().err


def test_a_model_error_exits_1(agent_project, fake_model, capsys):
    fake_model(FakeProvider([ProviderUnavailable("the provider is unavailable after 3 retries")]))
    assert main(["-C", str(agent_project), "-p", "Hello."]) == 1
    assert "unavailable after 3 retries" in capsys.readouterr().err


def test_the_iteration_limit_is_a_runtime_error(agent_project, fake_model, tmp_path, monkeypatch):
    home = tmp_path / "home"
    write_user_config(home, "agent:\n  max_iterations: 2\n")
    monkeypatch.setenv("RETRO_HOME", str(home))
    fake_model(FakeProvider([calls(call("memory__get_requirements"))] * 2))
    code, output = run_json(agent_project, "-p", "Loop.")
    assert code == 1 and "agent.max_iterations" in output["result"]


@pytest.mark.parametrize(
    "config",
    [USER_CONFIG.replace("model: local\n", ""), ""],
    ids=["profiles-but-no-model", "no-profile"],
)
def test_no_model_set_exits_2(agent_project, fake_model, tmp_path, monkeypatch, capsys, config):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(config)
    monkeypatch.setenv("RETRO_HOME", str(home))
    fake_model(FakeProvider())
    assert main(["-C", str(agent_project), "-p", "Hello."]) == 2
    assert "no model is set" in capsys.readouterr().err


def test_lang_and_retro_lang_set_the_language_of_the_state_message(agent_project, fake_model, monkeypatch):
    provider = fake_model(FakeProvider([answer(), answer()]))
    monkeypatch.setenv("RETRO_LANG", "fr")
    main(["-C", str(agent_project), "-p", "Hello."])
    main(["-C", str(agent_project), "--lang", "es", "-p", "Hello."])
    states = [request.messages[-1].content for request in provider.requests]
    assert "Language: Write responses and agent sections in `fr`." in states[0]
    assert "Language: Write responses and agent sections in `es`." in states[1]
