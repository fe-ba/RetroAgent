"""Terminal tables of runs, status and history (FR-30). Timestamps are shown in local time with their offset.

Cells fold instead of being cut, so a narrow terminal never hides an identifier or a count.
"""

from datetime import datetime

from rich.table import Table

from retroagent.runtime.commands import RunRow, Status
from retroagent.runtime.session import Version

_COUNT_COLUMNS = ("executed", "passed", "failed", "error", "blocked", "skipped")


def local_time(timestamp: str | None) -> str:
    if timestamp is None:
        return "-"
    return datetime.fromisoformat(timestamp).astimezone().isoformat(sep=" ", timespec="seconds")


def runs_table(rows: list[RunRow], title: str = "Runs") -> Table:
    table = Table(title=title)
    for name in ("Run", "Version", "Ref", "Commit", "Scope", "Status", "Executions"):
        table.add_column(name, overflow="fold")
    for name in _COUNT_COLUMNS:
        table.add_column(name.capitalize(), justify="right", overflow="fold")
    table.add_column("Started", overflow="fold")
    for row in rows:
        total = row.counts["executed"] + row.counts["blocked"] + row.counts["skipped"]
        table.add_row(
            row.run_id,
            row.version_role,
            row.ref,
            row.commit[:12],
            row.scope,
            row.status,
            str(total),
            *(str(row.counts[name]) for name in _COUNT_COLUMNS),
            local_time(row.started_at),
        )
    return table


def _version(version: Version | None) -> str:
    return f"{version.ref} ({version.commit[:12]})" if version else "not set"


def status_tables(status: Status) -> list[Table]:
    session = Table(title="Session", show_header=False)
    session.add_column("Item")
    session.add_column("Value", overflow="fold")
    session.add_row("Session", str(status.session_id))
    session.add_row("Baseline", _version(status.base))
    session.add_row("Candidate", _version(status.candidate))
    session.add_row("Mode", status.mode)
    session.add_row("Model calls", str(status.model_calls))
    session.add_row("Tokens", str(status.tokens))

    test_cases = Table(title="Test cases", show_header=False)
    test_cases.add_column("Status")
    test_cases.add_column("Count", justify="right")
    for name, count in status.test_cases.items():
        test_cases.add_row(name.capitalize(), str(count))
    suite = "none" if status.current_suite_size is None else str(status.current_suite_size)
    test_cases.add_row("Current suite", suite)

    tables = [session, test_cases]
    if status.latest_run is not None:
        tables.append(runs_table([status.latest_run], title="Latest run"))
    return tables


def history_table(rows: list[RunRow]) -> Table:
    return runs_table(rows, title="History")
