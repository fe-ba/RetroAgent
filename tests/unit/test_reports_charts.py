"""Charts: deterministic SVG, with the labels of ``expected/charts/``."""

import html
import re
import subprocess
import sys

from retroagent.metrics import NotEvaluable
from retroagent.reports import charts

COUNTS = {"passed": 23, "failed": 4, "error": 0, "blocked": 0, "skipped": 0}


def texts(svg: bytes) -> list[str]:
    return [html.unescape(t) for t in re.findall(r"<text[^>]*>([^<]*)</text>", svg.decode())]


def test_outcomes_chart_has_a_title_a_label_and_a_value_per_outcome():
    svg = charts.outcomes_chart(COUNTS)
    assert sorted(texts(svg)) == sorted(
        [
            "Execution outcomes (27 executed)",
            "passed",
            "failed",
            "error",
            "blocked",
            "skipped",
            "23",
            "4",
            "0",
            "0",
            "0",
        ]
    )
    assert len(re.findall(r'id="bar-\d+"', svg.decode())) == 2  # a zero has a label and no bar


def test_comparison_chart_names_the_number_of_test_cases_compared():
    svg = charts.comparison_chart({"new_failures": 2, "fixed": 0, "persistent_failures": 2, "stable_passes": 19})
    assert "Comparison with the baseline (23 test cases executed in both runs)" in texts(svg)
    assert "persistent failures" in texts(svg)


def test_the_same_data_gives_the_same_bytes_and_no_date():
    first = charts.outcomes_chart(COUNTS)
    assert charts.outcomes_chart(COUNTS) == first
    assert b"<dc:date" not in first and b"<metadata" in first
    code = (
        "import sys; from retroagent.reports import charts;"
        "sys.stdout.buffer.write(charts.outcomes_chart("
        "{'passed': 23, 'failed': 4, 'error': 0, 'blocked': 0, 'skipped': 0}))"
    )
    other = subprocess.run([sys.executable, "-c", code], capture_output=True, check=True).stdout
    assert other == first  # another process, the same bytes


def test_text_stays_text_so_the_chart_can_be_compared_and_read():
    assert b"<text" in charts.outcomes_chart(COUNTS)


def test_criteria_chart_draws_value_and_threshold_and_marks_a_criterion_that_is_not_evaluable():
    rates = [
        {"label": "EC-01 Product pass rate", "value": 0.885, "threshold": 0.9, "text": "88.5%  (min 90.0%)"},
        {"label": "EC-03 Requirement coverage", "value": None, "threshold": 1.0, "text": "not evaluable  (min 100.0%)"},
    ]
    counts = [{"label": "EC-05 High defects", "value": 1, "threshold": 0, "text": "1  (max 0)"}]
    svg = charts.criteria_chart(rates, counts)
    assert {"Rates", "Counts", "88.5%  (min 90.0%)", "not evaluable  (min 100.0%)"} <= set(texts(svg))
    assert len(re.findall(r'id="bar-\d+"', svg.decode())) == 2
    assert len(re.findall(r'id="mark-\d+"', svg.decode())) == 3


def test_a_chart_with_nothing_evaluable_shows_a_message_instead_of_bars():
    svg = charts.criteria_chart([{"label": "EC-01", "value": None, "threshold": 0.9, "text": "x"}], [])
    assert "Not evaluable: no criterion with a threshold has a value" in texts(svg)
    assert b'id="bar-' not in svg


def test_a_comparison_without_a_baseline_shows_the_reason():
    reason = NotEvaluable("there is no baseline run")
    metrics = dict.fromkeys(charts.COMPARISON, reason)

    class Evaluation:
        pass

    evaluation = Evaluation()
    evaluation.metrics, evaluation.criteria = metrics, []
    assert "Not evaluable: there is no baseline run" in texts(charts.draw("comparison.svg", evaluation))
