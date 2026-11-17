"""Parsing of the slash commands, the exit code of /run and the tables."""

import re

import pytest
from rich.console import Console

from retroagent.cli import tables
from retroagent.cli.interactive import run_failed
from retroagent.runtime.commands import (
    Command,
    CommandError,
    NotAvailable,
    RunOutcome,
    RunRow,
    Status,
    help_rows,
    parse,
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


@pytest.mark.parametrize("name", ["/cycle", "/select", "/design", "/implement", "/triage", "/report", "/defects"])
def test_the_commands_of_slice_4_are_known_and_not_available(name):
    with pytest.raises(NotAvailable, match="is not available yet"):
        parse(name)
    assert help_rows(name)[0][1].endswith("Not available yet in this build.")


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
