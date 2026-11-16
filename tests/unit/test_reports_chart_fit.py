"""Every label of every chart ends inside the canvas, also when a bar is at its maximum."""

from fixtures.chart_text import overflowing

from retroagent.reports import charts


def row(label, value, threshold, bound, shown):
    text = f"{shown}  ({bound} {'100.0%' if isinstance(threshold, float) else threshold})"
    return {"label": label, "value": value, "threshold": threshold, "text": text}


def test_a_criteria_chart_with_every_rate_at_100_percent_fits():
    rates = [
        row("EC-01 Product pass rate", 1.0, 1.0, "min", "100.0%"),
        row("EC-02 High-priority execution", 1.0, 1.0, "min", "100.0%"),
        row("EC-03 Requirement coverage", 1.0, 1.0, "min", "100.0%"),
        row("EC-07 Flaky tests", 1.0, 1.0, "max", "100.0%"),
    ]
    counts = [row("EC-05 High defects", 12345, 12345, "max", "12345")]
    assert overflowing(charts.criteria_chart(rates, counts)) == []


def test_a_bar_chart_with_a_very_large_count_fits():
    counts = {"passed": 1234567, "failed": 4, "error": 0, "blocked": 0, "skipped": 0}
    assert overflowing(charts.outcomes_chart(counts)) == []
    comparison = {"new_failures": 2, "fixed": 0, "persistent_failures": 2, "stable_passes": 9999999}
    assert overflowing(charts.comparison_chart(comparison)) == []


def test_the_measure_detects_labels_that_are_not_fitted(monkeypatch):
    """With the scale of before (no room for the labels) the same chart overflows: the test can fail."""
    monkeypatch.setattr(charts, "_fit", lambda fig, width_px, base, labels: base)
    rates = [row("EC-02 High-priority execution", 1.0, 1.0, "min", "100.0%")]
    assert overflowing(charts.criteria_chart(rates, []))
