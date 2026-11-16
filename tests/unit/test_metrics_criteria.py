"""Exit criteria EC-01 to EC-09 (docs/reference/metrics.md), evaluated on plain metric values."""

import pytest

from retroagent.metrics.compute import VACUOUS, NotEvaluable, Ratio
from retroagent.metrics.criteria import OpenDefectLimits, Thresholds, evaluate_criteria


def good_metrics(**changes):
    """Metrics that meet every criterion with the default thresholds."""
    values = {
        "product_pass_rate": Ratio(20, 20),
        "high_priority_executed_rate": Ratio(5, 5),
        "requirement_coverage": Ratio(3, 3),
        "open_defects": {"critical": 0, "high": 0, "medium": 0, "low": 0},
        "flaky_rate": Ratio(0, 20),
        "failed": 0,
        "error": 0,
        "triaged_failures": 0,
        "regressions": 0,
        "regressions_with_defect": 0,
        "unexcused_new_failures": 0,
    }
    values.update(changes)
    return values


def state(criterion_id, metrics, thresholds=None):
    criteria = {c.id: c for c in evaluate_criteria(metrics, thresholds or Thresholds())}
    return criteria[criterion_id]


def test_default_thresholds_are_those_of_the_configuration_reference():
    t = Thresholds()
    assert (t.min_pass_rate, t.min_high_priority_executed, t.min_requirement_coverage) == (0.95, 1.0, 1.0)
    assert t.max_open_defects == OpenDefectLimits(critical=0, high=0, medium=None)
    assert (t.max_flaky_rate, t.max_new_failures) == (0.05, 0)


def test_identifiers_names_and_blocking():
    criteria = evaluate_criteria(good_metrics(), Thresholds())
    assert [(c.id, c.name, c.blocking) for c in criteria] == [
        ("EC-01", "Product pass rate", True),
        ("EC-02", "High-priority execution", True),
        ("EC-03", "Requirement coverage", False),
        ("EC-04", "Critical defects", True),
        ("EC-05", "High defects", True),
        ("EC-06", "Medium defects", False),
        ("EC-07", "Flaky tests", False),
        ("EC-08", "Failures triaged", True),
        ("EC-09", "New failures", True),
    ]
    assert all(c.state == "met" for c in criteria)


def test_ec_01_product_pass_rate_on_the_exact_value():
    thresholds = Thresholds(min_pass_rate=0.9)
    assert state("EC-01", good_metrics(product_pass_rate=Ratio(9, 10)), thresholds).state == "met"  # 9/10, not float
    assert state("EC-01", good_metrics(product_pass_rate=Ratio(23, 26)), thresholds).state == "not_met"
    assert state("EC-01", good_metrics(product_pass_rate=Ratio(899, 999)), thresholds).state == "not_met"  # 89.99%
    result = state("EC-01", good_metrics(product_pass_rate=NotEvaluable("nothing was executed")))
    assert (result.state, result.value, result.reason) == ("not_evaluable", None, "nothing was executed")
    assert result.threshold == 0.95


def test_ec_02_high_priority_execution():
    assert state("EC-02", good_metrics(high_priority_executed_rate=Ratio(4, 5))).state == "not_met"
    assert state("EC-02", good_metrics(high_priority_executed_rate=VACUOUS)).state == "met"
    lower = Thresholds(min_high_priority_executed=0.8)
    assert state("EC-02", good_metrics(high_priority_executed_rate=Ratio(4, 5)), lower).state == "met"


def test_ec_03_requirement_coverage():
    assert state("EC-03", good_metrics(requirement_coverage=Ratio(6, 7))).state == "not_met"
    assert state("EC-03", good_metrics(requirement_coverage=VACUOUS)).state == "met"
    result = state("EC-03", good_metrics(requirement_coverage=NotEvaluable("no requirements")))
    assert (result.state, result.reason) == ("not_evaluable", "no requirements")


@pytest.mark.parametrize("criterion_id, severity", [("EC-04", "critical"), ("EC-05", "high")])
def test_ec_04_and_ec_05_open_defects(criterion_id, severity):
    def open_defects(count):
        return good_metrics(open_defects={"critical": 0, "high": 0, "medium": 0, "low": 0, severity: count})

    assert state(criterion_id, open_defects(0)).state == "met"
    result = state(criterion_id, open_defects(1))
    assert (result.state, result.value, result.threshold) == ("not_met", 1, 0)
    limits = OpenDefectLimits(**{severity: 1})
    assert state(criterion_id, open_defects(1), Thresholds(max_open_defects=limits)).state == "met"


def test_ec_06_medium_defects_are_always_met_without_a_limit():
    many = good_metrics(open_defects={"critical": 0, "high": 0, "medium": 9, "low": 0})
    result = state("EC-06", many)
    assert (result.state, result.value, result.threshold) == ("met", 9, None)
    limited = Thresholds(max_open_defects=OpenDefectLimits(medium=2))
    assert state("EC-06", many, limited).state == "not_met"
    two = good_metrics(open_defects={"critical": 0, "high": 0, "medium": 2, "low": 0})
    assert state("EC-06", two, limited).state == "met"


def test_ec_07_flaky_tests():
    assert state("EC-07", good_metrics(flaky_rate=Ratio(1, 20))).state == "met"  # exactly 5%
    assert state("EC-07", good_metrics(flaky_rate=Ratio(2, 39))).state == "not_met"  # 5.1%
    assert state("EC-07", good_metrics(flaky_rate=NotEvaluable("nothing was executed"))).state == "not_evaluable"


def test_ec_08_failures_triaged():
    met = state("EC-08", good_metrics(failed=3, error=1, triaged_failures=4, regressions=1, regressions_with_defect=1))
    assert met.state == "met"
    assert met.value == {"failures": 4, "triaged_failures": 4, "regressions": 1, "regressions_with_defect": 1}
    assert met.threshold is None
    untriaged = good_metrics(failed=2, triaged_failures=1)
    assert state("EC-08", untriaged).state == "not_met"
    without_defect = good_metrics(failed=1, triaged_failures=1, regressions=1, regressions_with_defect=0)
    assert state("EC-08", without_defect).state == "not_met"
    assert state("EC-08", good_metrics()).state == "met"  # no failure


def test_ec_09_new_failures():
    assert state("EC-09", good_metrics(unexcused_new_failures=1)).state == "not_met"
    assert state("EC-09", good_metrics(unexcused_new_failures=1), Thresholds(max_new_failures=1)).state == "met"
    result = state("EC-09", good_metrics(unexcused_new_failures=NotEvaluable("there is no baseline run")))
    assert (result.state, result.reason) == ("not_evaluable", "there is no baseline run")
