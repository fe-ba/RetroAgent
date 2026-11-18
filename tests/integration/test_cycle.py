"""``/cycle`` (runtime.md, Cycle command; ADR-0027): SC-09, SC-10, SC-16, SC-17, SC-19 and SC-20 with the reference
script, every stop condition and the resume after it, interruptions, and the exit codes of ``retro -p "/cycle"``.

The model is ``FakeProvider``; the runs are real runs of shop-api by the test runner.
"""

import contextlib
import io
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from fixtures import reference_script
from fixtures.agent_session import (
    Scripted,
    analyze_script,
    answer,
    call,
    calls,
    design_script,
    select_script,
    write_user_config,
)
from fixtures.example_project import example_project, project_copy, start
from fixtures.reference_scenario import decision_of
from fixtures.report_text import computed, difference, expected_computed
from fixtures.tool_definitions import step_tool_names

from retroagent.cli.main import main
from retroagent.llm import FakeProvider, Usage
from retroagent.llm.provider import request_characters
from retroagent.memory import connect, design, execution, interpretation, sessions
from retroagent.runtime import commands, cycle
from retroagent.runtime import session as session_module
from retroagent.servers.test_runner import junit
from retroagent.servers.test_runner.worktree import worktrees_dir

pytestmark = pytest.mark.network

FIELDS = {"result", "session_id", "runs", "reports", "decision", "denied", "recorded", "exit_code"}
CYCLE_1_TEMPLATES = [
    commands.ANALYZE,
    commands.SELECT,
    commands.design_message(None),
    commands.implement_message(()),
    commands.TRIAGE.format(run_id="RUN-0004"),
    commands.report_message("completion"),
]
STEP_OF_TEMPLATE = dict(
    zip(CYCLE_1_TEMPLATES, ("analyze", "select", "design", "implement", "triage", "report"), strict=True)
)
POSITION = {"analyze": 1, "select": 3, "design": 4, "implement": 5, "triage": 7, "report": 8}


def run_json(project: Path, *argv: str) -> tuple[int, dict]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(["-C", str(project), "--output-format", "json", *argv])
    output = json.loads(buffer.getvalue())
    assert set(output) == FIELDS and output["exit_code"] == code
    return code, output


@contextlib.contextmanager
def model(provider):
    """Every session started by ``main`` in the block gets ``provider`` as its model."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(session_module, "_make_provider", lambda profile, session, factory: provider)
        yield provider


def user_message(request) -> str:
    return next(m.content for m in request.messages if m.role == "user")


def first_requests(provider) -> list:
    """The first request of each turn: its conversation holds only the message of the turn."""
    return [r for r in provider.requests if len(r.messages) == 3]


def tool_names(request) -> list[str]:
    return sorted(t.name for t in request.tools)


@dataclass(frozen=True)
class Done:
    path: Path
    code: int
    output: dict
    provider: Scripted


@pytest.fixture(scope="module")
def cycle_1(tmp_path_factory, pip_cache) -> Done:
    """SC-09: ``retro -p "/cycle" --mode auto --trust-commands --base v1.0 --candidate v1.1`` on a new example, with
    the reference script. Nobody changes the project afterwards; cycle 2 runs on a copy."""
    with example_project(tmp_path_factory, pip_cache) as path, model(reference_script.cycle_1()) as provider:
        code, output = run_json(
            path, "--mode", "auto", "--trust-commands", "--base", "v1.0", "--candidate", "v1.1", "-p", "/cycle"
        )
    return Done(path, code, output, provider)


# SC-09 --------------------------------------------------------------------------------------------------------------


def test_sc09_cycle_1_ends_do_not_release_with_the_records_of_the_reference_scenario(cycle_1):
    output = cycle_1.output
    assert cycle_1.code == 3, output["result"]
    assert cycle_1.provider.remaining == 0
    assert output["decision"] == "do_not_release" and output["denied"] == 0
    # discover: the full runs; run: the suite against both versions
    assert output["runs"] == ["RUN-0001", "RUN-0002", "RUN-0003", "RUN-0004"]
    assert [r["id"] for r in output["reports"]] == ["RPT-0001"]
    assert output["result"].startswith("RPT-0001 is rendered") and "`do_not_release`" in output["result"]
    assert output["recorded"] == {
        "memory__sync_requirements": 1, "git__analyze_changes": 1, "memory__save_impact": 1, "memory__add_risk": 4,
        "memory__save_suite": 1, "memory__design_test_case": 2, "test_runner__write_test": 1,
        "memory__save_triage": 4, "memory__register_defect": 1, "reports__prepare_report": 1,
        "reports__render_report": 1,
    }  # fmt: skip
    conn = connect(cycle_1.path)
    try:
        runs = {run: execution.get_run(conn, run) for run in output["runs"]}
        assert [(r["version_role"], r["ref"], r["scope"], r["status"]) for r in runs.values()] == [
            ("base", "v1.0", "all", "completed"),
            ("candidate", "v1.1", "all", "completed"),
            ("base", "v1.0", "suite", "completed"),
            ("candidate", "v1.1", "suite", "completed"),
        ]
        suite_id = runs["RUN-0004"]["suite_id"]
        assert len(design.suite_test_cases(conn, suite_id)) == 28  # planned
        baseline, evaluated = (execution.execution_counts(conn, r) for r in ("RUN-0003", "RUN-0004"))
        assert (baseline["executed"], baseline["passed"], baseline["failed"], baseline["blocked"]) == (23, 21, 2, 4)
        not_reported = conn.execute(
            "SELECT COUNT(*) FROM test_execution WHERE run_id = 'RUN-0003' AND reason = 'not_reported'"
        ).fetchone()[0]
        assert not_reported == 4
        assert (evaluated["executed"], evaluated["passed"], evaluated["failed"], evaluated["blocked"]) == (27, 23, 4, 0)
        tc_027, tc_028 = design.get_test_case(conn, "TC-027"), design.get_test_case(conn, "TC-028")
        assert (tc_027["status"], tc_027["priority"], tc_028["status"], tc_028["priority"]) == (
            "implemented", "high", "designed", "medium",
        )  # fmt: skip
        defect = interpretation.get_defect(conn, "DEF-001")
        assert (defect["severity"], defect["status"]) == ("high", "open")
        assert interpretation.linked_test_cases(conn, "DEF-001") == ["TC-020"]
    finally:
        conn.close()


def test_sc09_each_model_step_is_a_turn_with_an_empty_conversation_and_the_tools_of_its_step(cycle_1):
    firsts = first_requests(cycle_1.provider)
    assert [user_message(r) for r in firsts] == CYCLE_1_TEMPLATES  # in the order of the cycle
    for request in firsts:
        step = STEP_OF_TEMPLATE[user_message(request)]
        system, message, state = request.messages
        assert (system.role, message.role, state.role) == ("system", "user", "user")
        assert state.content.startswith("<session-state>")
        assert f"Cycle step: {step} ({POSITION[step]} of 8). Do only this step, then end the turn." in state.content
        known = {t.name for r in cycle_1.provider.requests for t in r.tools} | {"test_runner__run_tests"}
        assert tool_names(request) == step_tool_names(known, step)
    # the state message is the last message of every call, and it names the step of the turn
    for request in cycle_1.provider.requests:
        assert "Cycle step: " in request.messages[-1].content


def test_sc09_the_rendered_report_has_the_computed_sections_of_the_expected_report(cycle_1):
    path = cycle_1.path / cycle_1.output["reports"][0]["path"] / "report.md"
    actual = computed(path.read_text(encoding="utf-8"))
    expected = expected_computed()
    assert actual == expected, "\n" + difference(expected, actual)


# SC-10 --------------------------------------------------------------------------------------------------------------


def test_sc10_metrics_criteria_and_decision_of_cycle_1(cycle_1):
    criteria, decision = decision_of(cycle_1.path)
    assert decision.outcome == "do_not_release"
    assert sorted(c.id for c in decision.reasons) == ["EC-01", "EC-05", "EC-09"]
    assert {i: c.state for i, c in criteria.items() if c.state != "met"} == {
        "EC-01": "not_met", "EC-05": "not_met", "EC-09": "not_met",
    }  # fmt: skip
    conn = connect(cycle_1.path)
    try:
        stored = conn.execute("SELECT * FROM evaluation ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    metrics = json.loads(stored["metrics"])
    assert stored["run_id"] == "RUN-0004" and stored["baseline_run_id"] == "RUN-0003"
    assert (
        metrics["new_failures"], metrics["unexcused_new_failures"], metrics["persistent_failures"],
        metrics["stable_passes"], metrics["not_comparable"], metrics["fixed"],
    ) == (2, 1, 2, 19, 4, 0)  # fmt: skip
    again_criteria, again = decision_of(cycle_1.path)  # evaluating twice gives identical values
    assert (again_criteria, again) == (criteria, decision)


# SC-20 --------------------------------------------------------------------------------------------------------------


def test_sc20_every_tool_call_is_recorded_and_every_execution_is_in_a_stored_junit_xml(cycle_1):
    conn = connect(cycle_1.path)
    try:
        rows = conn.execute(
            "SELECT * FROM tool_call WHERE session_id = ? ORDER BY id", (cycle_1.output["session_id"],)
        ).fetchall()
        script_calls = [c for r in cycle_1.provider.requests for m in r.messages if m.role == "assistant"
                        for c in m.tool_calls]  # fmt: skip
        model_calls = len({c.id for c in script_calls})
        assert len(rows) == model_calls + 4  # and the four runs of the direct steps
        assert [r["tool"] for r in rows].count("run_tests") == 4
        for row in rows:
            assert isinstance(json.loads(row["arguments"]), dict)
            assert row["outcome"] == "ok", (row["tool"], row["error"])
            assert row["started_at"] and row["ended_at"]
        for run_id in cycle_1.output["runs"]:
            run = execution.get_run(conn, run_id)
            first = junit.parse([cycle_1.path / run["evidence_dir"] / "junit-1.xml"])
            reported = {e.test_id: e.outcome for e in first}
            for row in execution.list_executions(conn, run_id):
                if row["status"] != "executed":
                    assert row["reason"] == "not_reported"
                    continue
                test_id = design.get_test_case(conn, row["test_case_id"])["test_id"]
                assert reported[test_id] == row["result"], (run_id, test_id)
    finally:
        conn.close()


# SC-16 --------------------------------------------------------------------------------------------------------------


def test_sc16_cycle_2_closes_the_defect_and_releases_with_conditions(cycle_1, tmp_path_factory, pip_cache, capsys):
    with project_copy(tmp_path_factory, cycle_1.path, pip_cache) as path, model(reference_script.cycle_2()) as script:
        code = main(["-C", str(path), "--mode", "auto", "--trust-commands", "-p", "/cycle v1.1 v1.2"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert script.remaining == 0
    assert "Defects: open: 0 critical, 1 high" in script.requests[0].messages[-1].content  # DEF-001 is found open
    # no full run: the change of v1.2 only removes lines from a test file
    assert "Cycle step 2 of 8: discover, skipped: completed full runs exist for v1.1..v1.2." in out
    assert "The cycle is complete." in out
    conn = connect(path)
    try:
        session_id = conn.execute("SELECT MAX(id) FROM session").fetchone()[0]
        runs = [r["id"] for r in conn.execute("SELECT id FROM run WHERE session_id = ? ORDER BY id", (session_id,))]
        assert runs == ["RUN-0005", "RUN-0006"]
        assert [(r["version_role"], r["ref"], r["scope"]) for r in map(lambda i: execution.get_run(conn, i), runs)] == [
            ("base", "v1.1", "suite"), ("candidate", "v1.2", "suite"),
        ]  # fmt: skip
        defect = interpretation.get_defect(conn, "DEF-001")
        assert (defect["status"], defect["closed_by"], defect["closed_run_id"]) == ("closed", "run", "RUN-0006")
        classifications = {
            row["test_case_id"]: row["classification"]
            for row in conn.execute(
                "SELECT e.test_case_id, t.classification FROM triage AS t JOIN test_execution AS e"
                " ON e.id = t.execution_id WHERE e.run_id = 'RUN-0006'"
            )
        }
        assert classifications == {"TC-011": "flaky", "TC-022": "pre_existing"}
        evaluation = conn.execute("SELECT * FROM evaluation ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert evaluation["decision"] == "release_with_conditions"
    metrics = json.loads(evaluation["metrics"])
    assert (metrics["fixed"], metrics["new_failures"]) == (1, 0)  # TC-020 is fixed
    conditions = json.loads(evaluation["decision_details"])["conditions"]
    assert [(c["kind"], [t["test_case_id"] for t in c["test_cases"]]) for c in conditions] == [
        ("pre_existing", ["TC-022"])
    ]


# SC-17 --------------------------------------------------------------------------------------------------------------


@pytest.fixture
def fresh(tmp_path_factory, pristine_example):
    """A copy of the example without any run."""
    with project_copy(tmp_path_factory, pristine_example) as path:
        yield path


def test_sc17_plan_mode_runs_analyze_select_and_design_and_stops_before_implement(fresh):
    script = Scripted([*analyze_script(), *select_script(), *design_script()])
    events: list = []
    with start(fresh, script, mode="plan") as session:
        result = cycle.run_cycle(session, ("v1.0", "v1.1"), show=events.append)
        tests_dir = session.project_dir / ".retro" / "tests"
        assert execution.list_runs(session.conn, 10) == []
    assert result.stop is None and result.plan_end
    assert result.steps == (("analyze", "ran"), ("select", "ran"), ("design", "ran"))
    assert [(e.name, e.position, e.total) for e in events if isinstance(e, cycle.StepStarted)] == [
        ("analyze", 1, 3), ("select", 2, 3), ("design", 3, 3),
    ]  # fmt: skip
    assert script.remaining == 0
    for request in script.requests:
        assert "test_runner__run_tests" not in tool_names(request)
        assert "test_runner__write_test" not in tool_names(request)
    assert not tests_dir.exists() or not any(tests_dir.iterdir())


def test_sc17_a_call_to_run_tests_in_plan_mode_is_refused_by_the_mode_and_stops_the_cycle(fresh):
    # select has run_tests in its tools; plan mode leaves it out of the definitions and refuses a call to it
    run = call("test_runner__run_tests", {"version": "base", "scope": "all"})
    script = Scripted([
        *analyze_script(),
        calls(call("runtime__load_skill", {"name": "test-selection"})), calls(run),
        answer("Running tests is refused in plan mode: the selection uses the known test cases only."),
    ])  # fmt: skip
    with start(fresh, script, mode="plan") as session:
        result = cycle.run_cycle(session, ("v1.0", "v1.1"))
        row = session.conn.execute("SELECT outcome, error FROM tool_call WHERE tool = 'run_tests'").fetchone()
        assert session.permission_refusals == 1 and execution.list_runs(session.conn, 10) == []
    assert steps(result) == [("analyze", "ran"), ("select", "ran")]
    assert (result.stop.step, result.stop.reason, result.stop.runtime_error) == ("select", "refused", False)
    assert row["outcome"] == "denied" and "plan" in row["error"]
    assert script.remaining == 0


# Stop conditions and resume ----------------------------------------------------------------------------------------


@pytest.fixture
def both_runs(tmp_path_factory, shop_after_both_runs, pip_cache):
    """A copy of the example after ``/run all --on both``: discover is done."""
    with project_copy(tmp_path_factory, shop_after_both_runs.path, pip_cache) as path:
        yield path


@pytest.fixture
def designed(tmp_path_factory, shop_after_design, pip_cache):
    """A copy of the example after the full runs, ``/analyze``, ``/select`` and ``/design``."""
    with project_copy(tmp_path_factory, shop_after_design, pip_cache) as path:
        yield path


def steps(result) -> list[tuple[str, str]]:
    return list(result.steps)


def no_impact() -> list:
    """An analyze step that loads its skill and answers without recording the impact."""
    return [calls(call("runtime__load_skill", {"name": "impact-analysis"})), answer("The change is small.")]


def test_an_outcome_missing_twice_stops_and_cycle_continues_from_the_step_that_stopped(both_runs):
    script = Scripted([
        *no_impact(), *no_impact(),  # first /cycle: analyze and its retry
        *analyze_script(), *select_script("Suite saved. Should I design test cases for REQ-002?"),  # second
        *design_script("Designed. Do you want me to implement it now?"),  # third
    ])  # fmt: skip
    with start(both_runs, script, trust_commands=True, mode="auto") as session:
        first = cycle.run_cycle(session)
        retry = script.requests[2]
        second = cycle.run_cycle(session)
        third = cycle.run_cycle(session)
    assert steps(first) == [("analyze", "ran")]
    assert (first.stop.step, first.stop.reason, first.stop.runtime_error) == ("analyze", "missing", True)
    assert "is still missing after a retry: there is no analysis of v1.0..v1.1" in first.stop.message
    assert user_message(retry) == (
        f"{commands.ANALYZE}\n\nThis step already ran once, and its outcome is missing: there is no analysis of"
        " v1.0..v1.1: call git__analyze_changes, then memory__save_impact. Complete the step."
    )
    assert len(retry.messages) == 3  # the retry starts with an empty conversation
    assert steps(second) == [("analyze", "ran"), ("discover", "skipped"), ("select", "ran")]
    assert (second.stop.step, second.stop.reason) == ("select", "question")
    assert steps(third) == [("analyze", "skipped"), ("discover", "skipped"), ("select", "skipped"), ("design", "ran")]
    assert (third.stop.step, third.stop.reason) == ("design", "question")
    assert script.remaining == 0


def test_a_refused_call_stops_the_cycle_with_exit_4_and_cycle_continues(both_runs):
    refused = call("test_runner__run_tests", {"version": "candidate", "scope": "all"})
    with model(Scripted([
        *analyze_script(),
        calls(call("runtime__load_skill", {"name": "test-selection"})), calls(refused),
        answer("The run was refused: the selection uses the known test cases only."),
    ])) as script:  # fmt: skip
        code, output = run_json(both_runs, "--trust-commands", "-p", "/cycle")  # mode default: no one to ask
    assert (code, output["denied"]) == (4, 1)
    assert output["result"] == "A tool call of the step select was refused."
    assert script.remaining == 0
    with model(Scripted([*select_script(), *design_script("Designed. Should I implement it?")])) as script:
        code, output = run_json(both_runs, "--trust-commands", "--mode", "auto", "-p", "/cycle")
    assert (code, output["denied"]) == (1, 0)  # it stops again, at the question of design
    assert output["result"] == "The step design ended with a question for the user."
    assert script.remaining == 0
    assert [user_message(r) for r in first_requests(script)] == [commands.SELECT, commands.design_message(None)]


def nothing_to_design_and_implement() -> list:
    return [answer("Nothing to design."), answer("Nothing to implement.")]


def test_a_run_that_ends_error_stops_the_cycle_and_cycle_continues_with_the_runs(designed):
    config = designed / ".retro" / "config.yaml"
    original = config.read_text(encoding="utf-8")
    config.write_text(original.replace("  setup: ", "  setup: exit 3 && "), encoding="utf-8")
    script = Scripted([
        *nothing_to_design_and_implement(),  # first /cycle
        *nothing_to_design_and_implement(), answer("Which failure should I triage first?"),  # second
    ])  # fmt: skip
    with start(designed, script, trust_commands=True, mode="auto") as session:
        first = cycle.run_cycle(session)
        config.write_text(original, encoding="utf-8")  # the user fixes the setup
        second = cycle.run_cycle(session)
        runs = [(r["id"], r["version_role"], r["status"]) for r in reversed(execution.list_runs(session.conn, 10))]
    head = [("analyze", "skipped"), ("discover", "skipped"), ("select", "skipped"), ("design", "ran"),
            ("implement", "ran"), ("run", "ran")]  # fmt: skip
    assert steps(first) == head
    assert (first.stop.step, first.stop.reason, first.stop.runtime_error) == ("run", "run_failed", True)
    assert "RUN-0003 ended error" in first.stop.message
    assert steps(second) == [*head, ("triage", "ran")]
    assert (second.stop.step, second.stop.reason) == ("triage", "question")
    assert runs[2:] == [
        ("RUN-0003", "base", "error"), ("RUN-0004", "base", "completed"), ("RUN-0005", "candidate", "completed"),
    ]  # fmt: skip
    assert script.remaining == 0


# Interruption -------------------------------------------------------------------------------------------------------


def test_an_interruption_in_a_model_step_stops_the_cycle_and_cycle_repeats_the_step(both_runs):
    interrupt = threading.Event()

    def press_escape(request):
        interrupt.set()  # the user presses Esc while the model answers
        return calls(call("memory__get_requirements"))

    script = Scripted([
        calls(call("runtime__load_skill", {"name": "impact-analysis"})), press_escape,
        *analyze_script(), *select_script("Saved. Should I continue?"),
    ])  # fmt: skip
    with start(both_runs, script, trust_commands=True, mode="auto") as session:
        first = cycle.run_cycle(session, interrupt=interrupt)
        second = cycle.run_cycle(session, interrupt=threading.Event())
    assert (first.stop.step, first.stop.reason, first.stop.runtime_error) == ("analyze", "interrupted", True)
    assert steps(second)[:3] == [("analyze", "ran"), ("discover", "skipped"), ("select", "ran")]
    assert script.remaining == 0


def running_run(project: Path, timeout: float = 120) -> str:
    """Wait until a run of ``project`` is running in its worktree."""
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


def test_an_interruption_during_a_run_stops_the_cycle_and_cycle_runs_again(designed):
    interrupt = threading.Event()
    seen: dict = {}

    def show(event):
        if isinstance(event, cycle.StepStarted) and event.name == "run":

            def press_escape():
                seen["run_id"] = running_run(designed)
                interrupt.set()

            seen["watcher"] = threading.Thread(target=press_escape, daemon=True)
            seen["watcher"].start()

    script = Scripted([*nothing_to_design_and_implement(), *nothing_to_design_and_implement(),
                       answer("Should I triage now?")])  # fmt: skip
    with start(designed, script, trust_commands=True, mode="auto") as session:
        first = cycle.run_cycle(session, interrupt=interrupt, show=show)
        seen["watcher"].join(5)
        interrupted = execution.get_run(session.conn, seen["run_id"])["status"]
        second = cycle.run_cycle(session, interrupt=threading.Event())
        statuses = [r["status"] for r in reversed(execution.list_runs(session.conn, 3))]
    assert (first.stop.step, first.stop.reason) == ("run", "interrupted")
    assert interrupted == "interrupted"
    assert ("run", "ran") in steps(second) and (second.stop.step, second.stop.reason) == ("triage", "question")
    assert statuses == ["interrupted", "completed", "completed"]


# Limits (SC-19) -----------------------------------------------------------------------------------------------------


def with_user_config(monkeypatch, tmp_path, extra: str) -> None:
    home = tmp_path / "home"
    write_user_config(home, extra)
    monkeypatch.setenv("RETRO_HOME", str(home))


def test_max_iterations_applies_to_each_step(both_runs, monkeypatch, tmp_path):
    with_user_config(monkeypatch, tmp_path, "agent:\n  max_iterations: 8\n")
    loop = [calls(call("memory__get_suite"))] * 8
    script = Scripted([*analyze_script(), *select_script(), *loop])  # 8 and 4 calls: each step stays in its limit
    with start(both_runs, script, trust_commands=True, mode="auto") as session:
        result = cycle.run_cycle(session)
    assert steps(result)[-1] == ("design", "ran")
    assert (result.stop.step, result.stop.reason, result.stop.runtime_error) == ("design", "limit", True)
    assert "agent.max_iterations" in result.stop.message
    assert script.remaining == 0


def test_the_truncation_guard_stops_the_cycle_and_ends_the_session(both_runs):
    quarter = FakeProvider(
        [calls(call("runtime__load_skill", {"name": "impact-analysis"}))],
        usage=lambda request, response: Usage(request_characters(request) // 16, 1),
    )
    with model(quarter):
        code, output = run_json(both_runs, "--trust-commands", "--mode", "auto", "-p", "/cycle")
    assert code == 1 and "context window" in output["result"]
    conn = connect(both_runs)
    try:
        assert execution.running_runs(conn) == []
        assert sessions.get_session(conn, output["session_id"])["ended_at"]
    finally:
        conn.close()


# Non-interactive mode -----------------------------------------------------------------------------------------------


def test_p_cycle_exits_1_when_an_outcome_is_still_missing(both_runs):
    with model(Scripted([*no_impact(), *no_impact()])):
        code, output = run_json(both_runs, "--trust-commands", "--mode", "auto", "-p", "/cycle")
    assert (code, output["recorded"], output["decision"]) == (1, {}, None)
    assert output["result"].startswith("The outcome of the step analyze is still missing after a retry")


def test_p_cycle_without_versions_is_invalid_usage(both_runs, capsys):
    config = both_runs / ".retro" / "config.yaml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("versions:\n  base: v1.0\n  candidate: v1.1\n", ""), encoding="utf-8")
    with model(FakeProvider()) as provider:
        code, _ = run_json(both_runs, "-p", "/cycle")
    assert code == 2 and provider.requests == []
    assert "the session versions are not set: use /cycle <base> <candidate>" in capsys.readouterr().err
