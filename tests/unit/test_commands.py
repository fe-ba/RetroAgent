"""Parsing of the slash commands, the exit code of /run and the tables."""

import re

import pytest
from rich.console import Console

from retroagent.cli import tables
from retroagent.cli.interactive import run_failed
from retroagent.runtime.commands import (
    SELECT,
    TRIAGE,
    Command,
    CommandError,
    DefectRow,
    NotAvailable,
    RunOutcome,
    RunRow,
    Status,
    design_message,
    help_rows,
    implement_message,
    parse,
    report_message,
)
from retroagent.runtime.session import Version
from retroagent.servers.errors import ToolError


@pytest.mark.parametrize(
    "line, command",
    [
        ("/run", Command("/run", "suite", "candidate")),
        ("/run suite", Command("/run", "suite", "candidate")),
        ("/run all --on both", Command("/run", "all", "both")),
        ("/run --on base all", Command("/run", "all", "base")),
        ("/run TC-001 TC-002 --on both", Command("/run", ("TC-001", "TC-002"), "both")),
        ("/run TC-001 TC-001", Command("/run", ("TC-001",), "candidate")),
        ("/status", Command("/status")),
        ("/history", Command("/history", limit=10)),
        ("/history 3", Command("/history", limit=3)),
        ("  /help  ", Command("/help")),
        ("/exit", Command("/exit")),
        ("/analyze", Command("/analyze")),
        ("/analyze v1.0 v1.1", Command("/analyze", refs=("v1.0", "v1.1"))),
        ("/mode", Command("/mode")),
        ("/mode plan", Command("/mode", argument="plan")),
        ("/model gemini", Command("/model", argument="gemini")),
        ("/help run", Command("/help", argument="run")),
        ("/clear", Command("/clear")),
        ("/skills", Command("/skills")),
        ("/mcp", Command("/mcp")),
        ("/init", Command("/init")),
        ("/select", Command("/select")),
        ("/design", Command("/design")),
        ("/design REQ-002", Command("/design", scope="REQ-002")),
        ("/design REQ-002   REQ-004", Command("/design", scope="REQ-002 REQ-004")),
        ('/design "the coupon rules"', Command("/design", scope="the coupon rules")),
        ("/implement", Command("/implement")),
        ("/implement TC-027", Command("/implement", ids=("TC-027",))),
        ("/implement TC-027 TC-028 TC-027", Command("/implement", ids=("TC-027", "TC-028"))),
        ("/triage", Command("/triage")),
        ("/triage RUN-0004", Command("/triage", run_id="RUN-0004")),
        ("/defects", Command("/defects")),
        ("/defects --all", Command("/defects", include_closed=True)),
        (
            "/defects close DEF-001 fixed outside the tested scope",
            Command("/defects", defect_id="DEF-001", reason="fixed outside the tested scope"),
        ),
        (
            '/defects close DEF-001 "no longer applies"',
            Command("/defects", defect_id="DEF-001", reason="no longer applies"),
        ),
        ("/report completion", Command("/report", report_type="completion")),
        ("/report test-cases", Command("/report", report_type="test-cases")),
        (
            "/report completion --run RUN-0004 --format pdf",
            Command("/report", report_type="completion", run_id="RUN-0004", format="pdf"),
        ),
        ("/report --format md completion", Command("/report", report_type="completion", format="md")),
    ],
)
def test_parse(line, command):
    assert parse(line) == command


@pytest.mark.parametrize(
    "line, message",
    [
        ("/run all --on", "--on needs one of base, candidate, both"),
        ("/run all --on nowhere", "--on needs one of"),
        ("/run all --fast", "unknown option --fast"),
        ("/run all TC-001", "not a mix"),
        ("/history x", "usage: /history [n]"),
        ("/history 1 2", "usage: /history [n]"),
        ("/status now", "usage: /status"),
        ("/analyze v1.0", "give both refs, or none"),
        ("/mode fast", "unknown mode fast"),
        ("/clear all", "usage: /clear"),
        ("/select now", "usage: /select"),
        ("/triage RUN-0003 RUN-0004", "usage: /triage [run_id]"),
        ("/defects close", "usage: /defects close <id> <reason>"),
        ("/defects close DEF-001", "usage: /defects close <id> <reason>"),
        ("/defects --open", "usage: /defects [--all], or /defects close <id> <reason>"),
        ("/defects --all DEF-001", "usage: /defects [--all], or /defects close <id> <reason>"),
        ("/report", "usage: /report <type>"),
        ("/report summary", "usage: /report <type>"),
        ("/report completion test-cases", "usage: /report <type>"),
        ("/report completion --run", "usage: /report <type>"),
        ("/report completion --format pdf --format md", "usage: /report <type>"),
        ("/report completion --format docx", "unknown format docx; use md or pdf"),
        ("/report completion --fast", "unknown option --fast"),
        ("/report test-cases --run RUN-0004", "the test-cases report does not use --run"),
        ("/nowhere", "unknown command /nowhere"),
        ("what changed?", "not a command"),
    ],
)
def test_parse_refuses(line, message):
    with pytest.raises(CommandError, match=re.escape(message)):
        parse(line)


def row(status="completed", **counts):
    full = dict.fromkeys(("executed", "blocked", "skipped", "passed", "failed", "error"), 0) | counts
    return RunRow(
        "RUN-0001",
        "base",
        "v1.0",
        "c7d45ad" + "0" * 33,
        "all",
        status,
        full,
        "2026-11-16T10:00:00.000+00:00",
        None,
        None,
    )


def test_cycle_takes_both_refs_or_none():
    assert parse("/cycle") == Command("/cycle")
    assert parse("/cycle v1.0 v1.1") == Command("/cycle", refs=("v1.0", "v1.1"))
    with pytest.raises(CommandError, match=r"usage: /cycle \[base\] \[candidate\]: give both refs, or none"):
        parse("/cycle v1.0")
    assert not help_rows("/cycle")[0][1].endswith("Not available yet in this build.")


@pytest.mark.parametrize("report_type", ["test-plan", "status", "defects"])
def test_the_should_reports_are_known_and_not_available(report_type):
    with pytest.raises(NotAvailable, match=f"the {report_type} report is not available in this build"):
        parse(f"/report {report_type}")


def test_the_template_of_report():
    """runtime.md, Model commands: the type, then the run and the format when they are given."""
    assert report_message("completion") == ("Load the skill `test-reporting` and generate the `completion` report.")
    assert report_message("completion", "RUN-0004", "pdf") == (
        "Load the skill `test-reporting` and generate the `completion` report for run `RUN-0004` in format `pdf`."
    )
    assert report_message("test-cases", format="md") == (
        "Load the skill `test-reporting` and generate the `test-cases` report in format `md`."
    )
    assert not help_rows("/report")[0][1].endswith("Not available yet in this build.")


def test_the_templates_of_select_and_design():
    """runtime.md, Model commands: the fixed messages, with the backticks of the specification kept."""
    assert SELECT == (
        "Load the skill `test-selection` and select and prioritize the regression suite for the latest impact analysis."
    )
    assert design_message(None) == (
        "Load the skill `test-design` and design test cases for the impacted areas not covered by the current suite."
    )
    assert (
        design_message("REQ-002 REQ-004") == "Load the skill `test-design` and design test cases for `REQ-002 REQ-004`."
    )
    for name in ("/select", "/design"):
        assert not help_rows(name)[0][1].endswith("Not available yet in this build.")


def test_the_templates_of_implement():
    """runtime.md, Model commands: with IDs, the rewrite clause; without, every designed test case of the suite."""
    assert implement_message() == (
        "Load the skill `test-design` and implement all designed test cases of the current suite."
    )
    assert implement_message(["TC-027", "TC-028"]) == (
        "Load the skill `test-design` and implement the test cases `TC-027, TC-028`; rewrite those that are already"
        " `implemented`."
    )
    assert not help_rows("/implement")[0][1].endswith("Not available yet in this build.")


def test_the_template_of_triage():
    """runtime.md, Model commands: the run is always named; without one, the runtime names the latest run."""
    assert TRIAGE.format(run_id="RUN-0004") == (
        "Load the skill `failure-triage` and triage the failed executions of run `RUN-0004`."
    )
    for name in ("/triage", "/defects"):
        assert not help_rows(name)[0][1].endswith("Not available yet in this build.")


def test_help_lists_every_command():
    usages = [usage for usage, _ in help_rows()]
    assert len(usages) == 19 and usages[1] == "/analyze [base] [candidate]"


@pytest.mark.parametrize(
    "outcome, failed",
    [
        (RunOutcome([row(executed=22, passed=20, failed=2)]), False),  # failed tests are not an error of /run
        (RunOutcome([], error=ToolError("denied", "not approved")), False),  # exit 4, counted by the session
        (RunOutcome([], error=ToolError("invalid_state", "no suite")), True),
        (RunOutcome([row("error", blocked=26)], not_run="the candidate was not run"), True),
        (RunOutcome([row("interrupted")], interrupted=True), True),
    ],
)
def test_run_failed(outcome, failed):
    assert run_failed(outcome) is failed


def render(*renderables):
    console = Console(record=True, width=200, color_system=None)
    for item in renderables:
        console.print(item)
    return console.export_text()


def test_the_runs_table_shows_the_counts():
    text = render(tables.runs_table([row(executed=22, passed=20, failed=2)]))
    line = next(line for line in text.splitlines() if "RUN-0001" in line)
    cells = [cell.strip() for cell in line.split("│")[1:-1]]
    assert cells[:13] == ["RUN-0001", "base", "v1.0", "c7d45ad00000", "all", "completed", "22", "22", "20", "2", "0",
                          "0", "0"]  # fmt: skip


def test_the_status_tables_show_every_row():
    status = Status(
        session_id=3,
        base=Version("v1.0", "c7d45ad" + "0" * 33),
        candidate=None,
        test_cases={"designed": 1, "implemented": 0},
        current_suite_size=None,
        latest_run=row("error", blocked=26),
    )
    text = render(*tables.status_tables(status))
    for expected in (
        "Baseline",
        "v1.0 (c7d45ad00000)",
        "Candidate",
        "not set",
        "Mode",
        "default",
        "Model calls",
        "Tokens",
        "Designed",
        "Implemented",
        "Current suite",
        "none",
        "Latest run",
    ):
        assert expected in text
    assert "0 input, 0 output" in text


def defect(status="open", **closing):
    return DefectRow(
        defect_id="DEF-001",
        severity="high",
        status=status,
        title="Shipping is not charged",
        test_cases=("TC-020",),
        detected_run_id="RUN-0004",
        detected_at="2026-11-16T10:00:00.000+00:00",
        closed_by=closing.get("closed_by"),
        closed_run_id=closing.get("closed_run_id"),
        closed_at=closing.get("closed_at"),
        close_reason=closing.get("close_reason"),
    )


def test_the_defects_table_shows_open_defects_and_with_all_how_they_were_closed():
    text = render(tables.defects_table([defect()]))
    assert "Open defects" in text
    for expected in ("DEF-001", "high", "open", "Shipping is not charged", "TC-020", "RUN-0004"):
        assert expected in text
    assert "Closed by" not in text
    closed = defect(
        "closed",
        closed_by="run",
        closed_run_id="RUN-0006",
        closed_at="2026-11-16T11:00:00.000+00:00",
        close_reason="Every linked test case passed in RUN-0006: TC-020.",
    )
    text = render(tables.defects_table([closed], include_closed=True))
    for expected in ("Closed by", "run (RUN-0006)", "Every linked test case passed"):
        assert expected in text
