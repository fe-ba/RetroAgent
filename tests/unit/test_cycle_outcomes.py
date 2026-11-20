"""The outcome checks of ``/cycle``: what is done and what is missing for each step, read from project memory
(runtime.md, Cycle command), on the records of the reference scenario of shop-api at each stage of the cycle."""

import pytest
from fixtures import reference_scenario as ref

from retroagent.memory import connect, impact, reporting, sessions
from retroagent.runtime.cycle import STEPS, done, ends_with_question, has_test_file, is_test_file, missing, progress
from retroagent.runtime.session import Version

V1_0 = Version(ref.BASE_REF, ref.BASE_COMMIT)
V1_1 = Version(ref.CANDIDATE_REF, ref.CANDIDATE_COMMIT)
V1_2 = Version("v1.2", ref.V1_2_COMMIT)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path)
    yield connection
    connection.close()


@pytest.mark.parametrize(
    "path, expected",
    [
        ("tests/test_api.py", True),
        ("tests/conftest.py", True),  # a folder named tests
        ("test/helpers.js", True),
        ("web/__tests__/cart.js", True),
        ("spec/models/cart_spec.rb", True),
        ("test_cart.py", True),
        ("pkg/cart/cart_test.go", True),
        ("web/cart.test.ts", True),
        ("web/cart.spec.js", True),
        ("src/test/java/shop/CartTest.java", True),
        ("src/main/java/shop/CartTest.java", True),  # the name alone
        ("src/shop/pricing.py", False),
        ("src/shop/contest.py", False),
        ("docs/testing.md", False),
        ("tests.py", False),
        ("src/latest/cart.py", False),  # "latest" is not "test"
    ],
)
def test_a_test_file_is_named_by_its_folder_or_its_name(path, expected):
    assert is_test_file(path) is expected


def changed(path, change="modified", added=1, removed=0, old_path=None):
    return {"path": path, "old_path": old_path, "change": change, "lines_added": added, "lines_removed": removed}


# The change set of v1.1..v1.2: shipping fixed, the obsolete coupon test removed.
CYCLE_2_FILES = [
    changed("src/shop/pricing.py", added=3, removed=2),
    changed("tests/test_discounts.py", added=0, removed=8),
]


@pytest.mark.parametrize(
    "files, expected",
    [
        ([changed("tests/test_cart.py", "added", 10)], True),
        ([changed("tests/test_cart.py", "renamed", 0, old_path="tests/test_basket.py")], True),
        ([changed("tests/test_cart.py", "modified", 3, 1)], True),
        ([changed("tests/test_cart.py", "modified", 0, 8)], True),  # only removes lines: a test may be deleted
        ([changed("tests/test_cart.py", "deleted", 0, 20)], True),
        ([changed("src/shop/helpers.py", "renamed", 0, old_path="tests/helpers.py")], True),  # renamed out of tests
        ([changed("src/shop/pricing.py", "renamed", 0, old_path="src/shop/prices.py")], False),
        ([changed("src/shop/cart.py", "added", 30), changed("README.md", "modified", 2, 2)], False),
        ([], False),
    ],
)
def test_a_change_set_has_a_test_file_whatever_the_change(files, expected):
    assert has_test_file(files) is expected


def test_the_change_sets_of_the_oracle():
    # cycle 1 modifies three test files with lines added; cycle 2 removes a test (ORACLE.md, S6 and v1.2)
    assert has_test_file(ref.CHANGE_SET)
    assert has_test_file(CYCLE_2_FILES)


def test_without_records_only_the_analysis_is_missing(conn):
    p = progress(conn, V1_0, V1_1)
    assert missing("analyze", p) == (
        "there is no analysis of v1.0..v1.1: call git__analyze_changes, then memory__save_impact"
    )
    assert [step for step in STEPS if done(step, p) is not None] == []


def test_an_analysis_without_impact_is_missing_its_impact(conn):
    session_id = sessions.start_session(conn, model="none", interactive=False, result_char_limit=8000)
    analysis_id = impact.add_analysis(
        conn, session_id=session_id, base_ref="v1.0", base_commit=V1_0.commit, candidate_ref="v1.1",
        candidate_commit=V1_1.commit, files=ref.CHANGE_SET,
    )  # fmt: skip
    p = progress(conn, V1_0, V1_1)
    assert missing("analyze", p) == (
        f"analysis {analysis_id} has no impact recorded: call memory__save_impact with its analysis_id"
    )
    # the change set has test files: both full runs are needed
    assert p.full_runs_missing == ("base", "candidate")
    assert missing("discover", p) == "no completed full run against the base v1.0 and the candidate v1.1"


def test_cycle_1_before_triage_every_step_up_to_run_is_done(conn):
    scenario = ref.load_reference_scenario(conn, triage=False)
    p = progress(conn, V1_0, V1_1)
    assert p.full_runs_missing == () and p.suite_id == scenario.suite_id
    assert {step: done(step, p) is not None for step in STEPS} == {
        "analyze": True, "discover": True, "select": True, "design": True, "implement": True, "run": True,
        "triage": False, "report": False,
    }  # fmt: skip
    assert done("run", p) == "RUN-0003 and RUN-0004 are completed"
    assert missing("triage", p).startswith("RUN-0004 has 4 failed or error executions without triage")
    assert missing("design", p) is None and missing("implement", p) is None  # no outcome checked by code


def test_cycle_1_after_triage_only_the_report_is_missing(conn):
    ref.load_reference_scenario(conn)
    p = progress(conn, V1_0, V1_1)
    assert done("triage", p) == "no failure of RUN-0004 is left without triage"
    assert missing("report", p) == (
        "no completion report of RUN-0004 is rendered: call reports__prepare_report with type completion, then"
        " reports__render_report with its sections"
    )


def evaluation(conn, run_id):
    return reporting.add_evaluation(
        conn, run_id=run_id, thresholds={}, metrics={}, criteria=[], decision="do_not_release",
        decision_details={}, tool_version="test",
    )  # fmt: skip


def test_only_a_rendered_completion_report_of_the_evaluated_run_finishes_the_cycle(conn):
    scenario = ref.load_reference_scenario(conn)
    draft = reporting.add_report(conn, type="completion", model="none", evaluation_id=evaluation(conn, "RUN-0004"))
    other = reporting.add_report(conn, type="completion", model="none", evaluation_id=evaluation(conn, "RUN-0002"))
    reporting.mark_rendered(conn, other, ["md"])  # a report of another run
    assert done("report", progress(conn, V1_0, V1_1)) is None
    reporting.mark_rendered(conn, draft, ["md"])
    p = progress(conn, V1_0, V1_1)
    assert p.report_id == draft and done("report", p) == f"{draft} is rendered for {scenario.evaluated_run}"
    assert all(done(step, p) is not None for step in STEPS)


def analysis_of_v1_2(conn, files) -> None:
    session_id = sessions.start_session(conn, model="none", interactive=False, result_char_limit=8000)
    impact.add_analysis(
        conn, session_id=session_id, base_ref="v1.1", base_commit=V1_1.commit, candidate_ref="v1.2",
        candidate_commit=V1_2.commit, files=files,
    )  # fmt: skip


def test_cycle_2_needs_a_full_run_on_the_candidate_only(conn):
    # v1.1 has a completed full run (RUN-0002, against the candidate of cycle 1); v1.2 deletes a test, so the full
    # run against v1.2 shows which tests exist there
    scenario = ref.load_reference_scenario(conn)
    analysis_of_v1_2(conn, CYCLE_2_FILES)
    p = progress(conn, V1_1, V1_2)
    assert p.full_runs_missing == ("candidate",)
    assert missing("discover", p) == "no completed full run against the candidate v1.2"
    assert scenario.full_candidate_run == "RUN-0002"


def test_a_change_without_a_test_file_needs_no_full_run_on_the_candidate(conn):
    ref.load_reference_scenario(conn)
    analysis_of_v1_2(conn, [changed("src/shop/pricing.py", added=3, removed=2)])
    p = progress(conn, V1_1, V1_2)
    assert p.full_runs_missing == () and done("discover", p) == "completed full runs exist for v1.1..v1.2"
    assert missing("select", p) == (
        f"analysis {p.analysis_id} has no suite: call memory__save_suite with its analysis_id"
    )


def test_the_full_run_on_the_candidate_is_skipped_when_a_completed_one_exists_on_its_commit(conn):
    from retroagent.memory import execution

    scenario = ref.load_reference_scenario(conn)
    analysis_of_v1_2(conn, CYCLE_2_FILES)
    for status in ("error", "completed"):  # only a completed one counts
        run_id = execution.start_run(
            conn, version_role="candidate", ref="v1.2", commit=V1_2.commit, scope="all", command="pytest",
            session_id=scenario.session_id,
        )  # fmt: skip
        execution.finish_run(conn, run_id, status=status, exit_code=None if status == "error" else 1)
        p = progress(conn, V1_1, V1_2)
        assert p.full_runs_missing == (() if status == "completed" else ("candidate",))
    assert done("discover", p) == "completed full runs exist for v1.1..v1.2"


def test_cycle_2_records_are_done_up_to_the_report(conn):
    scenario = ref.load_reference_scenario(conn)
    cycle = ref.load_cycle_2(conn, scenario)
    p = progress(conn, V1_1, V1_2)
    assert p.suite_id == cycle.suite_id and p.candidate_run["id"] == cycle.evaluated_run
    assert [step for step in STEPS if done(step, p) is None] == ["report"]


def test_a_run_that_did_not_complete_is_missing_from_the_run_step(conn):
    from retroagent.memory import execution

    scenario = ref.load_reference_scenario(conn)
    run_id = execution.start_run(
        conn, version_role="candidate", ref="v1.1", commit=V1_1.commit, scope="suite", command="pytest",
        session_id=scenario.session_id, suite_id=scenario.suite_id,
    )  # fmt: skip
    execution.finish_run(conn, run_id, status="error", error="setup: exit code 1")
    p = progress(conn, V1_0, V1_1)
    assert p.suite_runs_not_completed == ("candidate",)
    assert missing("run", p) == f"suite {scenario.suite_id} has no completed run against the candidate v1.1"
    assert done("design", p) is None and done("implement", p) is None and done("triage", p) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Which versions should I compare?", True),
        ("The impact is recorded.\n\nShould I continue with `/select`?\n\n", True),
        ("**Do you want the report anyway?**", True),
        ("The suite is saved.\n\nNext step: `/design`.", False),
        ("Is REQ-002 impacted? Yes: cart.py changed.\n\nNext step: /select.", False),
        ("", False),
    ],
)
def test_a_step_ends_with_a_question_when_its_last_line_asks(text, expected):
    assert ends_with_question(text) is expected
