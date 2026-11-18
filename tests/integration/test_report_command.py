"""``/report`` with the reference script on the records of the reference scenario (runtime.md, Model commands; skill
``test-reporting``): the evaluation, the draft, the agent sections sent to ``reports.render_report``, the rendered
report in Markdown and PDF, and the fields ``reports`` and ``decision`` of the JSON output."""

import contextlib
import io
import json
import re
from pathlib import Path

import pytest
from fixtures.agent_session import REPORT_SECTIONS, Scripted, report_script, tool_rows
from fixtures.example_project import start
from fixtures.reference_scenario import CANDIDATE_COMMIT, MIN_PASS_RATE
from fixtures.tool_definitions import STEP_OWN_TOOLS, STEP_READ_TOOLS

from retroagent.cli.main import main
from retroagent.memory import connect
from retroagent.metrics import Thresholds, evaluate
from retroagent.resources import __file__ as resources_file
from retroagent.runtime import commands

EXPECTED = Path(resources_file).parent / "examples" / "shop-api" / "expected" / "test-completion-report.md"
VARIABLE_ROWS = ("| Generated |", "| Model |", "| RetroAgent |", "| Run duration |", "| Test time |")
FOLDER = ".retro/reports/RPT-0001-completion/"


def computed(text: str) -> str:
    """The computed sections of a report or of a draft, as SC-11 compares them: no blockquote, no marker of an agent
    section, no variable row."""
    lines = [
        line
        for line in text.split("\n")
        if not line.startswith((">", "<!-- agent:")) and not line.startswith(VARIABLE_ROWS)
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def pdf_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except OSError:
        return False
    return True


def test_report_completion_follows_the_skill_and_renders_md_and_pdf(triaged_reference_project):
    path = triaged_reference_project.path
    script = Scripted(report_script())
    with start(path, script) as session:
        evaluations_before = session.conn.execute("SELECT COUNT(*) FROM evaluation").fetchone()[0]
        result = commands.report(session, "completion", format="pdf")
        rows = tool_rows(session.conn, session.id)
        evaluations = session.conn.execute("SELECT * FROM evaluation ORDER BY id").fetchall()
        report = session.conn.execute("SELECT * FROM report").fetchone()
        outcome = commands.session_outcome(session)
    assert script.remaining == 0

    # The template and the tools of the step report.
    first = script.requests[0]
    assert first.messages[1].content == (
        "Load the skill `test-reporting` and generate the `completion` report in format `pdf`."
    )
    assert sorted(t.name for t in first.tools) == sorted([*STEP_READ_TOOLS, *STEP_OWN_TOOLS["report"]])

    # Every call was dispatched, in the order of the skill.
    assert [(r["server"], r["tool"], r["outcome"]) for r in rows] == [
        ("runtime", "load_skill", "ok"),
        ("memory", "get_executions", "ok"),
        ("memory", "get_runs", "ok"),
        ("reports", "prepare_report", "ok"),
        ("reports", "render_report", "ok" if pdf_available() else "error"),
    ]

    # The evaluation stored by prepare_report, and the report it belongs to.
    assert len(evaluations) == evaluations_before + 1
    evaluation = evaluations[-1]
    assert (evaluation["run_id"], evaluation["baseline_run_id"], evaluation["decision"]) == (
        "RUN-0004",
        "RUN-0003",
        "do_not_release",
    )
    assert (report["id"], report["type"], report["status"], report["evaluation_id"]) == (
        "RPT-0001",
        "completion",
        "rendered",
        evaluation["id"],
    )
    assert report["model"] == "ollama/test-model"

    # The draft that the model read: computed sections, with the markers of the agent sections.
    prepared = json.loads([m.content for m in script.requests[3].messages if m.role == "tool"][-1])
    assert prepared["truncated"] is False and prepared["computed"].count("<!-- agent:") == 5
    assert computed(prepared["computed"]) == computed(EXPECTED.read_text(encoding="utf-8"))

    # The agent sections sent to render_report, as recorded in tool_call.
    sent = json.loads(rows[-1]["arguments"])
    assert sent == {"report_id": "RPT-0001", "sections": REPORT_SECTIONS}

    # The rendered report: computed sections equal the expected report, agent sections marked as the model's.
    text = (path / FOLDER / "report.md").read_text(encoding="utf-8")
    assert computed(text) == computed(EXPECTED.read_text(encoding="utf-8"))
    assert text.count("> **Agent analysis** · written by `ollama/test-model`, not computed.") == 5
    for section in REPORT_SECTIONS.values():
        assert f"> {section}" in text
    assert "Not provided." not in text
    if pdf_available():
        assert (path / FOLDER / "report.pdf").read_bytes().startswith(b"%PDF-")
        assert json.loads(report["formats"]) == ["md", "pdf"]
    else:
        assert json.loads(report["formats"]) == ["md"]

    # What the turn recorded, and the outcome of the session.
    recorded = dict(result.recorded)
    assert recorded["reports__prepare_report"] == 1
    assert recorded.get("reports__render_report") == (1 if pdf_available() else None)
    assert outcome.reports == [{"id": "RPT-0001", "path": FOLDER}]
    assert outcome.decision == "do_not_release"


def test_report_in_json_names_the_report_and_the_decision(triaged_reference_project, fake_model):
    if not pdf_available():
        pytest.skip("the Pango system library is not installed")
    path = triaged_reference_project.path
    fake_model(Scripted(report_script("RPT-0001 is rendered.")))
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(["-C", str(path), "--output-format", "json", "-p", "/report completion --format pdf"])
    output = json.loads(buffer.getvalue())
    assert (code, output["exit_code"]) == (3, 3)  # do_not_release (cli.md, Exit codes)
    assert output["result"] == "RPT-0001 is rendered."
    assert output["reports"] == [{"id": "RPT-0001", "path": FOLDER}]
    assert output["decision"] == "do_not_release"
    assert output["recorded"] == {"reports__prepare_report": 1, "reports__render_report": 1}
    assert output["runs"] == [] and output["denied"] == 0


def test_a_session_that_evaluated_nothing_has_no_decision_even_with_older_evaluations(triaged_reference_project):
    """The decision and the reports of a session are those created after it started (runtime.md)."""
    path = triaged_reference_project.path
    conn = connect(path)
    try:
        evaluate(conn, CANDIDATE_COMMIT, thresholds=Thresholds(min_pass_rate=MIN_PASS_RATE))
    finally:
        conn.close()
    with start(path) as session:
        outcome = commands.session_outcome(session)
    assert (outcome.decision, outcome.reports) == (None, [])


def test_a_report_that_cannot_be_asked_for_calls_no_model(triaged_reference_project, fake_model, capsys):
    provider = fake_model(Scripted([]))
    project = str(triaged_reference_project.path)
    with pytest.raises(SystemExit) as stopped:  # parsed before the session starts
        main(["-C", project, "-p", "/report test-plan"])
    assert stopped.value.code == 2
    assert "the test-plan report is not available in this build" in capsys.readouterr().err
    assert main(["-C", project, "-p", "/report completion --run RUN-9999"]) == 2  # the run is checked in the session
    assert "run RUN-9999 does not exist" in capsys.readouterr().err
    assert provider.requests == []
