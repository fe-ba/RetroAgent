"""SC-11: the completion report, on the records of the reference scenario (without the model)."""

import html
import re
import sys
import zlib
from pathlib import Path

import pytest
from fixtures.chart_text import overflowing
from fixtures.mcp_project import reports_server
from fixtures.reference_scenario import S4
from fixtures.report_text import EXPECTED, computed, difference

from retroagent.memory import interpretation
from retroagent.servers.errors import ToolError
from retroagent.servers.reports import server

SECTIONS = {
    "conclusions": "Do not release.\n\nTC-020 is the reason.",
    "summary": "A summary.",
    "deviations": "A deviation.",
    "residual_risks": "A risk.",
    "limitations": "A limit.",
}


def generate(session, formats=None, sections=SECTIONS) -> tuple[Path, dict]:
    prepared = server.prepare_report(session, "completion", formats=formats)
    server.render_report(session, prepared["report_id"], sections)
    return session.project_dir / prepared["path"], prepared


def test_the_computed_sections_equal_the_expected_report(reference):
    session, _ = reference
    folder, _ = generate(session)
    expected = computed((EXPECTED / "test-completion-report.md").read_text(encoding="utf-8"))
    actual = computed((folder / "report.md").read_text(encoding="utf-8"))
    assert actual == expected, "\n" + difference(expected, actual)


def test_the_header_of_the_report_names_this_report_and_the_tool(reference):
    session, _ = reference
    folder, _ = generate(session)
    text = (folder / "report.md").read_text(encoding="utf-8")
    assert "| Report | RPT-0001 |" in text and "| Model | `none` |" in text and "| RetroAgent | 0.1.0 |" in text
    assert re.search(r"\| Generated \| \d{4}-\d\d-\d\dT\d\d:\d\d-05:00 \|", text)  # local time, UTC offset


def test_agent_sections_are_marked_as_written_by_the_model(reference):
    session, _ = reference
    folder, prepared = generate(session, sections={"conclusions": "Do not release.", "summary": "A summary."})
    text = (folder / "report.md").read_text(encoding="utf-8")
    assert [s["name"] for s in prepared["sections"]] == [
        "conclusions",
        "summary",
        "deviations",
        "residual_risks",
        "limitations",
    ]
    assert text.count("> **Agent analysis** · written by `none`, not computed.") == 5
    assert "> Do not release." in text
    assert text.count("> Not provided.") == 3  # the sections that were not written
    expected = (EXPECTED / "test-completion-report.md").read_text(encoding="utf-8")
    assert text.count("**Agent analysis**") == expected.count("**Agent analysis**")


def texts(svg: str) -> list[str]:
    return sorted(html.unescape(t) for t in re.findall(r"<text[^>]*>([^<]*)</text>", svg))


@pytest.mark.parametrize("name", ["outcomes.svg", "comparison.svg", "criteria.svg"])
def test_the_charts_exist_and_have_the_texts_and_bars_of_the_expected_ones(reference, name):
    session, _ = reference
    folder, _ = generate(session)
    actual = (folder / "charts" / name).read_text(encoding="utf-8")
    expected = (EXPECTED / "charts" / name).read_text(encoding="utf-8")
    # Not byte for byte: the expected charts are drawn by hand; the texts and the number of shapes must agree.
    assert texts(actual) == texts(expected)
    bars_and_marks = len(re.findall(r'id="(?:bar|mark)-\d+"', actual))
    expected_shapes = len(re.findall(r"fill='#2a78d6'", expected)) + len(re.findall(r"stroke-width='2'", expected))
    assert bars_and_marks == expected_shapes


def test_the_charts_are_deterministic(reference):
    session, _ = reference
    first, _ = generate(session)
    second, _ = generate(session)
    for name in ("outcomes.svg", "comparison.svg", "criteria.svg"):
        assert (first / "charts" / name).read_bytes() == (second / "charts" / name).read_bytes()
    assert b"<dc:date" not in (first / "charts" / "criteria.svg").read_bytes()


def pdf_pages(path: Path) -> int:
    """The number of page objects; WeasyPrint keeps them in compressed object streams, so those are inflated."""
    data = path.read_bytes()
    assert data.startswith(b"%PDF-")
    for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", data, re.DOTALL):
        try:
            data += zlib.decompress(stream)
        except zlib.error:
            pass  # not compressed (fonts and images are not needed here)
    return len(re.findall(rb"/Type /Page\b(?!s)", data))


def test_the_pdf_exists_and_has_more_than_one_page(reference):
    pytest.importorskip("markdown")
    try:
        import weasyprint  # noqa: F401
    except OSError:
        pytest.skip("the Pango system library is not installed")
    session, _ = reference
    folder, _ = generate(session, formats=["pdf"])
    assert (folder / "report.md").is_file()
    assert pdf_pages(folder / "report.pdf") > 1


def test_the_draft_is_replaced_by_the_report(reference):
    session, _ = reference
    prepared = server.prepare_report(session, "completion")
    folder = session.project_dir / prepared["path"]
    assert (folder / "draft.md").read_text(encoding="utf-8") == prepared["computed"]
    assert prepared["computed"].count("<!-- agent:") == 5 and not (folder / "report.md").exists()
    server.render_report(session, prepared["report_id"], {})
    assert (folder / "report.md").is_file() and not (folder / "draft.md").exists()


def test_a_second_report_has_a_new_identifier_and_the_same_computed_sections(reference):
    session, _ = reference
    first, _ = generate(session)
    second, _ = generate(session)
    assert (first.name, second.name) == ("RPT-0001-completion", "RPT-0002-completion")

    def same_but_for_its_own_identifier(folder):
        text = (folder / "report.md").read_text(encoding="utf-8")
        return computed(text.replace(folder.name.removesuffix("-completion"), "RPT-XXXX"))

    assert same_but_for_its_own_identifier(first) == same_but_for_its_own_identifier(second)


def test_what_is_recorded_between_prepare_and_render_does_not_change_the_report(reference):
    session, scenario = reference
    prepared = server.prepare_report(session, "completion")
    conn = session.conn
    s4 = conn.execute(
        "SELECT id FROM test_execution WHERE run_id = ? AND test_case_id = ?",
        (scenario.evaluated_run, scenario.tc(S4)),
    ).fetchone()["id"]
    interpretation.add_triage(
        conn, execution_id=s4, classification="environment", justification="x", triaged_by="m", replace=True
    )
    interpretation.add_defect(conn, title="A defect found meanwhile", severity="critical", execution_ids=[s4])
    server.render_report(session, prepared["report_id"], SECTIONS)
    text = (session.project_dir / prepared["path"] / "report.md").read_text(encoding="utf-8")
    assert "A defect found meanwhile" not in text and "DEF-002" not in text
    expected = computed((EXPECTED / "test-completion-report.md").read_text(encoding="utf-8"))
    assert computed(text) == expected, "\n" + difference(expected, computed(text))


def test_a_report_that_is_prepared_is_a_draft_with_the_requested_formats(reference):
    session, _ = reference
    prepared = server.prepare_report(session, "completion", formats=["pdf"])
    row = session.conn.execute("SELECT * FROM report WHERE id = ?", (prepared["report_id"],)).fetchone()
    assert (row["status"], row["type"], row["path"]) == ("draft", "completion", ".retro/reports/RPT-0001-completion/")
    assert row["evaluation_id"] is not None and row["model"] == "none"
    assert prepared["formats"] == ["md", "pdf"]  # the PDF is always produced from the Markdown


def test_render_without_the_pdf_library_still_produces_the_markdown(reference, monkeypatch):
    session, _ = reference
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    prepared = server.prepare_report(session, "completion", formats=["pdf"])
    with pytest.raises(ToolError) as error:
        server.render_report(session, prepared["report_id"], SECTIONS)
    assert error.value.code == "unavailable" and "Pango" in error.value.message
    folder = session.project_dir / prepared["path"]
    assert (folder / "report.md").is_file() and not (folder / "report.pdf").exists()
    row = session.conn.execute("SELECT status, formats FROM report").fetchone()
    assert (row["status"], row["formats"]) == ("rendered", '["md"]')


@pytest.mark.parametrize("name", ["outcomes.svg", "comparison.svg", "criteria.svg"])
def test_no_label_of_the_reference_charts_leaves_the_canvas(reference, name):
    session, _ = reference
    folder, _ = generate(session)
    assert overflowing((folder / "charts" / name).read_bytes()) == []


def test_through_the_server_the_computed_sections_equal_the_expected_report_and_the_pdf_exists(reference):
    """SC-11 through the reports MCP server, as the model reaches it: prepare, then render with md and pdf."""
    pytest.importorskip("markdown")
    try:
        import weasyprint  # noqa: F401
    except OSError:
        pytest.skip("the Pango system library is not installed")
    session, _ = reference
    with reports_server(session) as client:
        prepared = client.call("reports", "prepare_report", {"type": "completion", "formats": ["pdf"]})
        rendered = client.call("reports", "render_report", {"report_id": prepared["report_id"], "sections": SECTIONS})
    folder = session.project_dir / prepared["path"]
    assert rendered["files"] == [f"{prepared['path']}report.md", f"{prepared['path']}report.pdf"]
    expected = computed((EXPECTED / "test-completion-report.md").read_text(encoding="utf-8"))
    actual = computed((folder / "report.md").read_text(encoding="utf-8"))
    assert actual == expected, "\n" + difference(expected, actual)
    assert sorted(p.name for p in (folder / "charts").iterdir()) == ["comparison.svg", "criteria.svg", "outcomes.svg"]
    assert pdf_pages(folder / "report.pdf") > 1
