"""Server ``reports``: evaluates and renders reports (mcp-tools.md, Server ``reports``; ADR-0006, ADR-0018).

Run as ``python -m retroagent.servers.reports.server --project <dir> --session <id>``.

``evaluate`` computes metrics, exit criteria and the decision from stored records and stores the evaluation.
``prepare_report`` computes everything and writes the computed sections (``draft.md``) and the charts. From then on
the report does not change: ``render_report`` only adds the agent sections and reads no result. No tool calls a
model (ADR-0020); the text of the agent sections reaches this server only as an argument of ``render_report``.
"""

import json
import sqlite3
from pathlib import Path

import retroagent
from retroagent.config import Config, ConfigError, load_config
from retroagent.memory import execution, reporting
from retroagent.memory.db import utc_now
from retroagent.memory.ids import next_id
from retroagent.metrics import EvaluationError
from retroagent.metrics import evaluate as compute_evaluation
from retroagent.metrics.evaluation import Evaluation
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
from retroagent.servers.errors import ToolError
from retroagent.servers.serving import Context, Tool, page, schema, serve

# Report types of the Must requirements (FR-25): type -> template, blocks and whether it lists test cases.
TYPES = {
    "completion": ("test-completion-report.md", blocks.COMPLETION_BLOCKS, False),
    "test-cases": ("test-case-specification.md", blocks.TEST_CASE_BLOCKS, True),
}
KNOWN_TYPES = ("test-plan", "test-cases", "status", "defects", "completion")
USES_RUN = ("status", "defects", "completion")
FORMATS = ("md", "pdf")


def _config(context: Context) -> Config:
    try:
        return load_config(context.project_dir)
    except ConfigError as error:
        raise ToolError("invalid_state", str(error)) from error


def _formats(config: Config, requested: list[str] | None) -> list[str]:
    requested = requested or [config["reports.default_format"]]
    unknown = [f for f in requested if f not in FORMATS]
    if unknown:
        raise ToolError("invalid_argument", f"unknown format {unknown[0]!r}: use md or pdf")
    return ["md", *(["pdf"] if "pdf" in requested else [])]  # the PDF is always produced from the Markdown


def _evaluate(context: Context, conn: sqlite3.Connection, config: Config, run_id: str | None) -> Evaluation:
    """Compute and store the evaluation of ``run_id``, or of the default evaluated run (metrics.md)."""
    if run_id is not None and execution.get_run(conn, run_id) is None:
        raise ToolError("not_found", f"run {run_id!r} does not exist")  # INV-13
    candidate = context.version(conn, "candidate")
    try:
        return compute_evaluation(conn, candidate.commit, run_id=run_id, thresholds=config.thresholds())
    except EvaluationError as error:
        raise ToolError("invalid_state", str(error)) from error


# evaluate ------------------------------------------------------------------------------------------------------------


def evaluate(context: Context, run_id: str | None = None) -> dict:
    config = _config(context)
    with context.connection() as conn:
        evaluation = _evaluate(context, conn, config, run_id)
    inputs, decision = evaluation.inputs, evaluation.decision
    lines = blocks.decision_lines(evaluation)
    return {
        "evaluation_id": evaluation.id,
        "run_id": inputs.run.id,
        "baseline_run_id": inputs.baseline.id if inputs.baseline else None,
        "full_base_run_id": inputs.full_base.id if inputs.full_base else None,
        "full_candidate_run_id": inputs.full_candidate.id if inputs.full_candidate else None,
        "analysis_id": inputs.analysis_id,
        "decision": decision.outcome,
        "reasons": lines if decision.outcome == "do_not_release" else [],
        "conditions": lines if decision.outcome == "release_with_conditions" else [],
        "criteria": [blocks.criterion_view(c) for c in evaluation.criteria],
        "metrics": blocks.metric_views(evaluation.metrics),
    }


# prepare_report and render_report ------------------------------------------------------------------------------------


def prepare_report(context: Context, type: str, run_id: str | None = None, formats: list[str] | None = None) -> dict:
    if type not in KNOWN_TYPES:
        raise ToolError("invalid_argument", f"unknown report type {type!r}: use {', '.join(KNOWN_TYPES)}")
    if run_id is not None and type not in USES_RUN:
        raise ToolError("invalid_argument", f"the {type} report does not use run_id")
    if type not in TYPES:
        raise ToolError("invalid_argument", f"the {type} report is not available in this build")
    template, block_registry, with_test_cases = TYPES[type]
    config = _config(context)
    formats = _formats(config, formats)
    with context.connection() as conn:
        versions = context.versions(conn)
        pair = {role: (v.ref, v.commit) if v else None for role, v in versions.items()}
        evaluation = _evaluate(context, conn, config, run_id) if type == "completion" else None

        created_at, report_id = utc_now(), next_id(conn, "RPT")  # the row is inserted once the draft resolves
        ctx = blocks.Context(
            conn=conn,
            report_id=report_id,
            created_at=created_at,
            model=context.session(conn)["model"],
            tool_version=retroagent.__version__,
            project_name=config["project.name"],
            base=pair["base"],
            candidate=pair["candidate"],
            evaluation=evaluation,
        )
        language = config["language"]
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
        path = reporting.get_report(conn, report_id)["path"]
        limit = context.result_limit(conn)
    folder = context.project_dir / path
    folder.mkdir(parents=True, exist_ok=True)
    if drawings:
        (folder / "charts").mkdir(exist_ok=True)
    for name, svg in drawings.items():
        (folder / "charts" / name).write_bytes(svg)
    (folder / "draft.md").write_text(draft, encoding="utf-8")
    # The computed data is cut at the result limit; the whole draft is in the folder (mcp-tools.md). There is no
    # input to read the rest, so no next_line is returned.
    computed, meta = page(draft, 1, limit)
    return {
        "report_id": report_id,
        "type": type,
        "formats": formats,
        "path": path,
        "sections": [{"name": name, "purpose": blocks.AGENT_SECTIONS[name]} for name in agent_names(draft)],
        "computed": computed,
        "truncated": meta["truncated"],
    }


def render_report(context: Context, report_id: str, sections: dict[str, str]) -> dict:
    with context.connection() as conn:
        row = reporting.get_report(conn, report_id)
        if row is None:
            raise ToolError("not_found", f"report {report_id!r} does not exist")
        if row["status"] != "draft":
            raise ToolError("invalid_state", f"report {report_id} is already rendered")
        folder = context.project_dir / row["path"]
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
    files = _files(row["path"], produced)
    if failure is not None:  # the report is rendered with its Markdown; the error says what to install
        raise ToolError("unavailable", f"{failure} Files: {', '.join(files)}")
    return {"report_id": report_id, "status": "rendered", "files": files}


def _files(path: str, formats: list[str]) -> list[str]:
    return [str(Path(path) / f"report.{ext}") for ext in formats]


# get_report ----------------------------------------------------------------------------------------------------------


def get_report(context: Context, report_id: str) -> dict:
    with context.connection() as conn:
        row = reporting.get_report(conn, report_id)
        if row is None:
            raise ToolError("not_found", f"report {report_id!r} does not exist")
        evaluation = None
        if row["evaluation_id"] is not None:
            stored = conn.execute(
                "SELECT id, run_id, baseline_run_id, decision FROM evaluation WHERE id = ?", (row["evaluation_id"],)
            ).fetchone()
            evaluation = dict(stored)
    formats = json.loads(row["formats"])
    return {
        "report_id": row["id"],
        "type": row["type"],
        "status": row["status"],
        "model": row["model"],
        "created_at": row["created_at"],
        "path": row["path"],
        "formats": formats,
        "files": _files(row["path"], formats) if row["status"] == "rendered" else [],
        "evaluation": evaluation,
    }


TEXT = {"type": "string", "minLength": 1}
RUN_ID = {**TEXT, "description": "A completed suite run against the candidate. Default: the latest one."}
REPORT_ID = {**TEXT, "description": "Report ID, such as RPT-0001."}

TOOLS = [
    Tool(
        "evaluate",
        "Compute and store the metrics, exit criteria and release decision of a run, from stored records only. "
        "Values are formatted as the report shows them; copy them, never recompute them.",
        schema({"run_id": RUN_ID}),
        evaluate,
    ),
    Tool(
        "prepare_report",
        "First step of a report: compute it, write its computed sections and charts, and return the report ID, the "
        "computed data and the agent sections to write. Long computed data is cut (truncated true).",
        schema(
            {
                "type": {"type": "string", "enum": list(KNOWN_TYPES), "description": "Report type."},
                "run_id": {**RUN_ID, "description": "Only for status, defects and completion. Default: the latest."},
                "formats": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(FORMATS)},
                    "minItems": 1,
                    "description": "md, pdf. The Markdown is always produced. Default: reports.default_format.",
                },
            },
            ("type",),
        ),
        prepare_report,
    ),
    Tool(
        "render_report",
        "Second step: add the agent sections to a prepared report and write its files. Computes nothing again. "
        "Sections not given are rendered as Not provided.",
        schema(
            {
                "report_id": {**REPORT_ID, "description": "A draft report from prepare_report."},
                "sections": {
                    "type": "object",
                    # The names depend on the report (analysis.DEF-001), so they are checked by the tool.
                    "additionalProperties": {"type": "string"},
                    "description": "Text of each agent section, by the exact names listed by prepare_report.",
                },
            },
            ("report_id", "sections"),
        ),
        render_report,
    ),
    Tool(
        "get_report",
        "Get a report: its status, type, files and the run and decision of its evaluation.",
        schema({"report_id": REPORT_ID}, ("report_id",)),
        get_report,
    ),
]


if __name__ == "__main__":
    serve("reports", TOOLS)
