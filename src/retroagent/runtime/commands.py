"""Direct commands of spec/runtime.md: ``/run``, ``/status`` and ``/history``, as functions that return data.

They call the runner and the data layer and print nothing. Counts and statuses come from stored records; no
function here takes or computes a test result.
"""

import json
import shlex
from collections.abc import Sequence
from dataclasses import dataclass, field

from retroagent.memory import design, execution, sessions
from retroagent.memory.db import utc_now
from retroagent.runtime.session import Session, Version
from retroagent.servers.errors import ToolError
from retroagent.servers.test_runner import runner

COMMANDS = ("/run", "/status", "/history", "/help", "/exit")
ON = ("base", "candidate", "both")
HISTORY_DEFAULT = 10

HELP = (
    (
        "/run [target] [--on <version>]",
        "Execute tests. target: suite (default), all, or test case IDs separated by"
        " spaces. --on: base, candidate (default) or both.",
    ),
    ("/status", "Session versions, test cases by status, the current suite and the latest run."),
    ("/history [n]", "The last n runs. Default: 10."),
    ("/help", "Show this help."),
    ("/exit", "End the session."),
)


class CommandError(Exception):
    """A direct command was used with invalid arguments."""


@dataclass(frozen=True)
class Command:
    name: str  # one of COMMANDS
    target: str | tuple[str, ...] = "suite"  # /run: "suite", "all" or test case IDs
    on: str = "candidate"  # /run
    limit: int = HISTORY_DEFAULT  # /history


def parse(line: str) -> Command:
    """Parse one direct command. Raises ``CommandError``; a line that is not a direct command of this build is one."""
    try:
        words = shlex.split(line)
    except ValueError as error:
        raise CommandError(str(error)) from error
    if not words or words[0] not in COMMANDS:
        raise CommandError(f"not available yet: {line.strip()}")
    name, args = words[0], words[1:]
    if name == "/run":
        return _parse_run(args)
    if name == "/history":
        if len(args) > 1 or (args and not (args[0].isdigit() and int(args[0]) > 0)):
            raise CommandError("usage: /history [n], where n is a positive integer")
        return Command(name, limit=int(args[0]) if args else HISTORY_DEFAULT)
    if args and name != "/help":
        raise CommandError(f"usage: {name}")
    return Command(name)


def _parse_run(args: list[str]) -> Command:
    on, targets = "candidate", []
    position = 0
    while position < len(args):
        word = args[position]
        if word == "--on":
            if position + 1 == len(args) or args[position + 1] not in ON:
                raise CommandError(f"--on needs one of {', '.join(ON)}")
            on = args[position + 1]
            position += 2
            continue
        if word.startswith("-"):
            raise CommandError(f"unknown option {word}")
        targets.append(word)
        position += 1
    if not targets:
        return Command("/run", "suite", on)
    if targets in (["suite"], ["all"]):
        return Command("/run", targets[0], on)
    if "suite" in targets or "all" in targets:
        raise CommandError("the target is suite, all, or test case IDs, not a mix of them")
    return Command("/run", tuple(dict.fromkeys(targets)), on)


@dataclass(frozen=True)
class RunRow:
    """A stored run with the counts of its executions."""

    run_id: str
    version_role: str
    ref: str
    commit: str
    scope: str
    status: str
    counts: dict[str, int]
    started_at: str
    ended_at: str | None
    error: str | None


@dataclass(frozen=True)
class RunOutcome:
    runs: list[RunRow] = field(default_factory=list)
    error: ToolError | None = None  # the run_tests call that failed; no run was stored for it
    interrupted: bool = False  # the user interrupted a run; it is stored as interrupted
    not_run: str | None = None  # why the candidate of --on both was not run


def _row(conn, run) -> RunRow:
    return RunRow(
        run_id=run["id"],
        version_role=run["version_role"],
        ref=run["ref"],
        commit=run["commit"],
        scope=run["scope"],
        status=run["status"],
        counts=execution.execution_counts(conn, run["id"]),
        started_at=run["started_at"],
        ended_at=run["ended_at"],
        error=run["error"],
    )


def run(session: Session, target: str | Sequence[str] = "suite", on: str = "candidate") -> RunOutcome:
    """``/run``: call ``test_runner.run_tests`` for each version. ``both`` runs the baseline first, and the
    candidate only when the baseline run is ``completed``."""
    if on not in ON:
        raise ValueError(f"on must be one of {', '.join(ON)}")
    if isinstance(target, str) and target in ("suite", "all"):
        scope, test_case_ids = target, None
    else:
        scope, test_case_ids = "selected", list(target)
    roles = ("base", "candidate") if on == "both" else (on,)
    runs: list[RunRow] = []
    for role in roles:
        if runs and runs[-1].status != "completed":
            return RunOutcome(runs, not_run=f"the candidate was not run: {runs[-1].run_id} is {runs[-1].status}")
        before = _latest_run_id(session)
        try:
            run_id = _call_run_tests(session, role, scope, test_case_ids)
        except ToolError as error:
            return RunOutcome(runs, error=error)
        except KeyboardInterrupt:
            latest = _latest_run_id(session)
            if latest is not None and latest != before:
                runs.append(_row(session.conn, execution.get_run(session.conn, latest)))
            return RunOutcome(runs, interrupted=True)
        runs.append(_row(session.conn, execution.get_run(session.conn, run_id)))
    return RunOutcome(runs)


def _latest_run_id(session: Session) -> str | None:
    rows = execution.list_runs(session.conn, 1, session_id=session.id)
    return rows[0]["id"] if rows else None


def _call_run_tests(session: Session, version: str, scope: str, test_case_ids: list[str] | None) -> str:
    """One call of ``test_runner.run_tests``, recorded in ``tool_call``. Returns the run ID."""
    arguments = {"version": version, "scope": scope}
    if test_case_ids is not None:
        arguments["test_case_ids"] = test_case_ids
    versions = session.versions()
    base, candidate = versions["base"], versions["candidate"]
    started_at = utc_now()
    outcome, message = "error", None
    try:
        summary = runner.run_tests(
            session.project_dir,
            session_id=session.id,
            version=version,
            scope=scope,
            base_ref=base.ref if base else None,
            base_commit=base.commit if base else None,
            candidate_ref=candidate.ref if candidate else None,
            candidate_commit=candidate.commit if candidate else None,
            commands_approved=session.trust_commands,
            test_case_ids=test_case_ids,
        )
        outcome = "ok"
        return summary.run_id
    except ToolError as error:
        outcome = "denied" if error.code == "denied" else "error"
        message = str(error)
        raise
    except KeyboardInterrupt:
        message = "interrupted by the user"
        raise
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        raise
    finally:
        sessions.record_tool_call(
            session.conn,
            session_id=session.id,
            server="test_runner",
            tool="run_tests",
            arguments=json.dumps(arguments),
            outcome=outcome,
            error=message,
            started_at=started_at,
        )


@dataclass(frozen=True)
class Status:
    session_id: int
    base: Version | None
    candidate: Version | None
    test_cases: dict[str, int]  # active test cases by status
    current_suite_size: int | None  # None when there is no current suite
    latest_run: RunRow | None
    mode: str = "default"  # modes arrive with the turn (slice 3)
    model_calls: int = 0  # no model is called in slice 1
    tokens: int = 0


def status(session: Session) -> Status:
    """``/status``."""
    versions = session.versions()
    base, candidate = versions["base"], versions["candidate"]
    suite_size = None
    if base and candidate:
        suite_id = design.current_suite(session.conn, base.commit, candidate.commit)
        if suite_id is not None:
            suite_size = len(design.suite_test_cases(session.conn, suite_id))
    latest = execution.list_runs(session.conn, 1)
    return Status(
        session_id=session.id,
        base=base,
        candidate=candidate,
        test_cases=design.count_active_test_cases(session.conn),
        current_suite_size=suite_size,
        latest_run=_row(session.conn, latest[0]) if latest else None,
    )


def history(session: Session, limit: int = HISTORY_DEFAULT) -> list[RunRow]:
    """``/history [n]``: the latest runs of the project, from every session."""
    return [_row(session.conn, row) for row in execution.list_runs(session.conn, limit)]
