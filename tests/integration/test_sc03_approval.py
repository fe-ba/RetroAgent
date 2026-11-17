"""SC-03: the approval of the project commands (runtime.md, Project commands; configuration.md, Project commands).

Each row of the table: approved, not approved in an interactive session, not approved in non-interactive mode, and
``--trust-commands``; a command changed after its approval, also during the session; a file of approvals that cannot
be read; and a configuration that cannot be read when the run is asked for.

A ``run_tests`` call that needs no real run uses ``scope: selected`` with a test case that does not exist: when every
check passes, the server answers ``not_found`` before it creates a worktree, so a dispatched call is told apart from a
refused one by who answered.
"""

import json
import subprocess

import pytest
from fixtures.agent_session import answer, call, calls, factory, tool_results
from fixtures.example_project import project_copy

from retroagent.cli.main import main
from retroagent.config import approvals, load_config, retro_home
from retroagent.llm import FakeProvider
from retroagent.runtime import permissions, session
from retroagent.runtime.permissions import ApprovalRequest, PermissionRequest
from retroagent.runtime.turn import run_turn

RUN_TESTS = "test_runner__run_tests"
MISSING = {"version": "base", "scope": "selected", "test_case_ids": ["TC-999"]}
SUITE = {"version": "candidate", "scope": "suite"}
DISPATCHED = {"code": "not_found", "message": "test case TC-999 does not exist"}
ENV = "  env:\n    SHOP_TEST_MODE: strict\n    SHOP_SEED: '42'\n"


class Answers:
    """Scripted answers of the user; records every question."""

    def __init__(self, *answers):
        self.answers, self.questions = list(answers), []

    def __call__(self, request):
        self.questions.append(request)
        return self.answers.pop(0)


def with_env(path):
    """The example configuration with a ``tests.env``, so that the approval shows variables too."""
    config = path / ".retro" / "config.yaml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("\nservice:\n", f"{ENV}\nservice:\n", 1), encoding="utf-8")


def change_command(path):
    config = path / ".retro" / "config.yaml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("-m pytest tests --junitxml", "-m pytest tests -q --junitxml", 1), encoding="utf-8")


def open_session(path, *, interactive=True, trust=False, mode="default"):
    options = session.Options(project=path, interactive=interactive, trust_commands=trust, mode=mode)
    return session.start(options, provider_factory=factory())


def run_tests(started, arguments, ask):
    """One model turn that calls ``run_tests`` once; returns what the model was told."""
    run_call = call(RUN_TESTS, arguments)
    run_turn(started, "Run.", provider=FakeProvider([calls(run_call), answer()]), client=started.client, ask=ask)
    return json.loads(tool_results(started.conversation)[run_call.id])


def approvals_file():
    return retro_home() / "approvals.json"


def stored(path) -> str | None:
    if not approvals_file().exists():
        return None
    entry = json.loads(approvals_file().read_text(encoding="utf-8"))["project_commands"].get(str(path.resolve()))
    return entry and entry["sha256"]


def runs(started) -> int:
    return started.conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]


@pytest.fixture
def project(tmp_path_factory, shop_after_design):
    with project_copy(tmp_path_factory, shop_after_design) as path:
        with_env(path)
        yield path


@pytest.mark.network
def test_sc03_approve_run_change_and_ask_again(tmp_path_factory, pip_cache, shop_after_design, fake_model):
    with project_copy(tmp_path_factory, shop_after_design, pip_cache) as path:
        with_env(path)
        config = load_config(path)
        with open_session(path) as started:
            existing = runs(started)  # the full runs of the fixture
            # Not approved, interactive: every command and variable in full, then the permission question.
            answers = Answers(permissions.APPROVE, permissions.ONCE)
            told = run_tests(started, SUITE, answers)
            approval, permission = answers.questions
            assert isinstance(approval, ApprovalRequest) and isinstance(permission, PermissionRequest)
            assert approval.details == (
                f"Project: {path.resolve()}",
                "They run on this machine with your privileges; RetroAgent is not a sandbox.",
                f"  tests.setup: {config['tests.setup']}",
                f"  tests.command: {config['tests.command']}",
                f"  tests.select: {config['tests.select']}",
                f"  service.start: {config['service.start']}",
                "  tests.env:",
                "    SHOP_TEST_MODE=strict",
                "    SHOP_SEED=42",
                f"An approval is stored in {approvals_file()}; a command that changes is asked again.",
            )
            assert told["status"] == "completed" and runs(started) == existing + 1
            # The approval is stored outside the project, as the hash of the five values.
            assert stored(path) == approvals.digest(config)
            assert not list(path.rglob("approvals*.json"))
            status = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True)
            assert status.stdout.split() == ["M", ".retro/config.yaml"]  # only the tests.env added by this test

            # Approved: the next run asks only for the permission.
            answers = Answers(permissions.DENY)
            assert run_tests(started, MISSING, answers)["error"]["message"].startswith("the user denied")
            assert [type(q) for q in answers.questions] == [PermissionRequest]

            # A command changed during the session is asked again, in its new content.
            before = approvals_file().read_bytes()
            change_command(path)
            answers = Answers(permissions.DENY)
            told = run_tests(started, MISSING, answers)
            (question,) = answers.questions
            assert isinstance(question, ApprovalRequest)
            assert f"  tests.command: {load_config(path)['tests.command']}" in question.details
            assert " -q " in load_config(path)["tests.command"]
            assert told == {"error": {"code": "denied", "message": permissions.COMMANDS_REFUSED}}
            assert approvals_file().read_bytes() == before and runs(started) == existing + 1

        # Non-interactive mode, the changed command not approved: refused, exit code 4, no run, nothing stored.
        fake_model(FakeProvider([calls(call(RUN_TESTS, SUITE)), answer("Not run.")]))
        assert main(["-C", str(path), "--mode", "auto", "-p", "Run the suite."]) == 4
        assert approvals_file().read_bytes() == before

        # --trust-commands: it runs, and nothing is stored.
        fake_model(FakeProvider())
        assert main(["-C", str(path), "--trust-commands", "--mode", "auto", "-p", "/run suite"]) == 0
        assert approvals_file().read_bytes() == before
        with open_session(path, interactive=False) as started:
            statuses = [row["status"] for row in started.conn.execute("SELECT status FROM run ORDER BY id")]
            assert statuses[-2:] == ["completed", "completed"]  # the run of the first session, then this one
            assert runs(started) == existing + 2


def test_a_stored_approval_lets_a_non_interactive_session_run(project):
    approvals.store(project, approvals.digest(load_config(project)))
    with open_session(project, interactive=False, mode="auto") as started:
        assert started.commands_state().approved
        assert run_tests(started, MISSING, ask=None) == {"error": DISPATCHED}
        assert started.permission_refusals == 0


def test_not_approved_and_no_one_to_ask_is_denied_whatever_the_mode(project):
    for mode in ("default", "auto"):
        with open_session(project, interactive=False, mode=mode) as started:
            told = run_tests(started, MISSING, ask=None)
            assert told == {"error": {"code": "denied", "message": permissions.COMMANDS_NOT_APPROVED}}
            assert started.permission_refusals == 1
    assert not approvals_file().exists()


def test_auto_mode_still_asks_for_the_approval_in_an_interactive_session(project):
    with open_session(project, mode="auto") as started:
        answers = Answers(permissions.APPROVE)
        assert run_tests(started, MISSING, answers) == {"error": DISPATCHED}  # no permission question in auto
        assert [type(q) for q in answers.questions] == [ApprovalRequest]
    assert stored(project) == approvals.digest(load_config(project))


def test_trust_commands_approves_for_the_session_and_stores_nothing(project):
    with open_session(project, trust=True) as started:
        answers = Answers(permissions.ONCE)
        assert run_tests(started, MISSING, answers) == {"error": DISPATCHED}
        assert [type(q) for q in answers.questions] == [PermissionRequest]
    assert not approvals_file().exists()


def test_an_approvals_file_that_cannot_be_read_refuses_the_run_and_is_never_overwritten(project):
    approvals_file().write_text("{broken", encoding="utf-8")
    with open_session(project) as started:
        answers = Answers()
        told = run_tests(started, MISSING, answers)
        assert told["error"]["code"] == "denied" and str(approvals_file()) in told["error"]["message"]
        assert answers.questions == [] and started.permission_refusals == 1
    assert approvals_file().read_text(encoding="utf-8") == "{broken"


def test_a_configuration_that_cannot_be_read_when_the_run_is_asked_is_invalid_state(project):
    with open_session(project) as started:
        (project / ".retro" / "config.yaml").write_text("tests: [broken\n", encoding="utf-8")
        answers = Answers()
        told = run_tests(started, MISSING, answers)
        assert told["error"]["code"] == "invalid_state" and "cannot be read" in told["error"]["message"]
        assert answers.questions == [] and started.permission_refusals == 0


def test_without_tests_command_nothing_is_asked_and_the_server_refuses(project):
    config = project / ".retro" / "config.yaml"
    text = config.read_text(encoding="utf-8")
    config.write_text("\n".join(line for line in text.splitlines() if "  command:" not in line) + "\n")
    with open_session(project) as started:
        answers = Answers(permissions.ONCE)
        told = run_tests(started, MISSING, answers)
        assert [type(q) for q in answers.questions] == [PermissionRequest]
        assert told["error"]["code"] == "invalid_state" and "tests.command" in told["error"]["message"]


def test_the_state_message_says_whether_the_current_commands_are_approved(project):
    with open_session(project, interactive=False) as started:
        assert "Project commands: not approved" in started.state_message().content
        approvals.store(project, approvals.digest(load_config(project)))
        assert "Project commands: approved" in started.state_message().content
        change_command(project)
        assert "Project commands: not approved" in started.state_message().content
