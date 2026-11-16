"""The inputs and errors of ``reports.prepare_report`` and ``reports.render_report`` (mcp-tools.md)."""

import pytest

from retroagent.reports import render
from retroagent.servers.reports import server


def code(call, *args, **kwargs) -> str:
    with pytest.raises(server.ToolError) as error:
        call(*args, **kwargs)
    return error.value.code


def test_prepare_refuses_what_it_cannot_do(reference):
    session, _ = reference
    assert code(server.prepare_report, session, "nonsense") == "invalid_argument"
    assert code(server.prepare_report, session, "test-cases", run_id="RUN-0004") == "invalid_argument"
    assert code(server.prepare_report, session, "completion", formats=["docx"]) == "invalid_argument"
    assert code(server.prepare_report, session, "status") == "invalid_argument"  # a Should report: not built yet
    assert code(server.prepare_report, session, "completion", run_id="RUN-0003") == "invalid_state"
    assert session.conn.execute("SELECT COUNT(*) FROM report").fetchone()[0] == 0  # nothing was stored as a report


def test_the_run_of_a_completion_report_can_be_given(reference):
    session, scenario = reference
    prepared = server.prepare_report(session, "completion", run_id=scenario.evaluated_run)
    assert f"| Evaluated run | {scenario.evaluated_run} |" in prepared["computed"]


def test_render_refuses_what_it_cannot_do(reference):
    session, _ = reference
    assert code(server.render_report, session, "RPT-0009", {}) == "not_found"
    prepared = server.prepare_report(session, "completion")
    assert code(server.render_report, session, prepared["report_id"], {"nonsense": "x"}) == "invalid_argument"
    server.render_report(session, prepared["report_id"], {})
    assert code(server.render_report, session, prepared["report_id"], {}) == "invalid_state"


def test_a_template_with_an_unresolved_marker_stops_the_report_and_stores_none(reference, tmp_path, monkeypatch):
    session, _ = reference
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "test-case-specification.md").write_text("# {{ project.name }}\n\n{{ metrics.nope }}\n")
    monkeypatch.setattr(render, "TEMPLATES", templates)
    with pytest.raises(server.ToolError, match=r"unknown marker \{\{ metrics.nope \}\} in test-case-specification.md"):
        server.prepare_report(session, "test-cases")
    assert session.conn.execute("SELECT COUNT(*) FROM report").fetchone()[0] == 0
    assert not (session.project_dir / ".retro" / "reports").exists()
