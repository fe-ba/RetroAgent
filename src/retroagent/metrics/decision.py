"""The release decision rule of ``docs/reference/metrics.md``, with its reasons and conditions."""

from dataclasses import dataclass

from retroagent.metrics.compute import (
    EvaluationInputs,
    designed_only_test_cases,
    excused_executions,
    pre_existing_executions,
)
from retroagent.metrics.criteria import CriterionResult


@dataclass(frozen=True)
class Condition:
    """One condition of ``release_with_conditions``.

    ``kind``: ``criterion_not_met``, ``criterion_not_evaluable``, ``excused``, ``pre_existing`` or
    ``designed_only``. A criterion condition names its criterion; the others name test cases, each as
    ``{"test_case_id", "classification"}`` (no classification for ``designed_only``).
    """

    kind: str
    criterion: CriterionResult | None = None
    test_cases: tuple[dict, ...] = ()
    baseline_run_id: str | None = None


@dataclass(frozen=True)
class Decision:
    outcome: str  # release | release_with_conditions | do_not_release
    reasons: tuple[CriterionResult, ...] = ()  # the blocking criteria that are not met or not evaluable
    conditions: tuple[Condition, ...] = ()


def _failing(criterion: CriterionResult) -> bool:
    return criterion.state in ("not_met", "not_evaluable")


def decide(criteria: list[CriterionResult], inputs: EvaluationInputs) -> Decision:
    """Applied in order; the first rule that matches decides."""
    reasons = tuple(c for c in criteria if c.blocking and _failing(c))
    if reasons:
        return Decision("do_not_release", reasons=reasons)

    conditions = [
        Condition("criterion_not_met" if c.state == "not_met" else "criterion_not_evaluable", criterion=c)
        for c in criteria
        if not c.blocking and _failing(c)
    ]
    excused = excused_executions(inputs.run)
    if excused:
        cases = tuple({"test_case_id": e.test_case_id, "classification": e.triage} for e in excused)
        conditions.append(Condition("excused", test_cases=cases))
    pre_existing = pre_existing_executions(inputs.run)
    if pre_existing:
        cases = tuple({"test_case_id": e.test_case_id, "classification": e.triage} for e in pre_existing)
        conditions.append(
            Condition(
                "pre_existing",
                test_cases=cases,
                baseline_run_id=inputs.baseline.id if inputs.baseline else None,
            )
        )
    designed_only = designed_only_test_cases(inputs.suite)
    if designed_only:
        conditions.append(Condition("designed_only", test_cases=tuple({"test_case_id": t.id} for t in designed_only)))
    if conditions:
        return Decision("release_with_conditions", conditions=tuple(conditions))
    return Decision("release")
