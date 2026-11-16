"""Evaluation on project memory: the reference scenario of shop-api against the expected completion report,
the selection rules of the inputs, the stored record, and determinism."""

import json
from dataclasses import replace

import pytest
from conftest import BASE_COMMIT, CANDIDATE_COMMIT
from fixtures import reference_scenario as ref

from retroagent.memory import execution, impact
from retroagent.metrics import EvaluationError, OpenDefectLimits, Thresholds, evaluate, load_inputs
from retroagent.metrics.compute import Ratio
from retroagent.metrics.evaluation import compute

THRESHOLDS = Thresholds(min_pass_rate=ref.MIN_PASS_RATE)


@pytest.fixture
def scenario(conn):
    return ref.load_reference_scenario(conn)


def pct(value):
    return round(float(value.value) * 100, 1)


def evaluations(conn):
    return conn.execute("SELECT * FROM evaluation ORDER BY id").fetchall()


# The expected report (expected/test-completion-report.md), sections 3, 5, 6 and 7


def test_reference_scenario_section_3_scope(conn, scenario):
    m = evaluate(conn, ref.CANDIDATE_COMMIT, thresholds=THRESHOLDS).metrics
    assert (m["planned"], m["implemented"], m["designed_only"], m["executed"]) == (28, 27, 1, 27)
    assert m["implementation_rate"] == Ratio(27, 28) and pct(m["implementation_rate"]) == 96.4
    assert m["execution_rate"] == Ratio(27, 28) and pct(m["execution_rate"]) == 96.4


def test_reference_scenario_section_5_exit_criteria(conn, scenario):
    criteria = evaluate(conn, ref.CANDIDATE_COMMIT, thresholds=THRESHOLDS).criteria
    rows = {c.id: (c.threshold, c.value, c.state, c.blocking) for c in criteria}
    assert rows["EC-01"] == (0.9, Ratio(23, 26), "not_met", True) and pct(rows["EC-01"][1]) == 88.5
    assert rows["EC-02"] == (1.0, Ratio(15, 15), "met", True)
    assert rows["EC-03"] == (1.0, Ratio(7, 7), "met", False)
    assert rows["EC-04"] == (0, 0, "met", True)
    assert rows["EC-05"] == (0, 1, "not_met", True)
    assert rows["EC-06"] == (None, 0, "met", False)
    assert rows["EC-07"] == (0.05, Ratio(1, 27), "met", False) and pct(rows["EC-07"][1]) == 3.7
    triage = {"failures": 4, "triaged_failures": 4, "regressions": 1, "regressions_with_defect": 1}
    assert rows["EC-08"] == (None, triage, "met", True)
    assert rows["EC-09"] == (0, 1, "not_met", True)
    assert [c.state for c in criteria].count("met") == 6


def test_reference_scenario_section_6_test_measures(conn, scenario):
    m = evaluate(conn, ref.CANDIDATE_COMMIT, thresholds=THRESHOLDS).metrics
    # Results
    assert m["pass_rate"] == Ratio(23, 27) and pct(m["pass_rate"]) == 85.2
    assert (m["excused"], m["pre_existing"], m["flaky"]) == (1, 1, 1)
    assert pct(m["product_pass_rate"]) == 88.5
    assert pct(m["flaky_rate"]) == 3.7
    # Coverage
    assert (m["impacted_requirements"], m["covered_requirements"]) == (7, 7)
    assert pct(m["requirement_coverage"]) == 100.0
    assert m["high_priority_planned"] == 15 and pct(m["high_priority_executed_rate"]) == 100.0
    # Comparison with the baseline
    assert (m["new_failures"], m["unexcused_new_failures"], m["fixed"]) == (2, 1, 0)
    assert (m["persistent_failures"], m["stable_passes"], m["not_comparable"]) == (2, 19, 4)
    # Selection quality
    assert m["revealing"] == 2
    assert m["selection_inclusiveness"] == Ratio(2, 2) and pct(m["selection_inclusiveness"]) == 100.0
    assert m["selection_precision"] == Ratio(0, 19) and pct(m["selection_precision"]) == 0.0


def test_reference_scenario_section_7_defects(conn, scenario):
    m = evaluate(conn, ref.CANDIDATE_COMMIT, thresholds=THRESHOLDS).metrics
    assert (m["defects_found"], m["defects_closed"]) == (1, 0)
    assert m["open_defects"] == {"critical": 0, "high": 1, "medium": 0, "low": 0}


def test_reference_scenario_decision_and_its_reasons(conn, scenario):
    decision = evaluate(conn, ref.CANDIDATE_COMMIT, thresholds=THRESHOLDS).decision
    assert decision.outcome == "do_not_release"
    assert [(r.id, r.state) for r in decision.reasons] == [
        ("EC-01", "not_met"),
        ("EC-05", "not_met"),
        ("EC-09", "not_met"),
    ]


def test_reference_scenario_inputs(conn, scenario):
    inputs = load_inputs(conn, ref.CANDIDATE_COMMIT)
    assert (inputs.run.id, inputs.baseline.id) == ("RUN-0004", "RUN-0003")
    assert (inputs.full_base.id, inputs.full_candidate.id) == ("RUN-0001", "RUN-0002")
    assert inputs.analysis_id == scenario.analysis_id
    assert [t.id for t in inputs.suite] == [f"TC-{n:03d}" for n in range(1, 29)]
    seeded = {e.test_case_id: e for e in inputs.run.executions}
    assert seeded[scenario.tc(ref.S3)].attempts == ("failed", "passed", "passed")
    assert seeded[scenario.tc(ref.S2)].triage == "expected_change"
    assert seeded[scenario.tc(ref.S1)].defect_ids == {"DEF-001"}


# The stored record


def test_evaluation_record_stores_inputs_values_and_decision_details(conn, scenario):
    result = evaluate(conn, ref.CANDIDATE_COMMIT, thresholds=THRESHOLDS)
    [row] = evaluations(conn)
    assert row["id"] == result.id
    assert (row["run_id"], row["baseline_run_id"]) == ("RUN-0004", "RUN-0003")
    assert (row["full_base_run_id"], row["full_candidate_run_id"]) == ("RUN-0001", "RUN-0002")
    assert row["analysis_id"] == scenario.analysis_id
    assert row["decision"] == "do_not_release"
    assert row["tool_version"] == "0.1.0"
    thresholds = json.loads(row["thresholds"])
    assert thresholds["min_pass_rate"] == 0.9
    assert thresholds["max_open_defects"] == {"critical": 0, "high": 0, "medium": None}
    metrics = json.loads(row["metrics"])
    assert metrics["product_pass_rate"] == {"numerator": 23, "denominator": 26}
    assert metrics["open_defects"]["high"] == 1
    criteria = json.loads(row["criteria"])
    assert [c["id"] for c in criteria] == [f"EC-0{n}" for n in range(1, 10)]
    assert criteria[0] == {
        "id": "EC-01",
        "name": "Product pass rate",
        "state": "not_met",
        "value": {"numerator": 23, "denominator": 26},
        "threshold": 0.9,
        "blocking": True,
        "reason": None,
    }
    details = json.loads(row["decision_details"])
    assert [r["id"] for r in details["reasons"]] == ["EC-01", "EC-05", "EC-09"]
    assert details["conditions"] == []


def test_conditions_are_stored_with_their_test_cases(conn, scenario):
    # With the defect counted as allowed and one new failure accepted, the scenario releases with conditions.
    thresholds = Thresholds(min_pass_rate=0.85, max_new_failures=1, max_open_defects=OpenDefectLimits(high=1))
    evaluate(conn, ref.CANDIDATE_COMMIT, thresholds=thresholds)
    [row] = evaluations(conn)
    assert row["decision"] == "release_with_conditions"
    conditions = json.loads(row["decision_details"])["conditions"]
    assert [c["kind"] for c in conditions] == ["excused", "pre_existing", "designed_only"]
    excused, pre_existing, designed_only = conditions
    assert excused["test_cases"] == [{"test_case_id": scenario.tc(ref.S2), "classification": "expected_change"}]
    assert pre_existing["test_cases"] == [{"test_case_id": scenario.tc(ref.S4), "classification": "pre_existing"}]
    assert pre_existing["baseline_run_id"] == "RUN-0003"
    assert designed_only["test_cases"] == [{"test_case_id": scenario.tc_028}]


def test_not_evaluable_metrics_are_stored_as_null(conn, build):
    test_case_id = build.test_case()
    suite_id = build.suite(test_case_id)
    run_id = build.run(scope="suite", suite_id=suite_id)
    build.execute(run_id, test_case_id)
    execution.finish_run(conn, run_id, status="completed", exit_code=0)
    result = evaluate(conn, CANDIDATE_COMMIT)
    assert result.inputs.baseline is None
    [row] = evaluations(conn)
    metrics = json.loads(row["metrics"])
    assert metrics["unexcused_new_failures"] is None and metrics["revealing"] is None
    assert row["baseline_run_id"] is None
    assert row["decision"] == "do_not_release"
    [reason] = json.loads(row["decision_details"])["reasons"]
    assert (reason["id"], reason["state"], reason["value"]) == ("EC-09", "not_evaluable", None)


def test_without_a_baseline_run_ec_09_is_not_evaluable_and_nothing_is_released(conn, scenario):
    inputs = replace(load_inputs(conn, ref.CANDIDATE_COMMIT), baseline=None)
    _, criteria, decision = compute(inputs, THRESHOLDS)
    ec_09 = next(c for c in criteria if c.id == "EC-09")
    assert ec_09.state == "not_evaluable"
    assert decision.outcome == "do_not_release"
    assert "EC-09" in [r.id for r in decision.reasons]


def test_evaluating_twice_gives_identical_values(conn, scenario):
    first = evaluate(conn, ref.CANDIDATE_COMMIT, thresholds=THRESHOLDS)
    second = evaluate(conn, ref.CANDIDATE_COMMIT, thresholds=THRESHOLDS)
    assert (first.metrics, first.criteria, first.decision) == (second.metrics, second.criteria, second.decision)
    one, two = evaluations(conn)
    assert one["id"] != two["id"]
    for column in one.keys():
        if column not in ("id", "created_at"):
            assert one[column] == two[column], column


# Selection of the inputs


def completed_run(conn, session_id, *, role, commit, scope, suite_id=None):
    run_id = execution.start_run(
        conn,
        version_role=role,
        ref="x",
        commit=commit,
        scope=scope,
        command="pytest",
        session_id=session_id,
        suite_id=suite_id,
    )
    execution.finish_run(conn, run_id, status="completed", exit_code=0)
    return run_id


def test_runs_of_the_other_role_are_never_used_even_on_the_same_commit(conn, scenario):
    session_id = scenario.session_id
    completed_run(conn, session_id, role="candidate", commit=ref.BASE_COMMIT, scope="all")
    completed_run(conn, session_id, role="base", commit=ref.CANDIDATE_COMMIT, scope="all")
    inputs = load_inputs(conn, ref.CANDIDATE_COMMIT)
    assert (inputs.baseline.id, inputs.full_base.id, inputs.full_candidate.id) == ("RUN-0003", "RUN-0001", "RUN-0002")


def test_baseline_run_is_the_latest_completed_base_run_of_any_scope(conn, scenario):
    unfinished = execution.start_run(
        conn,
        version_role="base",
        ref="v1.0",
        commit=ref.BASE_COMMIT,
        scope="selected",
        command="pytest",
        session_id=scenario.session_id,
    )
    execution.finish_run(conn, unfinished, status="error", error="setup failed")
    assert load_inputs(conn, ref.CANDIDATE_COMMIT).baseline.id == "RUN-0003"
    latest = completed_run(conn, scenario.session_id, role="base", commit=ref.BASE_COMMIT, scope="selected")
    assert load_inputs(conn, ref.CANDIDATE_COMMIT).baseline.id == latest
    assert load_inputs(conn, ref.CANDIDATE_COMMIT).full_base.id == "RUN-0001"  # full runs have scope all


def test_explicit_evaluated_run(conn, scenario):
    assert load_inputs(conn, ref.CANDIDATE_COMMIT, run_id="RUN-0004").run.id == "RUN-0004"
    running = execution.start_run(
        conn,
        version_role="candidate",
        ref="v1.1",
        commit=ref.CANDIDATE_COMMIT,
        scope="suite",
        command="pytest",
        session_id=scenario.session_id,
        suite_id=scenario.suite_id,
    )
    for run_id in ("RUN-0003", "RUN-0002", "RUN-0099", running):  # base, scope all, unknown, not completed
        with pytest.raises(EvaluationError):
            evaluate(conn, ref.CANDIDATE_COMMIT, run_id=run_id)
    assert evaluations(conn) == []


def test_default_evaluated_run_is_the_latest_completed_suite_run_against_the_candidate(conn, scenario):
    later = completed_run(
        conn, scenario.session_id, role="candidate", commit=ref.CANDIDATE_COMMIT, scope="suite", suite_id=1
    )
    assert load_inputs(conn, ref.CANDIDATE_COMMIT).run.id == later
    with pytest.raises(EvaluationError, match="no completed suite run"):
        load_inputs(conn, "0" * 40)


def test_evaluated_run_must_be_on_the_candidate_commit_of_its_analysis(conn, build):
    other = impact.add_analysis(
        conn,
        session_id=build.session_id,
        base_ref="v1.0",
        base_commit=BASE_COMMIT,
        candidate_ref="v1.2",
        candidate_commit="d" * 40,
        files=[],
    )
    test_case_id = build.test_case()
    build.analysis_id = other
    suite_id = build.suite(test_case_id)
    run_id = build.run(scope="suite", suite_id=suite_id)
    execution.finish_run(conn, run_id, status="completed", exit_code=0)
    with pytest.raises(EvaluationError, match="not on the candidate commit of analysis"):
        evaluate(conn, CANDIDATE_COMMIT)
    assert evaluations(conn) == []
