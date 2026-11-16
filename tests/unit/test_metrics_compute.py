"""Every formula of docs/reference/metrics.md on plain data, with each not evaluable and vacuous case."""

from fractions import Fraction

from retroagent.metrics.compute import (
    VACUOUS,
    Defect,
    EvaluationInputs,
    Execution,
    NotEvaluable,
    Ratio,
    Run,
    TestCase,
    compute_metrics,
    to_json,
)


def ex(test_case_id, *attempts, triage=None, defects=(), duration=0.5):
    """An executed execution; the first attempt is the result, the others are reruns."""
    attempts = attempts or ("passed",)
    return Execution(test_case_id, "executed", attempts[0], tuple(attempts), triage, frozenset(defects), duration)


def blocked(test_case_id):
    return Execution(test_case_id, "blocked")


def skipped(test_case_id):
    return Execution(test_case_id, "skipped")


def case(test_case_id, status="implemented", priority="medium", requirements=()):
    return TestCase(test_case_id, status, priority, frozenset(requirements))


def run(*executions, run_id="RUN-0002", started="2026-11-16T10:00:00.000+00:00", ended="2026-11-16T10:00:03.400+00:00"):
    return Run(run_id, tuple(executions), started, ended)


def metrics(*executions, suite=None, **inputs):
    if suite is None:
        suite = tuple(case(e.test_case_id) for e in executions)
    return compute_metrics(EvaluationInputs(run=run(*executions), suite=tuple(suite), **inputs))


def is_not_evaluable(value):
    return isinstance(value, NotEvaluable) and value.reason


# Scope


def test_scope_counts_and_rates():
    suite = [case("TC-001"), case("TC-002"), case("TC-003"), case("TC-004", status="designed")]
    m = metrics(ex("TC-001"), blocked("TC-002"), skipped("TC-003"), suite=suite)
    assert (m["planned"], m["implemented"], m["designed_only"]) == (4, 3, 1)
    assert (m["executed"], m["blocked"], m["skipped"]) == (1, 1, 1)
    assert m["implementation_rate"] == Ratio(3, 4)
    assert m["execution_rate"] == Ratio(1, 4)


def test_scope_rates_are_not_evaluable_when_nothing_is_planned():
    m = metrics(suite=[])
    assert m["planned"] == 0
    assert is_not_evaluable(m["implementation_rate"])
    assert is_not_evaluable(m["execution_rate"])


# Results


def test_result_is_the_first_attempt():
    m = metrics(ex("TC-001", "failed", "passed", "passed"), ex("TC-002", "error", "failed"), ex("TC-003"))
    assert (m["passed"], m["failed"], m["error"]) == (1, 1, 1)
    assert m["pass_rate"] == Ratio(1, 3)


def test_rates_of_results_are_not_evaluable_when_nothing_was_executed():
    m = metrics(blocked("TC-001"))
    for name in ("pass_rate", "product_pass_rate", "flaky_rate"):
        assert is_not_evaluable(m[name]), name


def test_excused_counts_only_expected_change_and_test_defect_failures():
    m = metrics(
        ex("TC-001", "failed", triage="expected_change"),
        ex("TC-002", "error", triage="test_defect"),
        ex("TC-003", "failed", triage="regression"),
        ex("TC-004", "failed", triage="flaky"),
        ex("TC-005", "failed", triage="environment"),
        ex("TC-006", "failed", triage="pre_existing"),
        ex("TC-007", "failed"),
        ex("TC-008"),
    )
    assert m["excused"] == 2
    assert m["pre_existing"] == 1
    assert m["product_pass_rate"] == Ratio(1, 6)  # pre-existing failures are not excused


def test_product_pass_rate_is_not_evaluable_when_every_execution_is_excused():
    m = metrics(ex("TC-001", "failed", triage="test_defect"))
    assert m["pass_rate"] == Ratio(0, 1)
    assert is_not_evaluable(m["product_pass_rate"])


def test_flaky_means_a_rerun_passed():
    m = metrics(
        ex("TC-001", "failed", "passed", "failed"),  # flaky
        ex("TC-002", "error", "failed", "error"),  # failed and error have the same verdict
        ex("TC-003", "failed", "failed", "failed"),
        ex("TC-004"),
    )
    assert m["flaky"] == 1
    assert m["flaky_rate"] == Ratio(1, 4)
    assert (m["failed"], m["error"]) == (2, 1)  # the flaky execution keeps the result of its first attempt


# Coverage


def test_requirement_coverage_counts_impacted_requirements_traced_to_an_executed_execution():
    suite = [case("TC-001", requirements={"REQ-001"}), case("TC-002", requirements={"REQ-002", "REQ-003"})]
    m = metrics(
        ex("TC-001", "failed"),  # a failed execution still covers
        blocked("TC-002"),  # a blocked execution does not
        suite=suite,
        impacted_requirement_ids=frozenset({"REQ-001", "REQ-002", "REQ-004"}),
    )
    assert (m["impacted_requirements"], m["covered_requirements"]) == (3, 1)
    assert m["requirement_coverage"] == Ratio(1, 3)


def test_requirement_coverage_is_one_when_nothing_is_impacted():
    assert metrics(ex("TC-001"))["requirement_coverage"] == VACUOUS == Ratio(1, 1)


def test_requirement_coverage_is_not_evaluable_without_documented_requirements():
    m = metrics(ex("TC-001"), has_requirements=False)
    assert is_not_evaluable(m["requirement_coverage"])


def test_high_priority_execution_rate():
    suite = [case("TC-001", priority="high"), case("TC-002", priority="high"), case("TC-003", priority="low")]
    m = metrics(ex("TC-001", "failed"), blocked("TC-002"), ex("TC-003"), suite=suite)
    assert m["high_priority_planned"] == 2
    assert m["high_priority_executed_rate"] == Ratio(1, 2)


def test_high_priority_execution_rate_is_one_when_no_high_priority_case_is_planned():
    m = metrics(ex("TC-001"))
    assert m["high_priority_planned"] == 0
    assert m["high_priority_executed_rate"] == VACUOUS


# Comparison with the baseline


def compare(candidate, base):
    suite = tuple(case(e.test_case_id) for e in candidate)
    return compute_metrics(EvaluationInputs(run=run(*candidate), suite=suite, baseline=run(*base, run_id="RUN-0001")))


def test_comparison_of_verdicts():
    m = compare(
        candidate=[
            ex("TC-001", "failed"),  # new failure
            ex("TC-002", "error"),  # new failure: error is not passed
            ex("TC-003"),  # fixed
            ex("TC-004", "failed"),  # persistent
            ex("TC-005"),  # stable pass
            ex("TC-006"),  # executed only in the candidate
            blocked("TC-007"),
        ],
        base=[
            ex("TC-001"),
            ex("TC-002"),
            ex("TC-003", "error"),
            ex("TC-004", "failed", "passed"),  # a flaky failure is compared by its result
            ex("TC-005"),
            blocked("TC-006"),
            ex("TC-007"),  # executed only in the baseline
            ex("TC-008"),  # not in the candidate run at all
        ],
    )
    assert (m["new_failures"], m["fixed"], m["persistent_failures"], m["stable_passes"]) == (2, 1, 1, 1)
    assert m["not_comparable"] == 3
    assert m["unexcused_new_failures"] == 2


def test_unexcused_new_failures_leave_out_only_excused_ones():
    m = compare(
        candidate=[
            ex("TC-001", "failed", triage="expected_change"),
            ex("TC-002", "failed", triage="test_defect"),
            ex("TC-003", "failed", "passed", triage="flaky"),
            ex("TC-004", "failed", triage="environment"),
            ex("TC-005", "failed"),  # untriaged
        ],
        base=[ex(f"TC-00{n}") for n in range(1, 6)],
    )
    assert m["new_failures"] == 5
    assert m["unexcused_new_failures"] == 3


def test_comparison_is_not_evaluable_without_a_baseline_run():
    m = metrics(ex("TC-001"))
    for name in ("new_failures", "fixed", "persistent_failures", "stable_passes", "not_comparable"):
        assert is_not_evaluable(m[name]), name
    assert is_not_evaluable(m["unexcused_new_failures"])


def test_unexcused_new_failures_are_not_evaluable_when_nothing_was_executed_in_both_runs():
    m = compare(candidate=[ex("TC-001"), blocked("TC-002")], base=[blocked("TC-001"), ex("TC-002")])
    assert is_not_evaluable(m["unexcused_new_failures"])
    assert (m["new_failures"], m["stable_passes"], m["not_comparable"]) == (0, 0, 2)


# Selection quality


def selection(suite_ids, full_base, full_candidate):
    suite = tuple(case(t) for t in suite_ids)
    return compute_metrics(
        EvaluationInputs(
            run=run(),
            suite=suite,
            full_base=run(*full_base, run_id="RUN-0001") if full_base is not None else None,
            full_candidate=run(*full_candidate, run_id="RUN-0002") if full_candidate is not None else None,
        )
    )


def test_revealing_inclusiveness_and_precision():
    m = selection(
        suite_ids=["TC-001", "TC-003", "TC-004"],
        full_base=[
            ex("TC-001"),
            ex("TC-002", "failed"),
            ex("TC-003"),
            ex("TC-004"),
            ex("TC-005"),
            ex("TC-006", "failed", "passed"),
            ex("TC-007"),
        ],
        full_candidate=[
            ex("TC-001", "failed"),  # revealing, selected
            ex("TC-002"),  # revealing, not selected
            ex("TC-003"),  # non-revealing, selected
            ex("TC-004"),  # non-revealing, selected
            ex("TC-005"),  # non-revealing, left out
            ex("TC-006"),  # flaky in F0: neither
            ex("TC-007", "failed", "passed"),  # flaky in F: neither
            ex("TC-008", "failed"),  # only in F: neither
        ],
    )
    assert m["revealing"] == 2
    assert m["selection_inclusiveness"] == Ratio(1, 2)
    assert m["selection_precision"] == Ratio(1, 3)


def test_selection_quality_vacuous_values():
    m = selection(suite_ids=["TC-001"], full_base=[ex("TC-001", "failed", "passed")], full_candidate=[ex("TC-001")])
    assert m["revealing"] == 0
    assert m["selection_inclusiveness"] == VACUOUS  # no revealing test case
    assert m["selection_precision"] == VACUOUS  # no non-revealing test case


def test_selection_quality_is_not_evaluable_without_both_full_runs():
    for full_base, full_candidate in [(None, [ex("TC-001")]), ([ex("TC-001")], None), (None, None)]:
        m = selection(["TC-001"], full_base, full_candidate)
        for name in ("revealing", "selection_inclusiveness", "selection_precision"):
            assert is_not_evaluable(m[name]), name


# Defects


def test_defect_counts():
    m = metrics(
        ex("TC-001", "failed", triage="regression", defects={"DEF-001", "DEF-002"}),
        ex("TC-002", "failed", triage="regression"),  # a regression without a defect
        ex("TC-003", "failed", triage="flaky"),
        ex("TC-004", "error"),  # untriaged
        ex("TC-005", "failed", triage="pre_existing", defects={"DEF-001"}),
        ex("TC-006"),
        defects=(
            Defect("DEF-001", "high", "open"),
            Defect("DEF-002", "critical", "open"),
            Defect("DEF-003", "medium", "open"),
            Defect("DEF-004", "low", "open"),
            Defect("DEF-005", "high", "closed"),
            Defect("DEF-006", "low", "open"),  # linked to another run: open, not found here
        ),
    )
    assert m["open_defects"] == {"critical": 1, "high": 1, "medium": 1, "low": 2}
    assert m["defects_found"] == 2
    assert m["defects_closed"] == 1
    assert (m["triaged_failures"], m["regressions"], m["regressions_with_defect"]) == (4, 2, 1)


# Time


def test_run_duration_and_test_time():
    m = metrics(ex("TC-001", duration=0.25), ex("TC-002", "failed", "passed", duration=0.5), blocked("TC-003"))
    assert m["run_duration"] == 3.4
    assert m["test_time"] == 0.75


def test_run_duration_is_not_evaluable_without_an_end_time():
    m = compute_metrics(EvaluationInputs(run=Run("RUN-0001", (), "2026-11-16T10:00:00.000+00:00", None), suite=()))
    assert is_not_evaluable(m["run_duration"])


# Storage form


def test_json_form_has_null_for_not_evaluable_and_numerator_and_denominator_for_ratios():
    assert to_json({"a": NotEvaluable("x"), "b": Ratio(22, 26), "c": [3, {"d": None}]}) == {
        "a": None,
        "b": {"numerator": 22, "denominator": 26},  # kept as counted, not reduced
        "c": [3, {"d": None}],
    }
    assert Ratio(22, 26).value == Fraction(11, 13)
