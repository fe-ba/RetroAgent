"""The completion report of cycle 2 of the reference scenario (v1.1 to v1.2)."""

import re

from fixtures.reference_scenario import load_cycle_2

from retroagent.servers.reports import server


def test_cycle_2_renders_without_an_unresolved_marker_and_states_release_with_conditions(reference):
    session, scenario = reference
    cycle = load_cycle_2(session.conn, scenario)
    prepared = server.prepare_report(session.with_id(cycle.session_id), "completion", formats=["md"])
    text = prepared["computed"]
    assert not re.search(r"\{\{|\}\}", text)
    assert "**Release decision: `release_with_conditions`**" in text
    assert f"| Evaluated run | {cycle.evaluated_run} |" in text and f"| Baseline run | {cycle.baseline_run} |" in text
    assert f"- Test cases that already failed against the baseline {cycle.baseline_run}: TC-022." in text
    assert "| Product pass rate | 92.0% |" in text and "| Fixed | 1 |" in text
    assert "| Open, high | 0 |" in text and "No open defects." in text
    assert "| Revealing test cases | not evaluable |" in text  # there is no full run in this cycle
    assert "Metric `revealing` is not evaluable" in text
    folder = session.project_dir / prepared["path"]
    assert sorted(p.name for p in (folder / "charts").iterdir()) == ["comparison.svg", "criteria.svg", "outcomes.svg"]
