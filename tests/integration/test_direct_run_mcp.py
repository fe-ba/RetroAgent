"""``/run`` as a tool call of the user: the same checks, question and ``tool_call`` row as a call of the model, and the
dispatch to the ``test_runner`` MCP server (runtime.md, Slash commands).

A dispatched call uses ``scope: selected`` and a test case that does not exist, so the server answers ``not_found``
before it creates a worktree: who answered tells a dispatched call from a refused one.
"""

import json

import pytest
from fixtures.agent_session import tool_rows
from fixtures.example_project import start

from retroagent.runtime import commands, permissions

MISSING = ("TC-999",)
DISPATCHED = ("not_found", "test case TC-999 does not exist")


class Answers:
    def __init__(self, *answers):
        self.answers, self.questions = list(answers), []

    def __call__(self, request):
        self.questions.append(request)
        return self.answers.pop(0)


@pytest.fixture
def dispatched(agent):
    """The calls the client sent to a server."""
    sent = []
    original = agent.client.call

    def spy(server, tool, arguments=None, timeout=None):
        sent.append((server, tool, dict(arguments or {})))
        return original(server, tool, arguments, timeout)

    agent.client.call = spy
    return sent


def test_the_question_shows_the_version_the_scope_the_test_cases_and_the_commands(agent, dispatched):
    answers = Answers(permissions.DENY)
    outcome = commands.run(agent, "all", "base", ask=answers)
    (question,) = answers.questions
    assert question.tool == permissions.RUN_TESTS
    assert question.permissions == ("run_tests", "start_service")  # the example configures service.start
    base = agent.versions()["base"]
    details = "\n".join(question.details)
    assert f"Version: base {base.ref} ({base.commit})" in details
    assert "Scope: all" in details
    assert "Test cases: every test of the project" in details
    for key in ("tests.setup", "tests.command", "service.start"):
        assert agent.config[key] in details
    assert (outcome.error.code, outcome.runs) == ("denied", [])
    assert dispatched == []
    row = tool_rows(agent.conn, agent.id)[-1]
    assert (row["server"], row["tool"], row["outcome"]) == ("test_runner", "run_tests", "denied")
    assert json.loads(row["arguments"]) == {"version": "base", "scope": "all"}
    assert agent.permission_refusals == 1


def test_allow_once_dispatches_to_the_server_and_asks_again(agent, dispatched):
    answers = Answers(permissions.ONCE, permissions.ONCE)
    for _ in range(2):
        outcome = commands.run(agent, MISSING, "candidate", ask=answers)
        assert (outcome.error.code, outcome.error.message) == DISPATCHED
    assert len(answers.questions) == 2
    assert answers.questions[0].details[2] == "Test cases: 1"
    assert dispatched == [("test_runner", "run_tests", {"version": "candidate", "scope": "selected",
                                                        "test_case_ids": ["TC-999"]})] * 2  # fmt: skip
    rows = tool_rows(agent.conn, agent.id)
    assert [(r["tool"], r["outcome"]) for r in rows] == [("run_tests", "error")] * 2
    assert rows[0]["error"] == "not_found: test case TC-999 does not exist"
    assert agent.permission_refusals == 0
    assert agent.conversation.messages == []  # a direct command is not added to the conversation


def test_allow_for_the_session_is_not_asked_again(agent, dispatched):
    answers = Answers(permissions.SESSION)
    for _ in range(2):
        outcome = commands.run(agent, MISSING, "both", ask=answers)
        assert (outcome.error.code, outcome.error.message) == DISPATCHED
    assert len(answers.questions) == 1
    assert agent.grants == {"run_tests", "start_service"}
    assert len(dispatched) == 2


def test_no_one_to_ask_is_a_refusal_for_lack_of_permission(agent, dispatched):
    outcome = commands.run(agent, MISSING, ask=None)
    assert outcome.error.code == "denied" and "no one to ask" in outcome.error.message
    assert dispatched == [] and agent.permission_refusals == 1


def test_without_trusted_commands_it_is_refused_before_any_question(agent_project):
    with start(agent_project) as session:
        answers = Answers()
        outcome = commands.run(session, MISSING, ask=answers)
        assert outcome.error.code == "denied"
        assert outcome.error.message == permissions.COMMANDS_NOT_APPROVED
        assert answers.questions == []
        row = tool_rows(session.conn, session.id)[-1]
        assert (row["tool"], row["outcome"]) == ("run_tests", "denied")
        assert session.permission_refusals == 1


def test_plan_mode_refuses_it(agent, dispatched):
    agent.mode = "plan"
    outcome = commands.run(agent, MISSING, ask=Answers())
    assert outcome.error.code == "denied" and outcome.error.message.startswith("plan mode does not allow")
    assert dispatched == [] and agent.permission_refusals == 1
