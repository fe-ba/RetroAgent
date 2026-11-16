"""SC-12: the test case specification, on the records of the reference scenario."""

import re

from fixtures.reference_scenario import GENERATED

from retroagent.servers.reports import server


def specification(session):
    prepared = server.prepare_report(session, "test-cases")
    server.render_report(session, prepared["report_id"], {})
    folder = session.project_dir / prepared["path"]
    return prepared, folder, (folder / "report.md").read_text(encoding="utf-8")


def item(text: str, test_case_id: str) -> str:
    return re.search(rf"### {test_case_id}: .*?(?=\n### TC-|\Z)", text, re.DOTALL).group(0)


def test_tc_027_shows_its_whole_design_and_its_implementation(reference):
    session, scenario = reference
    _, _, text = specification(session)
    tc_027 = item(text, scenario.tc_027)
    assert "### TC-027: A quantity above the stock is rejected" in tc_027
    assert "| Objective | Adding more units than in stock is refused and the cart does not change. |" in tc_027
    assert "| Priority | `high` |" in tc_027 and "| Status | `implemented` |" in tc_027
    assert "| Requirements | REQ-002 |" in tc_027
    assert f"| Implementation | {GENERATED} |" in tc_027
    assert "| Origin | designed by none |" in tc_027
    assert "| Last execution | RUN-0004 against v1.1: passed |" in tc_027
    assert "#### Preconditions\n\n- A product with stock 5" in tc_027
    assert "#### Input data\n\n| Name | Value |\n|---|---|\n| quantity | 6 |" in tc_027
    assert "#### Steps\n\n1. Add 6 units of the product to a new cart" in tc_027
    assert "#### Expected result\n\nThe request is rejected and the cart stays empty." in tc_027


def test_tc_028_is_designed_and_has_no_implementation(reference):
    session, scenario = reference
    _, _, text = specification(session)
    tc_028 = item(text, scenario.tc_028)
    assert "| Status | `designed` |" in tc_028 and "| Implementation | none |" in tc_028
    assert "| Last execution | none |" in tc_028
    assert "#### Preconditions\n\nNo preconditions." in tc_028 and "#### Input data\n\nNo input data." in tc_028


def test_summary_and_traceability_describe_the_current_suite(reference):
    session, _ = reference
    _, _, text = specification(session)
    assert "| Test cases in the suite | 28 |" in text and "| Implemented | 27 |" in text
    assert "| Designed only | 1 |" in text
    assert "| TC-027 | A quantity above the stock is rejected | `high` | `implemented` | REQ-002 |" in text
    assert "| TC-028 | An unknown product cannot be added | `medium` | `designed` | REQ-002 |" in text
    assert "| REQ-002 | TC-027, TC-028 |" in text
    assert text.count("\n### TC-") == 28
    assert text.index("### TC-027") < text.index("### TC-028")  # high priority first, then the identifier


def test_it_has_no_agent_section_and_no_chart(reference):
    session, _ = reference
    prepared, folder, text = specification(session)
    assert prepared["sections"] == [] and "Agent analysis" not in text
    assert not (folder / "charts").exists()
    assert "{{" not in text and "<!--" not in text
