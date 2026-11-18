"""``/implement [ids]`` with a model that follows the skill ``test-design`` (Implement), on shop-api after
``/run all --on both``, ``/analyze``, ``/select`` and ``/design`` (runtime.md, Model commands).

The command empties the conversation, sends its fixed template and exposes only the tools of the step
``implement``. The script reads the designed test cases of the current suite and the tests of the project, as a model
would, and writes the code of each one with ``test_runner.write_test``. Then the suite runs against both versions.
"""

import pytest
from fixtures.agent_session import (
    GENERATED_FILE,
    GENERATED_NAME,
    Scripted,
    answer,
    call,
    calls,
    generated_code,
    result_in,
    tool_rows,
)
from fixtures.example_project import project_copy, start
from fixtures.tool_definitions import step_tool_names

from retroagent.llm.provider import Message
from retroagent.memory import design, execution
from retroagent.runtime import commands

pytestmark = pytest.mark.network


def implement_script() -> Scripted:
    designed = call("memory__get_test_cases", {"status": "designed"})
    written = {}

    def write_each(request):
        for test_case in result_in(request, designed.id)["test_cases"]:
            written[test_case["id"]] = call(
                "test_runner__write_test",
                {"test_case_id": test_case["id"], "file": GENERATED_FILE, "test_name": GENERATED_NAME,
                 "code": generated_code()},
            )  # fmt: skip
        return calls(*written.values())

    def report(request):
        rows = [result_in(request, c.id) for c in written.values()]
        table = "\n".join(f"| {row['test_case_id']} | {row['implementation']} |" for row in rows)
        return answer(f"| Test case | Implementation |\n|---|---|\n{table}\n\nImplemented, not executed.")

    return Scripted([
        calls(call("runtime__load_skill", {"name": "test-design"})),
        calls(call("memory__get_suite"), designed),
        calls(call("git__list_files", {"version": "candidate", "path": "tests"})),
        calls(call("git__read_file", {"path": "tests/test_cart.py", "version": "candidate"})),
        write_each,
        report,
    ])  # fmt: skip


def first_user_message(request) -> str:
    return next(m.content for m in request.messages if m.role == "user")


def test_implement_writes_the_designed_test_cases_and_their_tests_run_on_both_versions(
    tmp_path_factory, pip_cache, shop_after_design
):
    with project_copy(tmp_path_factory, shop_after_design, pip_cache) as path:
        script = implement_script()
        with start(path, script, trust_commands=True, mode="auto") as session:
            (designed,) = [row["id"] for row in design.list_test_cases(session.conn, status="designed")]
            session.conversation.messages.append(Message(role="user", content="An earlier conversation."))

            result = commands.implement(session)

            assert script.remaining == 0 and result.text.endswith("Implemented, not executed.")
            assert first_user_message(script.requests[0]) == commands.IMPLEMENT_DEFAULT
            assert "An earlier conversation." not in [m.content for m in script.requests[0].messages]
            expected_tools = step_tool_names(session.known_tools(), "implement")
            for request in script.requests:
                assert sorted(t.name for t in request.tools) == expected_tools
            rows = tool_rows(session.conn, session.id)
            assert all(row["outcome"] == "ok" for row in rows)
            assert ("test_runner", "write_test") in [(row["server"], row["tool"]) for row in rows]

            row = design.get_test_case(session.conn, designed)
            assert (row["status"], row["implementation"], row["revision"]) == (
                "implemented", f"{GENERATED_FILE}::{GENERATED_NAME}", 1,
            )  # fmt: skip
            assert (path / ".retro" / "tests" / GENERATED_FILE).read_text(encoding="utf-8") == generated_code()
            assert session.conversation.loaded_skill == "test-design"

            outcome = commands.run(session, "suite", "both")

            assert [run.status for run in outcome.runs] == ["completed", "completed"]
            for run in outcome.runs:
                (executed,) = [e for e in execution.list_executions(session.conn, run.run_id)
                               if e["test_case_id"] == designed]  # fmt: skip
                assert (executed["status"], executed["result"], executed["test_revision"]) == ("executed", "passed", 1)


def test_implement_with_ids_names_them_in_the_template(tmp_path_factory, shop_after_design):
    with project_copy(tmp_path_factory, shop_after_design) as path:
        script = Scripted([answer("Nothing to implement.")])
        with start(path, script, trust_commands=True) as session:
            commands.implement(session, ["TC-027", "TC-028"])
    assert first_user_message(script.requests[0]) == (
        "Load the skill `test-design` and implement the test cases `TC-027, TC-028`; rewrite those that are already"
        " `implemented`."
    )
