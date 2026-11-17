"""``/select`` and ``/design [scope]`` with a model that follows the skills ``test-selection`` and ``test-design``
(runtime.md, Model commands), on shop-api after ``/run all --on both`` and ``/analyze``.

Each model command empties the conversation, sends its fixed template and exposes only the tools of its step. The
scripts read what the tools return, as a model would, and the tests check what project memory holds afterwards.
"""

import json

import pytest
from fixtures.agent_session import Scripted, analyze_script, answer, call, calls, result_in, tool_rows
from fixtures.example_project import project_copy, start

from retroagent.cli.main import main
from retroagent.context.tools import USER_ONLY
from retroagent.memory import design, impact
from retroagent.runtime import commands

pytestmark = pytest.mark.network

SHIPPING = "test_req_005_shipping_charged_when_discount_drops_below_threshold"
SECOND_COUPON = "test_req_004_second_coupon_is_rejected"
SEARCH = "test_req_001_search_results_are_sorted_by_name"
REQ_002_CASE = {
    "title": "A quantity above the stock is rejected",
    "objective": "Verify that adding more units than in stock is refused and the cart does not change.",
    "priority": "high",
    "preconditions": ["Product P-1 has stock 5", "The cart is empty"],
    "input_data": [{"name": "product", "value": "P-1"}, {"name": "quantity", "value": "6"}],
    "steps": ["Add 6 units of P-1 to the cart", "Read the cart"],
    "expected_result": "The request is rejected with status 409 and the cart stays empty.",
    "requirement_ids": ["REQ-002"],
}


@pytest.fixture(scope="module")
def project(tmp_path_factory, shop_after_both_runs):
    """A copy of the project after both full runs, analyzed with the reference script of ``/analyze``."""
    with project_copy(tmp_path_factory, shop_after_both_runs.path) as path:
        with start(path, Scripted(analyze_script()), trust_commands=True) as session:
            commands.analyze(session)
        yield path


def first_user_message(request) -> str:
    return next(m.content for m in request.messages if m.role == "user")


def step_tools(session, *extra: str) -> list[str]:
    """The tools of a step: every tool of runtime, git and memory except the user-only ones, and ``extra``."""
    return sorted(
        [name for name in session.known_tools()
         if name.split("__")[0] in ("runtime", "git", "memory") and name not in USER_ONLY] + list(extra)
    )  # fmt: skip


def calls_of(session) -> list[tuple[str, str]]:
    return [(row["server"], row["tool"]) for row in tool_rows(session.conn, session.id)]


def test_select_records_a_suite_with_a_reason_for_every_test_case_and_reports_the_gap_of_req_002(project):
    analysis, test_cases = call("memory__get_analysis"), call("memory__get_test_cases")
    saved = {}

    def save_suite(request):
        # Traced only by the requirements that get_test_cases lists for each test case, never by its title.
        impacted = {r["requirement_id"] for r in result_in(request, analysis.id)["requirements"]}
        selected = [
            (tc["id"], next(r["requirement_id"] for r in tc["requirements"] if r["requirement_id"] in impacted))
            for tc in result_in(request, test_cases.id)["test_cases"]
            if any(r["requirement_id"] in impacted for r in tc["requirements"])
        ]
        items = [
            {"test_case_id": test_case_id, "position": position,
             "selection_reason": f"Traced to {requirement_id}, an impacted requirement."}
            for position, (test_case_id, requirement_id) in enumerate(selected, start=1)
        ]  # fmt: skip
        saved["call"] = call("memory__save_suite", {"analysis_id": result_in(request, analysis.id)["analysis_id"],
                                                    "items": items})  # fmt: skip
        return calls(saved["call"])

    def report_gaps(request):
        uncovered = result_in(request, saved["call"].id)["uncovered_requirements"]
        return answer(f"Suite saved. Gaps: {', '.join(uncovered)}. Next step: /design.")

    script = Scripted([
        calls(call("runtime__load_skill", {"name": "test-selection"})),
        calls(analysis),
        calls(test_cases),
        calls(call("memory__get_risks"), call("memory__get_requirements", {"ids": ["REQ-004", "REQ-005"]})),
        save_suite,
        report_gaps,
    ])  # fmt: skip
    with start(project, script, trust_commands=True) as session:
        result = commands.select(session)

        assert result.text == "Suite saved. Gaps: REQ-002. Next step: /design." and script.remaining == 0
        assert first_user_message(script.requests[0]) == commands.SELECT
        for request in script.requests:
            assert sorted(t.name for t in request.tools) == step_tools(session, "test_runner__run_tests")
            assert "test_runner__write_test" not in [t.name for t in request.tools]
        assert calls_of(session) == [
            ("runtime", "load_skill"), ("memory", "get_analysis"), ("memory", "get_test_cases"),
            ("memory", "get_risks"), ("memory", "get_requirements"), ("memory", "save_suite"),
        ]  # fmt: skip
        assert all(row["outcome"] == "ok" for row in tool_rows(session.conn, session.id))

        base, candidate = session.versions()["base"], session.versions()["candidate"]
        suite_id = design.current_suite(session.conn, base.commit, candidate.commit)
        rows = session.conn.execute(
            "SELECT s.position, s.selection_reason, tc.test_id FROM suite_test_case s JOIN test_case tc"
            " ON tc.id = s.test_case_id WHERE s.suite_id = ? ORDER BY s.position",
            (suite_id,),
        ).fetchall()
        names = [row["test_id"].rpartition("::")[2] for row in rows]
        assert SHIPPING in names and SECOND_COUPON in names  # the two revealing test cases (SC-23)
        assert SEARCH not in names  # REQ-001 was judged not impacted
        assert [row["position"] for row in rows] == list(range(1, len(rows) + 1))
        assert all(row["selection_reason"].startswith("Traced to REQ-") for row in rows)
        assert not any("REQ-002" in row["selection_reason"] for row in rows)
        assert design.uncovered_requirements(session.conn, suite_id) == ["REQ-002"]
        assert session.conversation.loaded_skill == "test-selection"


def test_design_designs_for_every_uncovered_requirement_of_the_current_suite(project):
    suite = call("memory__get_suite")
    designed: dict[str, object] = {}  # requirement -> the design_test_case call made for it

    def read_scope(request):
        uncovered = result_in(request, suite.id)["uncovered_requirements"]
        return calls(call("memory__get_analysis"), call("memory__get_requirements", {"ids": uncovered}),
                     *(call("memory__get_test_cases", {"requirement_id": r}) for r in uncovered))  # fmt: skip

    def design_each(request):
        for requirement_id in result_in(request, suite.id)["uncovered_requirements"]:
            fields = REQ_002_CASE if requirement_id == "REQ-002" else {
                **REQ_002_CASE, "title": f"Main rule of {requirement_id}", "requirement_ids": [requirement_id],
            }  # fmt: skip
            designed[requirement_id] = call(
                "memory__design_test_case", {**fields, "selection_reason": f"Covers the gap of {requirement_id}."}
            )
        return calls(*designed.values())

    script = Scripted([
        calls(call("runtime__load_skill", {"name": "test-design"})),
        calls(suite),
        read_scope,
        calls(call("git__read_file", {"path": "src/shop/cart.py", "version": "candidate"})),
        design_each,
        answer("Test cases designed for every gap. They are designed, not implemented, not executed."),
    ])  # fmt: skip
    with start(project, script, trust_commands=True) as session:
        base, candidate = session.versions()["base"], session.versions()["candidate"]
        suite_id = design.current_suite(session.conn, base.commit, candidate.commit)
        if suite_id is None:  # this test runs alone: an empty selection, as /select may leave
            analysis_id = impact.latest_analysis(session.conn, base.commit, candidate.commit)
            suite_id = design.save_suite(session.conn, analysis_id=analysis_id, session_id=session.id, items=[])
        size = len(design.suite_test_cases(session.conn, suite_id))
        uncovered = design.uncovered_requirements(session.conn, suite_id)
        assert "REQ-002" in uncovered  # after /select, the only one

        result = commands.design_tests(session)

        assert script.remaining == 0 and "not executed" in result.text
        assert first_user_message(script.requests[0]) == commands.DESIGN_DEFAULT
        for request in script.requests:
            assert sorted(t.name for t in request.tools) == step_tools(session)
            assert not any(t.name.startswith("test_runner__") for t in request.tools)
        assert all(row["outcome"] == "ok" for row in tool_rows(session.conn, session.id))
        assert result_in(script.requests[2], suite.id)["suite_id"] == suite_id
        assert sorted(designed) == uncovered
        assert design.uncovered_requirements(session.conn, suite_id) == []

        created = result_in(script.requests[-1], designed["REQ-002"].id)
        row = design.get_test_case(session.conn, created["test_case_id"])
        assert (row["status"], row["origin"], row["designed_by"]) == ("designed", "designed", session.model)
        assert (row["title"], row["objective"], row["priority"], row["expected_result"]) == (
            REQ_002_CASE["title"], REQ_002_CASE["objective"], "high", REQ_002_CASE["expected_result"],
        )  # fmt: skip
        for field in ("preconditions", "input_data", "steps"):
            assert json.loads(row[field]) == REQ_002_CASE[field]
        assert (row["implementation"], row["test_id"]) == (None, None)
        links = [tuple(r) for r in design.test_case_requirements(session.conn, created["test_case_id"])]
        assert links == [("REQ-002", "design")]
        items = design.suite_items(session.conn, suite_id)
        assert [i["position"] for i in items[size:]] == list(range(size + 1, size + len(designed) + 1))
        assert created["suite_id"] == suite_id and created["test_case_id"] in [i["test_case_id"] for i in items]
        assert session.conversation.loaded_skill == "test-design"


def test_design_with_a_scope_names_it_in_the_template(project):
    script = Scripted([answer("Nothing to design.")])
    with start(project, script, trust_commands=True) as session:
        commands.design_tests(session, "REQ-002 REQ-004")
    assert first_user_message(script.requests[0]) == (
        "Load the skill `test-design` and design test cases for `REQ-002 REQ-004`."
    )


def test_select_in_non_interactive_mode(project, fake_model, capsys):
    script = fake_model(Scripted([answer("No change since the last selection.")]))
    assert main(["-C", str(project), "-p", "/select"]) == 0
    assert capsys.readouterr().out.strip() == "No change since the last selection."
    assert first_user_message(script.requests[0]) == commands.SELECT
