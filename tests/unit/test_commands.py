"""Parsing of the direct commands, their exit codes and their tables."""

import re

import pytest
from rich.console import Console

from retroagent.cli import tables
from retroagent.cli.interactive import exit_code
from retroagent.runtime.commands import Command, CommandError, RunOutcome, RunRow, Status, parse
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
        ("/analyze v1.0 v1.1", "not available yet"),
        ("/defects", "not available yet"),
        ("what changed?", "not available yet"),
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


@pytest.mark.parametrize(
    "outcome, code",
    [
        (RunOutcome([row(executed=22, passed=20, failed=2)]), 0),  # failed tests are not an error of /run
        (RunOutcome([], error=ToolError("denied", "not approved")), 4),
        (RunOutcome([], error=ToolError("invalid_state", "no suite")), 1),
        (RunOutcome([row("error", blocked=26)], not_run="the candidate was not run"), 1),
        (RunOutcome([row("interrupted")], interrupted=True), 1),
    ],
)
def test_exit_code_of_run(outcome, code):
    assert exit_code(outcome) == code


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
    assert [line.split()[-2] for line in text.splitlines() if "Model calls" in line or "Tokens" in line] == ["0"] * 2
