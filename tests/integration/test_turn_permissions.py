"""Modes and permissions through the turn, with the real servers (runtime.md, Modes and permissions; SC-17 and SC-18
without a run).

A ``run_tests`` call that passes every check is dispatched with ``scope: selected`` and a test case that does not
exist, so the server answers ``not_found`` before it creates a worktree: a dispatched call is told apart from a
refused one by who answered, the server or the runtime. The example configures ``service.start``, so
``run_tests`` needs ``run_tests`` and ``start_service``.
"""

import dataclasses
import json

import pytest
from fixtures.agent_session import answer, call, calls, tool_results, tool_rows

from retroagent.llm import FakeProvider
from retroagent.runtime import permissions
from retroagent.runtime.turn import run_turn

RUN_TESTS = "test_runner__run_tests"
SELECTED = {"version": "base", "scope": "selected", "test_case_ids": ["TC-999"]}


class Answers:
    """Scripted answers to permission questions; records every question."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.questions: list[permissions.PermissionRequest] = []

    def __call__(self, request):
        self.questions.append(request)
        return self.answers.pop(0)


def set_permissions(session, value):
    values = {f"permissions.{key}": value for key in ("run_tests", "write_tests", "start_service")}
    session.config = dataclasses.replace(session.config, values={**session.config.values, **values})


def run_tests_once(session, ask=None, arguments=SELECTED):
    run_call = call(RUN_TESTS, arguments)
    provider = FakeProvider([calls(run_call), answer()])
    run_turn(session, "Run.", provider=provider, client=session.client, ask=ask)
    content = json.loads(tool_results(session.conversation)[run_call.id])
    return content["error"], tool_rows(session.conn, session.id)[-1], provider


DISPATCHED = {"code": "not_found", "message": "test case TC-999 does not exist"}

TABLE = {
    ("default", "allow"): "dispatched",
    ("default", "ask"): "asked",
    ("default", "deny"): "denied",
    ("auto", "allow"): "dispatched",
    ("auto", "ask"): "dispatched",
    ("auto", "deny"): "denied",
    ("plan", "allow"): "denied",
    ("plan", "ask"): "denied",
    ("plan", "deny"): "denied",
}


@pytest.mark.parametrize(("mode", "value"), list(TABLE))
def test_each_row_of_the_mode_and_permission_tables_for_run_tests(agent, mode, value):
    agent.mode = mode
    set_permissions(agent, value)
    answers = Answers(permissions.ONCE)
    error, row, _ = run_tests_once(agent, ask=answers)
    expected = TABLE[(mode, value)]
    if expected == "denied":
        assert error["code"] == "denied" and row["outcome"] == "denied"
        assert answers.questions == []
        if mode == "plan":
            assert error["message"].startswith("plan mode does not allow test_runner__run_tests")
        else:
            assert error["message"] == "the permission run_tests and start_service is deny"
    else:
        assert error == DISPATCHED and row["outcome"] == "error"
        assert len(answers.questions) == (1 if expected == "asked" else 0)


def test_one_question_names_both_permissions_and_shows_the_commands(agent):
    set_permissions(agent, "ask")
    answers = Answers(permissions.ONCE)
    run_tests_once(agent, ask=answers)
    (question,) = answers.questions
    assert question.tool == RUN_TESTS
    assert question.permissions == ("run_tests", "start_service")
    base = agent.versions()["base"]
    config = agent.config
    assert question.details == (
        f"Version: base {base.ref} ({base.commit})",
        "Scope: selected",
        "Test cases: 1",
        "Commands:",
        f"  setup: {config['tests.setup']}",
        f"  tests: {config['tests.select']}",
        f"  service: {config['service.start']}",
    )


def test_allow_once_asks_again_at_the_next_call(agent):
    set_permissions(agent, "ask")
    answers = Answers(permissions.ONCE, permissions.ONCE)
    run_tests_once(agent, ask=answers)
    run_tests_once(agent, ask=answers)
    assert len(answers.questions) == 2
    assert agent.grants == set()


def test_allow_for_the_session_grants_both_permissions_and_is_not_asked_again(agent):
    set_permissions(agent, "ask")
    answers = Answers(permissions.SESSION)
    run_tests_once(agent, ask=answers)
    error, _, provider = run_tests_once(agent, ask=answers)
    assert error == DISPATCHED and len(answers.questions) == 1
    assert agent.grants == {"run_tests", "start_service"}
    assert (
        "Permissions: run_tests allow, write_tests ask, start_service allow"
        in provider.requests[0].messages[-1].content
    )
    assert agent.config["permissions.run_tests"] == "ask"  # the grant is never written to configuration


def test_a_denied_question_returns_denied_to_the_model(agent):
    set_permissions(agent, "ask")
    error, row, _ = run_tests_once(agent, ask=Answers(permissions.DENY))
    assert error == {"code": "denied", "message": "the user denied the permission run_tests and start_service"}
    assert row["outcome"] == "denied"


def test_ask_without_anyone_to_ask_is_denied(agent):
    set_permissions(agent, "ask")
    error, row, _ = run_tests_once(agent, ask=None)
    assert error["code"] == "denied" and "no one to ask" in error["message"]
    assert row["outcome"] == "denied"


@pytest.mark.parametrize("mode", ["default", "auto"])
def test_run_tests_without_approved_commands_and_no_one_to_ask_is_denied(agent, mode):
    """The approval of the project commands, non-interactive row; the other rows are in test_sc03_approval.py."""
    agent.mode, agent.trust_commands = mode, False
    set_permissions(agent, "allow")
    error, row, provider = run_tests_once(agent, ask=None)
    assert error == {"code": "denied", "message": permissions.COMMANDS_NOT_APPROVED}
    assert row["outcome"] == "denied" and agent.permission_refusals == 1
    assert "Project commands: not approved" in provider.requests[0].messages[-1].content


def test_plan_mode_leaves_the_tools_out_and_refuses_and_records_a_call_to_them(agent):
    agent.mode = "plan"
    set_permissions(agent, "allow")
    error, row, provider = run_tests_once(agent, arguments={"version": "base", "scope": "all"})
    offered = {tool.name for tool in provider.requests[0].tools}
    assert offered and RUN_TESTS not in offered and "test_runner__write_test" not in offered
    assert "git__analyze_changes" in offered
    assert error["code"] == "denied"
    assert (row["server"], row["tool"], row["outcome"]) == ("test_runner", "run_tests", "denied")
    assert agent.conn.execute("SELECT COUNT(*) FROM run").fetchone()[0] == 0  # nothing ran


def test_in_default_mode_the_definitions_have_run_tests(agent):
    _, _, provider = run_tests_once(agent, ask=Answers(permissions.DENY))
    assert RUN_TESTS in {tool.name for tool in provider.requests[0].tools}
