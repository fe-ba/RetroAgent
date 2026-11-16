"""The figures of ORACLE.md (shop-api) from the pure functions: cycle 1 without generated tests, and cycle 2.

Test cases are named by their test identifier here; the results are those of ORACLE.md, Raw results.
"""

from fixtures.reference_scenario import S1, S2, S3, S4, V1_0_TESTS, V1_1_NEW_TESTS, V1_1_TESTS

from retroagent.metrics.compute import Defect, EvaluationInputs, Execution, Ratio, Run, TestCase
from retroagent.metrics.criteria import Thresholds
from retroagent.metrics.evaluation import compute

THRESHOLDS = Thresholds(min_pass_rate=0.90)  # the project configuration of shop-api
V1_2_TESTS = [t for t in V1_1_TESTS if t != S2]  # v1.2 removes the obsolete coupon test

FAILING = {
    "v1.0": {S3: ("failed", "passed", "passed"), S4: ("failed",) * 3},
    "v1.1": {S3: ("failed", "passed", "passed"), S4: ("failed",) * 3, S1: ("failed",) * 3, S2: ("failed",) * 3},
    "v1.2": {S3: ("failed", "passed", "passed"), S4: ("failed",) * 3},
}


def version_run(run_id, version, tests, *, triage=None, defects=None, not_reported=()):
    triage, defects = triage or {}, defects or {}
    executions = []
    for test_id in tests:
        if test_id in not_reported:
            executions.append(Execution(test_id, "blocked"))
            continue
        attempts = FAILING[version].get(test_id, ("passed",))
        executions.append(
            Execution(
                test_id,
                "executed",
                attempts[0],
                attempts,
                triage.get(test_id),
                frozenset(defects.get(test_id, ())),
                0.001,
            )
        )
    return Run(run_id, tuple(executions), "2026-11-16T10:00:00.000+00:00", "2026-11-16T10:00:03.000+00:00")


def requirement_of(test_id):
    return "REQ-" + test_id.split("test_req_")[1][:3]


def suite_of(tests):
    return tuple(TestCase(t, "implemented", "high", frozenset({requirement_of(t)})) for t in tests)


def pct(ratio: Ratio) -> float:
    return round(float(ratio.value) * 100, 1)


def cycle_1(severity="high"):
    tests = V1_1_TESTS
    inputs = EvaluationInputs(
        run=version_run(
            "R",
            "v1.1",
            tests,
            triage={S1: "regression", S2: "expected_change", S3: "flaky", S4: "pre_existing"},
            defects={S1: {"DEF-001"}},
        ),
        suite=suite_of(tests),
        baseline=version_run("R0", "v1.0", tests, not_reported=V1_1_NEW_TESTS),
        full_base=version_run("F0", "v1.0", V1_0_TESTS),
        full_candidate=version_run("F", "v1.1", tests),
        impacted_requirement_ids=frozenset(f"REQ-00{n}" for n in range(2, 9)),
        defects=(Defect("DEF-001", severity, "open"),),
    )
    return compute(inputs, THRESHOLDS)


def test_cycle_1_figures():
    m, criteria, decision = cycle_1()
    assert (m["planned"], m["implemented"], m["executed"]) == (26, 26, 26)
    assert (m["passed"], m["failed"]) == (22, 4)
    assert m["pass_rate"] == Ratio(22, 26) and pct(m["pass_rate"]) == 84.6
    assert (m["excused"], m["pre_existing"]) == (1, 1)
    assert m["product_pass_rate"] == Ratio(22, 25) and pct(m["product_pass_rate"]) == 88.0
    assert m["flaky"] == 1 and m["flaky_rate"] == Ratio(1, 26) and pct(m["flaky_rate"]) == 3.8
    assert (m["new_failures"], m["unexcused_new_failures"]) == (2, 1)
    assert (m["fixed"], m["persistent_failures"], m["stable_passes"], m["not_comparable"]) == (0, 2, 18, 4)
    assert m["revealing"] == 2
    states = {c.id: c.state for c in criteria}
    assert (states["EC-01"], states["EC-05"], states["EC-07"], states["EC-08"], states["EC-09"]) == (
        "not_met",
        "not_met",
        "met",
        "met",
        "not_met",
    )
    assert decision.outcome == "do_not_release"


def test_cycle_1_decision_does_not_depend_on_the_severity_of_the_defect():
    for severity in ("critical", "high", "medium", "low"):
        _, _, decision = cycle_1(severity)
        assert decision.outcome == "do_not_release"
        assert {"EC-01", "EC-09"} <= {r.id for r in decision.reasons}


def cycle_2(baseline_tests):
    inputs = EvaluationInputs(
        run=version_run("R", "v1.2", V1_2_TESTS, triage={S3: "flaky", S4: "pre_existing"}),
        suite=suite_of(V1_2_TESTS),
        baseline=version_run("R0", "v1.1", baseline_tests),
        impacted_requirement_ids=frozenset({"REQ-005"}),
        defects=(Defect("DEF-001", "high", "closed"),),  # closed by the candidate run (slice 4)
    )
    return compute(inputs, THRESHOLDS)


def test_cycle_2_figures_and_decision():
    m, criteria, decision = cycle_2(baseline_tests=V1_2_TESTS)
    assert (m["planned"], m["implemented"], m["executed"]) == (25, 25, 25)
    assert (m["passed"], m["failed"]) == (23, 2)
    assert m["pass_rate"] == m["product_pass_rate"] == Ratio(23, 25) and pct(m["pass_rate"]) == 92.0
    assert (m["excused"], m["pre_existing"]) == (0, 1)
    assert m["flaky"] == 1 and m["flaky_rate"] == Ratio(1, 25) and pct(m["flaky_rate"]) == 4.0
    assert (m["new_failures"], m["unexcused_new_failures"]) == (0, 0)
    assert (m["fixed"], m["persistent_failures"], m["stable_passes"], m["not_comparable"]) == (1, 2, 22, 0)
    assert all(c.state == "met" for c in criteria if c.blocking)
    assert decision.outcome == "release_with_conditions"
    [condition] = decision.conditions
    assert condition.kind == "pre_existing"
    assert condition.test_cases == ({"test_case_id": S4, "classification": "pre_existing"},)
    assert condition.baseline_run_id == "R0"


def test_cycle_2_with_a_full_baseline_run_has_one_test_case_not_comparable():
    m, _, decision = cycle_2(baseline_tests=V1_1_TESTS)  # the full run against v1.1 still has the coupon test
    assert m["not_comparable"] == 1
    assert (m["fixed"], m["persistent_failures"], m["stable_passes"]) == (1, 2, 22)
    assert decision.outcome == "release_with_conditions"
