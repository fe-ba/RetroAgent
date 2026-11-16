"""Server ``reports``: ``prepare_report`` and ``render_report`` as plain functions (mcp-tools.md, ADR-0018).

``prepare_report`` computes everything and writes the computed sections (``draft.md``) and the charts. From then
on the report does not change: ``render_report`` only adds the agent sections and reads no result.
"""

import json
from pathlib import Path

import retroagent
from retroagent.memory import reporting, sessions
from retroagent.memory.db import utc_now
from retroagent.memory.ids import next_id
from retroagent.metrics import EvaluationError, evaluate
from retroagent.reports import blocks, charts, pdf
from retroagent.reports.render import (
    Renderer,
    ReportError,
    add_agent_sections,
    agent_names,
    chart_references,
    find_template,
    strip_comments,
)
from retroagent.runtime.session import Session
from retroagent.servers.errors import ToolError

# Report types of the Must requirements (FR-25): type -> template, blocks and whether it lists test cases.
TYPES = {
    "completion": ("test-completion-report.md", blocks.COMPLETION_BLOCKS, False),
    "test-cases": ("test-case-specification.md", blocks.TEST_CASE_BLOCKS, True),
}
KNOWN_TYPES = ("test-plan", "test-cases", "status", "defects", "completion")
USES_RUN = ("status", "defects", "completion")
FORMATS = ("md", "pdf")


def _formats(session: Session, requested: list[str] | None) -> list[str]:
    requested = requested or [session.config["reports.default_format"]]
    unknown = [f for f in requested if f not in FORMATS]
    if unknown:
        raise ToolError("invalid_argument", f"unknown format {unknown[0]!r}: use md or pdf")
    return ["md", *(["pdf"] if "pdf" in requested else [])]  # the PDF is always produced from the Markdown


def prepare_report(session: Session, type: str, run_id: str | None = None, formats: list[str] | None = None) -> dict:
    conn = session.conn
    if type not in KNOWN_TYPES:
        raise ToolError("invalid_argument", f"unknown report type {type!r}: use {', '.join(KNOWN_TYPES)}")
    if run_id is not None and type not in USES_RUN:
        raise ToolError("invalid_argument", f"the {type} report does not use run_id")
    if type not in TYPES:
        raise ToolError("invalid_argument", f"the {type} report is not available yet")
    template, block_registry, with_test_cases = TYPES[type]
    formats = _formats(session, formats)
    versions = session.versions()
    pair = {role: (v.ref, v.commit) if v else None for role, v in versions.items()}

    evaluation = None
    if type == "completion":
        if versions["candidate"] is None:
            raise ToolError("invalid_state", "the session has no versions")
        try:
            evaluation = evaluate(
                conn, versions["candidate"].commit, run_id=run_id, thresholds=session.config.thresholds()
            )
        except EvaluationError as error:
            raise ToolError("invalid_state", str(error)) from error

    created_at, report_id = utc_now(), next_id(conn, "RPT")  # the row is inserted once the draft resolves
    ctx = blocks.Context(
        conn=conn,
        report_id=report_id,
        created_at=created_at,
        model=sessions.get_session(conn, session.id)["model"],
        tool_version=retroagent.__version__,
        project_name=session.config["project.name"],
        base=pair["base"],
        candidate=pair["candidate"],
        evaluation=evaluation,
    )
    language = session.config["language"]
    try:
        draft = Renderer(language, blocks.AGENT_SECTIONS).render(
            template, blocks.scope(ctx, block_registry, with_test_cases=with_test_cases)
        )
        template_text = strip_comments(find_template(template, language).read_text(encoding="utf-8"))
        drawings = {name: charts.draw(name, evaluation) for name in chart_references(template_text)}
    except ReportError as error:
        raise ToolError("invalid_argument", str(error)) from error
    draft += "\n"

    row_id = reporting.add_report(
        conn,
        type=type,
        model=ctx.model,
        evaluation_id=evaluation.id if evaluation else None,
        formats=formats,
        created_at=created_at,
    )
    assert row_id == report_id
    folder = session.project_dir / reporting.get_report(conn, report_id)["path"]
    folder.mkdir(parents=True, exist_ok=True)
    if drawings:
        (folder / "charts").mkdir(exist_ok=True)
    for name, svg in drawings.items():
        (folder / "charts" / name).write_bytes(svg)
    (folder / "draft.md").write_text(draft, encoding="utf-8")
    sections = [{"name": name, "purpose": blocks.AGENT_SECTIONS[name]} for name in agent_names(draft)]
    return {
        "report_id": report_id,
        "type": type,
        "formats": formats,
        "path": str(folder.relative_to(session.project_dir)) + "/",
        "sections": sections,
        "computed": draft,
    }


def render_report(session: Session, report_id: str, sections: dict[str, str]) -> dict:
    conn = session.conn
    row = reporting.get_report(conn, report_id)
    if row is None:
        raise ToolError("not_found", f"report {report_id} does not exist")
    if row["status"] != "draft":
        raise ToolError("invalid_state", f"report {report_id} is already rendered")
    folder = session.project_dir / row["path"]
    draft_path = folder / "draft.md"
    if not draft_path.is_file():
        raise ToolError("invalid_state", f"the draft of report {report_id} is missing: {draft_path}")
    draft = draft_path.read_text(encoding="utf-8")
    unknown = sorted(set(sections) - set(agent_names(draft)))
    if unknown:
        raise ToolError("invalid_argument", f"report {report_id} has no agent section {unknown[0]!r}")

    text = add_agent_sections(draft.rstrip("\n"), row["model"], {k: str(v) for k, v in sections.items()}) + "\n"
    (folder / "report.md").write_text(text, encoding="utf-8")
    draft_path.unlink()
    produced, failure = ["md"], None
    if "pdf" in json.loads(row["formats"]):
        try:
            pdf.write_pdf(text, folder / "report.pdf", folder)
            produced.append("pdf")
        except pdf.PdfUnavailable as error:
            failure = error
    reporting.mark_rendered(conn, report_id, produced)
    files = [str(Path(row["path"]) / f"report.{ext}") for ext in produced]
    if failure is not None:
        raise ToolError("unavailable", f"{failure} Files: {', '.join(files)}")
    return {"report_id": report_id, "status": "rendered", "files": files}
