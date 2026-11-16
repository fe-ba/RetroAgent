"""The release decision rule (docs/reference/metrics.md): every branch and every kind of condition."""

from dataclasses import replace

from test_metrics_compute import blocked, case, ex, run

from retroagent.metrics.compute import Defect, EvaluationInputs
from retroagent.metrics.criteria import Thresholds
from retroagent.metrics.evaluation import compute


def good_inputs(**changes):
    """Four test cases that pass against both versions; the impacted requirement is covered; no defect."""
    ids = ["TC-001", "TC-002", "TC-003", "TC-004"]
    values = {
        "run": run(*(ex(t) for t in ids)),
        "suite": tuple(case(t, priority="high", requirements={"REQ-001"}) for t in ids),
        "baseline": run(*(ex(t) for t in ids), run_id="RUN-0001"),
        "impacted_requirement_ids": frozenset({"REQ-001"}),
    }
    values.update(changes)
    return EvaluationInputs(**values)


def with_candidate(inputs, test_case_id, execution):
    executions = tuple(execution if e.test_case_id == test_case_id else e for e in inputs.run.executions)
    return replace(inputs, run=replace(inputs.run, executions=executions))


def decide(inputs, thresholds=None):
    return compute(inputs, thresholds or Thresholds())[2]


def test_release():
    decision = decide(good_inputs())
    assert (decision.outcome, decision.reasons, decision.conditions) == ("release", (), ())


def test_condition_for_a_non_blocking_criterion_not_met():
    inputs = good_inputs(impacted_requirement_ids=frozenset({"REQ-001", "REQ-002"}))
    decision = decide(inputs)
    assert decision.outcome == "release_with_conditions"
    [condition] = decision.conditions
    assert condition.kind == "criterion_not_met"
    assert (condition.criterion.id, condition.criterion.threshold) == ("EC-03", 1.0)
    assert condition.criterion.value.numerator == 1 and condition.criterion.value.denominator == 2


def test_condition_for_a_non_blocking_criterion_not_evaluable():
    decision = decide(good_inputs(has_requirements=False))
    assert decision.outcome == "release_with_conditions"
    [condition] = decision.conditions
    assert (condition.kind, condition.criterion.id) == ("criterion_not_evaluable", "EC-03")
    assert condition.criterion.reason == "the project has no documented requirements"


def test_condition_for_excused_failures():
    inputs = with_candidate(good_inputs(), "TC-002", ex("TC-002", "failed", triage="expected_change"))
    inputs = with_candidate(inputs, "TC-003", ex("TC-003", "error", triage="test_defect"))
    decision = decide(inputs)
    assert decision.outcome == "release_with_conditions"
    [condition] = decision.conditions
    assert condition.kind == "excused"
    assert condition.test_cases == (
        {"test_case_id": "TC-002", "classification": "expected_change"},
        {"test_case_id": "TC-003", "classification": "test_defect"},
    )


def test_condition_for_pre_existing_failures():
    inputs = good_inputs(
        baseline=run(ex("TC-001"), ex("TC-002"), ex("TC-003"), ex("TC-004", "failed"), run_id="RUN-0007")
    )
    inputs = with_candidate(inputs, "TC-004", ex("TC-004", "failed", triage="pre_existing"))
    decision = decide(inputs, Thresholds(min_pass_rate=0.75))
    assert decision.outcome == "release_with_conditions"
    [condition] = decision.conditions
    assert condition.kind == "pre_existing"
    assert condition.test_cases == ({"test_case_id": "TC-004", "classification": "pre_existing"},)
    assert condition.baseline_run_id == "RUN-0007"


def test_condition_for_designed_only_test_cases():
    inputs = good_inputs()
    inputs = replace(inputs, suite=(*inputs.suite, case("TC-005", status="designed", priority="medium")))
    decision = decide(inputs)
    assert decision.outcome == "release_with_conditions"
    [condition] = decision.conditions
    assert (condition.kind, condition.test_cases) == ("designed_only", ({"test_case_id": "TC-005"},))


def test_one_condition_per_cause_in_order():
    inputs = good_inputs(has_requirements=False)
    inputs = with_candidate(inputs, "TC-002", ex("TC-002", "failed", triage="test_defect"))
    inputs = replace(inputs, suite=(*inputs.suite, case("TC-005", status="designed")))
    decision = decide(inputs)
    assert [c.kind for c in decision.conditions] == ["criterion_not_evaluable", "excused", "designed_only"]


def test_do_not_release_when_a_blocking_criterion_is_not_met():
    inputs = good_inputs(defects=(Defect("DEF-001", "high", "open"),), has_requirements=False)
    decision = decide(inputs)
    assert decision.outcome == "do_not_release"
    assert [(r.id, r.state) for r in decision.reasons] == [("EC-05", "not_met")]
    assert decision.conditions == ()  # conditions belong to release_with_conditions only


def test_do_not_release_when_a_blocking_criterion_is_not_evaluable():
    decision = decide(good_inputs(baseline=None))
    assert decision.outcome == "do_not_release"
    [reason] = decision.reasons
    assert (reason.id, reason.state, reason.reason) == ("EC-09", "not_evaluable", "there is no baseline run")


def test_nothing_executed_is_not_released():
    inputs = good_inputs(run=run(*(blocked(t) for t in ("TC-001", "TC-002", "TC-003", "TC-004"))))
    decision = decide(inputs)
    assert decision.outcome == "do_not_release"
    assert [(r.id, r.state) for r in decision.reasons] == [
        ("EC-01", "not_evaluable"),
        ("EC-02", "not_met"),
        ("EC-09", "not_evaluable"),
    ]
