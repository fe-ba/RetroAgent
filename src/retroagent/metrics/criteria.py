"""Exit criteria EC-01 to EC-09 of ``docs/reference/metrics.md``, evaluated on computed metrics."""

from dataclasses import dataclass, field
from fractions import Fraction

from retroagent.metrics.compute import NotEvaluable, Ratio


@dataclass(frozen=True)
class OpenDefectLimits:
    critical: int = 0
    high: int = 0
    medium: int | None = None  # None: no limit


@dataclass(frozen=True)
class Thresholds:
    """``exit_criteria.*`` of the effective configuration; the defaults are those of configuration.md."""

    min_pass_rate: float = 0.95
    min_high_priority_executed: float = 1.0
    min_requirement_coverage: float = 1.0
    max_open_defects: OpenDefectLimits = field(default_factory=OpenDefectLimits)
    max_flaky_rate: float = 0.05
    max_new_failures: int = 0


@dataclass(frozen=True)
class CriterionResult:
    id: str
    name: str
    state: str  # met | not_met | not_evaluable
    value: object  # Ratio, int, dict (EC-08) or None when not evaluable
    threshold: object  # as configured; None for EC-08 and for a medium limit that is not set
    blocking: bool
    reason: str | None = None  # why it could not be evaluated


def _exact(threshold: float) -> Fraction:
    """A configured threshold as the exact decimal it was written as: 0.90 is 9/10, not the nearest float."""
    return Fraction(str(threshold))


def _compare(id, name, blocking, value, threshold, at_least: bool) -> CriterionResult:
    if isinstance(value, NotEvaluable):
        return CriterionResult(id, name, "not_evaluable", None, threshold, blocking, value.reason)
    if threshold is None:
        holds = True
    else:
        actual = value.value if isinstance(value, Ratio) else value
        limit = _exact(threshold) if isinstance(value, Ratio) else threshold
        holds = actual >= limit if at_least else actual <= limit
    return CriterionResult(id, name, "met" if holds else "not_met", value, threshold, blocking)


def evaluate_criteria(metrics: dict, thresholds: Thresholds) -> list[CriterionResult]:
    open_defects = metrics["open_defects"]
    limits = thresholds.max_open_defects
    failures = metrics["failed"] + metrics["error"]
    triage = {
        "failures": failures,
        "triaged_failures": metrics["triaged_failures"],
        "regressions": metrics["regressions"],
        "regressions_with_defect": metrics["regressions_with_defect"],
    }
    triaged = triage["triaged_failures"] == failures and triage["regressions_with_defect"] == triage["regressions"]
    return [
        _compare("EC-01", "Product pass rate", True, metrics["product_pass_rate"], thresholds.min_pass_rate, True),
        _compare(
            "EC-02",
            "High-priority execution",
            True,
            metrics["high_priority_executed_rate"],
            thresholds.min_high_priority_executed,
            True,
        ),
        _compare(
            "EC-03",
            "Requirement coverage",
            False,
            metrics["requirement_coverage"],
            thresholds.min_requirement_coverage,
            True,
        ),
        _compare("EC-04", "Critical defects", True, open_defects["critical"], limits.critical, False),
        _compare("EC-05", "High defects", True, open_defects["high"], limits.high, False),
        _compare("EC-06", "Medium defects", False, open_defects["medium"], limits.medium, False),
        _compare("EC-07", "Flaky tests", False, metrics["flaky_rate"], thresholds.max_flaky_rate, False),
        CriterionResult("EC-08", "Failures triaged", "met" if triaged else "not_met", triage, None, True),
        _compare("EC-09", "New failures", True, metrics["unexcused_new_failures"], thresholds.max_new_failures, False),
    ]
