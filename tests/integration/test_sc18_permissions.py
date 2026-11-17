"""SC-18: permissions in mode default. ``/implement`` asks before ``write_test`` and shows the code; the user denies
it, the test case stays ``designed`` and the model is told ``denied``. ``/run`` asks before ``run_tests`` and shows
the commands; the user allows it and the suite runs."""

import json

import pytest
from fixtures.agent_session import (
    GENERATED_FILE,
    GENERATED_NAME,
    Scripted,
    answer,
    call,
    calls,
    generated_code,
    tool_results,
    tool_rows,
)
from fixtures.example_project import project_copy, start

from retroagent.memory import design
from retroagent.runtime import commands, permissions

pytestmark = pytest.mark.network


class Answers:
    """Scripted answers of the user; records every question."""

    def __init__(self, *answers):
        self.answers, self.questions = list(answers), []

    def __call__(self, request):
        self.questions.append(request)
        return self.answers.pop(0)


def test_sc18_write_test_denied_then_run_tests_allowed(tmp_path_factory, pip_cache, shop_after_design):
    with project_copy(tmp_path_factory, shop_after_design, pip_cache) as path:
        with start(path, trust_commands=True) as session:
            assert session.mode == "default"
            (designed,) = [row["id"] for row in design.list_test_cases(session.conn, status="designed")]
            write = call(
                "test_runner__write_test",
                {"test_case_id": designed, "file": GENERATED_FILE, "test_name": GENERATED_NAME,
                 "code": generated_code()},
            )  # fmt: skip
            script = Scripted([
                calls(call("runtime__load_skill", {"name": "test-design"})),
                calls(write),
                answer("The write was refused; the test case stays designed."),
            ])  # fmt: skip
            session.provider = script
            implement_answers = Answers(permissions.DENY)

            commands.implement(session, ask=implement_answers)

            (question,) = implement_answers.questions
            assert (question.tool, question.permissions) == ("test_runner__write_test", ("write_tests",))
            assert question.details == (
                f"Test case: {designed}",
                f"File: .retro/tests/{GENERATED_FILE}",
                f"Test: {GENERATED_NAME}",
                "Code:",
                generated_code(),
            )
            told = json.loads(tool_results(session.conversation)[write.id])
            assert told == {"error": {"code": "denied", "message": "the user denied the permission write_tests"}}
            assert tool_rows(session.conn, session.id)[-1]["outcome"] == "denied"
            row = design.get_test_case(session.conn, designed)
            assert (row["status"], row["implementation"], row["revision"]) == ("designed", None, None)
            assert not (path / ".retro" / "tests" / GENERATED_FILE).exists()

            run_answers = Answers(permissions.ONCE)
            outcome = commands.run(session, "suite", "candidate", ask=run_answers)

            (question,) = run_answers.questions
            config = session.config
            assert (question.tool, question.permissions) == (
                "test_runner__run_tests", ("run_tests", "start_service"),
            )  # fmt: skip
            base, candidate = session.versions()["base"], session.versions()["candidate"]
            suite = design.suite_test_cases(
                session.conn, design.current_suite(session.conn, base.commit, candidate.commit)
            )
            implemented = sum(1 for row in suite if row["status"] == "implemented")
            assert implemented > 0
            assert question.details == (
                f"Version: candidate {candidate.ref} ({candidate.commit})",
                "Scope: suite",
                f"Test cases: {implemented}",
                "Commands:",
                f"  setup: {config['tests.setup']}",
                f"  tests: {config['tests.select']}",
                f"  service: {config['service.start']}",
            )
            assert [run.status for run in outcome.runs] == ["completed"]
