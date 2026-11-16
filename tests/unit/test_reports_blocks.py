"""Formatting rules, values, blocks and items of the reports (reports.md)."""

import time
from fractions import Fraction

import pytest
from fixtures.memory_records import BASE_COMMIT, CANDIDATE_COMMIT

from retroagent.memory import design
from retroagent.metrics import NotEvaluable, Ratio
from retroagent.metrics.criteria import CriterionResult
from retroagent.metrics.decision import Condition, Decision
from retroagent.metrics.evaluation import Evaluation
from retroagent.reports import blocks
from retroagent.reports.blocks import Context


@pytest.fixture
def local_time(monkeypatch):
    """The local time zone is UTC-5 (POSIX ``EST5``), whatever the machine."""
    monkeypatch.setenv("TZ", "EST5")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def context(conn, evaluation=None, base=True):
    return Context(
        conn=conn,
        report_id="RPT-0001",
        created_at="2026-11-15T22:30:00.000+00:00",
        model="fake/model",
        tool_version="0.1.0",
        project_name="shop",
        base=("v1.0", BASE_COMMIT) if base else None,
        candidate=("v1.1", CANDIDATE_COMMIT) if base else None,
        evaluation=evaluation,
    )


# Formatting


@pytest.mark.parametrize(
    "ratio, text",
    [
        (Fraction(23, 26), "88.5%"),
        (Fraction(22, 25), "88.0%"),
        (Fraction(1, 27), "3.7%"),
        (Fraction(1), "100.0%"),
        (Fraction(0), "0.0%"),
        (Fraction(5, 10000), "0.1%"),  # half up
        (Fraction(1, 20), "5.0%"),
    ],
)
def test_ratio_is_a_percentage_with_one_decimal(ratio, text):
    assert blocks.percent(ratio) == text


def test_values_by_kind():
    assert blocks.fmt(Ratio(22, 25)) == "88.0%"
    assert blocks.fmt(12) == "12"
    assert blocks.fmt(42.3) == "42.3 s"
    assert blocks.fmt(0.04) == "0.0 s"
    assert blocks.fmt(NotEvaluable("nothing was executed")) == "not evaluable"
    assert blocks.fmt(None) == "not evaluable"
    assert blocks.commit("c7d45ada468e3746c498cb3417999e117154a942") == "c7d45ad"
    assert blocks.commit(None) == "none"
    assert blocks.joined(["TC-004", "TC-007"]) == "TC-004, TC-007"
    assert blocks.joined([]) == "none"


def test_a_timestamp_is_in_the_local_time_zone_to_the_minute(local_time):
    assert blocks.timestamp("2026-11-15T15:00:59.123+00:00") == "2026-11-15T10:00-05:00"
    assert blocks.timestamp(None) == "none"


def test_a_value_is_one_line_and_never_breaks_its_table():
    assert blocks.one_line("a\nb\r\nc") == "a b c"
    assert blocks.one_line("x | y") == "x \\| y"
    table = blocks.table(["A", "B"], [["one\ntwo", "a|b"]])
    assert table == "| A | B |\n|---|---|\n| one two | a\\|b |"


def test_stored_text_cannot_open_a_comment_that_reads_as_an_agent_marker():
    assert "<!--" not in blocks.one_line("<!-- agent:conclusions -->")


# Values


def test_values_without_an_evaluation_or_versions(conn, local_time):
    values = blocks.values(context(conn, base=False))
    assert values["project.name"] == "shop" and values["report.id"] == "RPT-0001"
    assert values["report.generated_at"] == "2026-11-15T17:30-05:00"
    assert values["versions.base.ref"] == "none" and values["versions.base.commit"] == "none"
    assert values["run.id"] == "none" and values["decision.value"] == "not evaluable"
    assert values["suite.planned"] == "0" and values["suite.high_priority_planned"] == "0"
    assert "metrics.pass_rate" not in values


def test_suite_values_count_the_current_suite(build, conn):
    cases = [build.test_case(implemented=True), build.test_case(implemented=False)]
    build.suite(*cases)
    values = blocks.values(context(conn))
    assert [values[f"suite.{k}"] for k in ("planned", "implemented", "designed_only", "high_priority_planned")] == [
        "2",
        "1",
        "1",
        "2",
    ]
    assert values["versions.candidate.commit"] == "ccccccc"


def test_nested_metrics_have_dotted_names():
    values = blocks._metric_values("metrics.", {"passed": 3, "open_defects": {"high": 1}, "pass_rate": Ratio(1, 2)})
    assert values == {"metrics.passed": "3", "metrics.open_defects.high": "1", "metrics.pass_rate": "50.0%"}


# Criteria and the decision


def criterion(id, name, state, value, threshold, blocking=True, reason=None):
    return CriterionResult(id, name, state, value, threshold, blocking, reason)


def with_decision(conn, decision, criteria=()):
    return context(conn, Evaluation(1, None, {}, list(criteria), decision))


def test_thresholds_and_values_of_the_criteria_table(conn):
    criteria = [
        criterion("EC-01", "Product pass rate", "not_met", Ratio(23, 26), 0.9),
        criterion("EC-05", "High defects", "not_met", 1, 0),
        criterion("EC-06", "Medium defects", "met", 0, None, blocking=False),
        criterion("EC-07", "Flaky tests", "met", Ratio(1, 27), 0.05, blocking=False),
        criterion(
            "EC-08",
            "Failures triaged",
            "met",
            {"failures": 4, "triaged_failures": 4, "regressions": 1, "regressions_with_defect": 1},
            None,
        ),
        criterion(
            "EC-03", "Requirement coverage", "not_evaluable", None, 1.0, blocking=False, reason="no requirements"
        ),
    ]
    rows = blocks.criteria_table(with_decision(conn, Decision("do_not_release"), criteria)).split("\n")[2:]
    assert rows == [
        "| EC-01 | Product pass rate | at least 90.0% | 88.5% | `not_met` | Yes |",
        "| EC-05 | High defects | at most 0 | 1 | `not_met` | Yes |",
        "| EC-06 | Medium defects | none | 0 | `met` | No |",
        "| EC-07 | Flaky tests | at most 5.0% | 3.7% | `met` | No |",
        "| EC-08 | Failures triaged | none | 4 of 4 triaged, 1 of 1 regressions linked to a defect | `met` | Yes |",
        "| EC-03 | Requirement coverage | at least 100.0% | not evaluable | `not_evaluable` | No |",
    ]


def test_reasons_of_do_not_release_are_the_blocking_criteria(conn):
    reasons = (criterion("EC-01", "Product pass rate", "not_met", Ratio(23, 26), 0.9),)
    ctx = with_decision(conn, Decision("do_not_release", reasons=reasons))
    assert blocks.decision_reasons(ctx) == "- EC-01 Product pass rate: threshold at least 90.0%, value 88.5%."


def test_reasons_of_release_and_of_a_decision_that_cannot_be_evaluated(conn):
    assert blocks.decision_reasons(with_decision(conn, Decision("release"))) == "- All exit criteria are met."
    assert "only evaluated for runs against the candidate" in blocks.decision_reasons(context(conn))


def test_each_condition_of_release_with_conditions_is_one_item(conn):
    conditions = (
        Condition(
            "criterion_not_met", criterion=criterion("EC-07", "Flaky tests", "not_met", Ratio(3, 50), 0.05, False)
        ),
        Condition(
            "criterion_not_evaluable",
            criterion=criterion("EC-03", "Requirement coverage", "not_evaluable", None, 1.0, False, "no requirements"),
        ),
        Condition("excused", test_cases=({"test_case_id": "TC-014", "classification": "expected_change"},)),
        Condition(
            "pre_existing",
            test_cases=({"test_case_id": "TC-022", "classification": "pre_existing"},),
            baseline_run_id="RUN-0003",
        ),
        Condition("designed_only", test_cases=({"test_case_id": "TC-028"},)),
    )
    assert blocks.decision_reasons(with_decision(conn, Decision("release_with_conditions", conditions=conditions))) == (
        "- EC-07 Flaky tests: threshold at most 5.0%, value 6.0%.\n"
        "- EC-03 Requirement coverage: not evaluable (no requirements).\n"
        "- Test cases to update: TC-014 (`expected_change`).\n"
        "- Test cases that already failed against the baseline RUN-0003: TC-022.\n"
        "- Planned test cases never implemented: TC-028."
    )


def test_limitations_list_what_is_not_evaluable_and_then_the_fixed_ones(conn):
    evaluation = Evaluation(
        1,
        None,
        {"revealing": NotEvaluable("full runs against both versions are needed"), "passed": 3},
        [criterion("EC-03", "Requirement coverage", "not_evaluable", None, 1.0, False, "no requirements")],
        Decision("release"),
    )
    assert blocks.limitations_list(context(conn, evaluation)).split("\n") == [
        "- Metric `revealing` is not evaluable: full runs against both versions are needed.",
        "- Criterion EC-03 Requirement coverage is not evaluable: no requirements.",
        "- The number of flaky executions is a lower bound: a few reruns find only part of the flakiness.",
        "- Code coverage is not measured.",
    ]


# Empty messages and items


def test_empty_blocks_say_so(conn):
    ctx = context(conn)
    assert blocks.open_defects_table(ctx) == "No open defects."
    assert blocks.cases_table(ctx) == "The suite is empty."
    assert blocks.traceability_table(ctx) == "No documented requirements."


def test_a_test_case_item_shows_its_design_and_the_empty_messages_of_what_it_lacks(conn):
    design.add_test_case(
        conn,
        title="A quantity above the stock is rejected",
        objective="Refused.",
        priority="high",
        designed_by="fake/model",
        preconditions=["A product with stock 5"],
        input_data=[{"name": "quantity", "value": 6}],
        steps=["Add 6 units", "Look at the cart"],
        expected_result="Rejected | cart empty",
    )
    design.add_test_case(conn, title="Bare", priority="low", designed_by="fake/model")
    full, bare = (blocks.case_scope(context(conn), design.get_test_case(conn, t)) for t in ("TC-001", "TC-002"))
    assert full.values["test_case.origin"] == "designed by fake/model"
    assert full.values["test_case.implementation"] == "none" and full.values["test_case.last_execution"] == "none"
    assert full.values["test_case.expected_result"] == "Rejected \\| cart empty"
    assert full.blocks["list:preconditions"]() == "- A product with stock 5"
    assert full.blocks["table:input_data"]() == "| Name | Value |\n|---|---|\n| quantity | 6 |"
    assert full.blocks["list:steps"]() == "1. Add 6 units\n2. Look at the cart"
    assert bare.blocks["list:preconditions"]() == "No preconditions."
    assert bare.blocks["table:input_data"]() == "No input data."
    assert bare.blocks["list:steps"]() == "No steps recorded."
    assert bare.values["test_case.objective"] == "none"
