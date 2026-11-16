"""Metrics of ``docs/reference/metrics.md``, as pure functions of plain data.

Nothing here reads the database or a model output (ADR-0006). A ratio keeps its numerator and denominator and is
compared as an exact ``Fraction``. A metric that cannot be evaluated is a ``NotEvaluable`` value with its reason,
never zero.
"""

import dataclasses
import math
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

SEVERITIES = ("critical", "high", "medium", "low")
EXCUSING = ("expected_change", "test_defect")


@dataclass(frozen=True)
class NotEvaluable:
    reason: str


@dataclass(frozen=True)
class Ratio:
    numerator: int
    denominator: int

    @property
    def value(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


VACUOUS = Ratio(1, 1)  # the value 1.0 that some metrics state when their denominator is zero


@dataclass(frozen=True)
class TestCase:
    __test__ = False  # not a pytest class

    id: str
    status: str  # designed | implemented
    priority: str  # high | medium | low
    requirement_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Execution:
    """A test execution. ``attempts`` are the attempt results in order; the first one is ``result``."""

    test_case_id: str
    status: str  # executed | blocked | skipped
    result: str | None = None
    attempts: tuple[str, ...] = ()
    triage: str | None = None  # classification of the current triage
    defect_ids: frozenset[str] = frozenset()
    duration: float | None = None  # test time of the first attempt

    @property
    def executed(self) -> bool:
        return self.status == "executed"

    @property
    def failure(self) -> bool:
        return self.result in ("failed", "error")

    @property
    def flaky(self) -> bool:
        """At least one rerun passed (ADR-0022). ``failed`` and ``error`` reruns do not make it flaky."""
        return any(result == "passed" for result in self.attempts[1:])

    @property
    def excused(self) -> bool:
        return self.failure and self.triage in EXCUSING


@dataclass(frozen=True)
class Run:
    id: str
    executions: tuple[Execution, ...] = ()
    started_at: str | None = None
    ended_at: str | None = None

    def executed(self) -> dict[str, Execution]:
        """Executed executions by test case."""
        return {e.test_case_id: e for e in self.executions if e.executed}


@dataclass(frozen=True)
class Defect:
    id: str
    severity: str
    status: str  # open | closed


@dataclass(frozen=True)
class EvaluationInputs:
    """The inputs of one evaluation (metrics.md, Evaluation inputs)."""

    run: Run  # R
    suite: tuple[TestCase, ...]  # S
    baseline: Run | None = None  # R0
    full_base: Run | None = None  # F0
    full_candidate: Run | None = None  # F
    impacted_requirement_ids: frozenset[str] = frozenset()
    has_requirements: bool = True
    defects: tuple[Defect, ...] = ()
    analysis_id: int | None = None


def ratio(numerator: int, denominator: int, reason: str) -> Ratio | NotEvaluable:
    """``numerator / denominator``, not evaluable when the denominator is zero."""
    return Ratio(numerator, denominator) if denominator else NotEvaluable(reason)


def vacuous_ratio(numerator: int, denominator: int) -> Ratio:
    """``numerator / denominator``, ``1.0`` when the denominator is zero."""
    return Ratio(numerator, denominator) if denominator else VACUOUS


# Scope


def scope_metrics(suite: tuple[TestCase, ...], run: Run) -> dict:
    planned = len(suite)
    implemented = sum(1 for t in suite if t.status == "implemented")
    executed = sum(1 for e in run.executions if e.status == "executed")
    return {
        "planned": planned,
        "implemented": implemented,
        "implementation_rate": ratio(implemented, planned, "no test case is planned"),
        "designed_only": planned - implemented,
        "executed": executed,
        "blocked": sum(1 for e in run.executions if e.status == "blocked"),
        "skipped": sum(1 for e in run.executions if e.status == "skipped"),
        "execution_rate": ratio(executed, planned, "no test case is planned"),
    }


# Results


def excused_executions(run: Run) -> list[Execution]:
    return sorted((e for e in run.executions if e.excused), key=lambda e: e.test_case_id)


def pre_existing_executions(run: Run) -> list[Execution]:
    return sorted((e for e in run.executions if e.failure and e.triage == "pre_existing"), key=lambda e: e.test_case_id)


def designed_only_test_cases(suite: tuple[TestCase, ...]) -> list[TestCase]:
    return sorted((t for t in suite if t.status != "implemented"), key=lambda t: t.id)


def result_metrics(run: Run) -> dict:
    executed = [e for e in run.executions if e.executed]
    passed = sum(1 for e in executed if e.result == "passed")
    excused = len(excused_executions(run))
    flaky = sum(1 for e in executed if e.flaky)
    return {
        "passed": passed,
        "failed": sum(1 for e in executed if e.result == "failed"),
        "error": sum(1 for e in executed if e.result == "error"),
        "pass_rate": ratio(passed, len(executed), "nothing was executed"),
        "excused": excused,
        "product_pass_rate": ratio(passed, len(executed) - excused, "no executed test case is left after excused"),
        "pre_existing": len(pre_existing_executions(run)),
        "flaky": flaky,
        "flaky_rate": ratio(flaky, len(executed), "nothing was executed"),
    }


# Coverage


def coverage_metrics(inputs: EvaluationInputs) -> dict:
    executed = inputs.run.executed()
    executed_cases = [t for t in inputs.suite if t.id in executed]
    impacted = inputs.impacted_requirement_ids
    covered = {r for r in impacted if any(r in t.requirement_ids for t in executed_cases)}
    if not inputs.has_requirements:
        coverage = NotEvaluable("the project has no documented requirements")
    else:
        coverage = vacuous_ratio(len(covered), len(impacted))
    high = [t for t in inputs.suite if t.priority == "high"]
    return {
        "impacted_requirements": len(impacted),
        "covered_requirements": len(covered),
        "requirement_coverage": coverage,
        "high_priority_planned": len(high),
        "high_priority_executed_rate": vacuous_ratio(sum(1 for t in high if t.id in executed), len(high)),
    }


# Comparison with the baseline

COMPARISON = ("new_failures", "fixed", "persistent_failures", "stable_passes", "not_comparable")


def comparison_metrics(run: Run, baseline: Run | None) -> dict:
    if baseline is None:
        missing = NotEvaluable("there is no baseline run")
        return {name: missing for name in (*COMPARISON, "unexcused_new_failures")}
    candidate, base = run.executed(), baseline.executed()
    common = candidate.keys() & base.keys()
    counts = dict.fromkeys(COMPARISON, 0)
    unexcused = 0
    for test_case_id in common:
        was_passed = base[test_case_id].result == "passed"
        is_passed = candidate[test_case_id].result == "passed"
        if was_passed and not is_passed:
            counts["new_failures"] += 1
            unexcused += not candidate[test_case_id].excused
        elif not was_passed and is_passed:
            counts["fixed"] += 1
        elif not was_passed:
            counts["persistent_failures"] += 1
        else:
            counts["stable_passes"] += 1
    counts["not_comparable"] = len(candidate.keys() ^ base.keys())
    counts["unexcused_new_failures"] = (
        unexcused if common else NotEvaluable("no test case was executed in both the run and the baseline run")
    )
    return counts


# Selection quality


def selection_metrics(suite: tuple[TestCase, ...], full_base: Run | None, full_candidate: Run | None) -> dict:
    if full_base is None or full_candidate is None:
        missing = NotEvaluable("full runs against both versions are needed")
        return {"revealing": missing, "selection_inclusiveness": missing, "selection_precision": missing}
    base, candidate = full_base.executed(), full_candidate.executed()
    revealing, non_revealing = set(), set()
    for test_case_id in base.keys() & candidate.keys():
        before, after = base[test_case_id], candidate[test_case_id]
        if before.flaky or after.flaky:
            continue
        if (before.result == "passed") != (after.result == "passed"):
            revealing.add(test_case_id)
        else:
            non_revealing.add(test_case_id)
    selected = {t.id for t in suite}
    return {
        "revealing": len(revealing),
        "selection_inclusiveness": vacuous_ratio(len(revealing & selected), len(revealing)),
        "selection_precision": vacuous_ratio(len(non_revealing - selected), len(non_revealing)),
    }


# Defects


def defect_metrics(run: Run, defects: tuple[Defect, ...]) -> dict:
    failures = [e for e in run.executions if e.failure]
    regressions = [e for e in failures if e.triage == "regression"]
    return {
        "open_defects": {
            severity: sum(1 for d in defects if d.status == "open" and d.severity == severity)
            for severity in SEVERITIES
        },
        "triaged_failures": sum(1 for e in failures if e.triage is not None),
        "regressions": len(regressions),
        "regressions_with_defect": sum(1 for e in regressions if e.defect_ids),
        "defects_found": len({d for e in run.executions for d in e.defect_ids}),
        "defects_closed": sum(1 for d in defects if d.status == "closed"),
    }


# Time


def time_metrics(run: Run) -> dict:
    if run.started_at is None or run.ended_at is None:
        duration = NotEvaluable("the run has no end time")
    else:
        delta = datetime.fromisoformat(run.ended_at) - datetime.fromisoformat(run.started_at)
        duration = delta.total_seconds()
    times = [e.duration for e in run.executions if e.executed and e.duration is not None]
    return {"run_duration": duration, "test_time": math.fsum(times)}


def compute_metrics(inputs: EvaluationInputs) -> dict:
    """Every metric of metrics.md, keyed by its name."""
    return {
        **scope_metrics(inputs.suite, inputs.run),
        **result_metrics(inputs.run),
        **coverage_metrics(inputs),
        **comparison_metrics(inputs.run, inputs.baseline),
        **selection_metrics(inputs.suite, inputs.full_base, inputs.full_candidate),
        **defect_metrics(inputs.run, inputs.defects),
        **time_metrics(inputs.run),
    }


def to_json(value):
    """JSON form for storage (data-model.md, ``evaluation``): not evaluable is ``null``, a ratio is its numerator
    and denominator."""
    if isinstance(value, NotEvaluable):
        return None
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_json(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    return value
