"""Slash commands of spec/runtime.md, as functions that return data; they print nothing.

**Direct** commands run without the model. ``/run`` calls ``test_runner.run_tests`` through ``turn.call_tool``: the
same checks, question and ``tool_call`` row as a call of the model, dispatched to the MCP server. A direct command and
its output are not added to the conversation.

**Model** commands empty the conversation and send a fixed template with the tool set of their step. This build
has ``/analyze``, ``/select`` and ``/design``; the other commands of cli.md are parsed and answered as not available
yet.

Counts and statuses come from stored records; no function here takes or computes a test result.
"""

import json
import shlex
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from retroagent.context import tools
from retroagent.memory import design, execution
from retroagent.runtime import permissions, turn
from retroagent.runtime.session import Session, SessionError, Version
from retroagent.servers.errors import ToolError

ON = ("base", "candidate", "both")
HISTORY_DEFAULT = 10

# The fixed templates of the model commands (runtime.md, Model commands) and the tool set of each.
ANALYZE = "Load the skill `impact-analysis` and analyze the impact of the change between the session versions."
ANALYZE_TOOL_SET = "analyze"
SELECT = (
    "Load the skill `test-selection` and select and prioritize the regression suite for the latest impact analysis."
)
SELECT_TOOL_SET = "select"
DESIGN = "Load the skill `test-design` and design test cases for `{scope}`."
DESIGN_DEFAULT = (
    "Load the skill `test-design` and design test cases for the impacted areas not covered by the current suite."
)
DESIGN_TOOL_SET = "design"

# Every slash command of cli.md: usage, description, and whether this build has it.
HELP = (
    ("/cycle [base] [candidate]", "Run the whole regression cycle, from the impact analysis to the completion"
     " report, one step at a time.", False),
    ("/analyze [base] [candidate]", "Compute the change set and the impact analysis. Sets the session versions when"
     " given.", True),
    ("/select", "Select and prioritize the regression suite for the current change.", True),
    ("/design [scope]", "Design test cases for the impacted areas, or for scope (requirement IDs, modules or free"
     " text).", True),
    ("/implement [ids]", "Write executable test code for designed test cases.", False),
    ("/run [target] [--on <version>]", "Execute tests. target: suite (default), all, or test case IDs separated by"
     " spaces. --on: base, candidate (default) or both.", True),
    ("/triage [run_id]", "Classify the failures of a run. Default: last run.", False),
    ("/report <type> [--run <run_id>] [--format <format>]", "Generate a report.", False),
    ("/status", "Session versions, test cases by status, the current suite, the latest run, the mode, and the model"
     " calls and tokens of the session.", True),
    ("/history [n]", "The last n runs. Default: 10.", True),
    ("/defects [--all]", "Open defects; with --all, closed ones too. /defects close <id> <reason> closes one.", False),
    ("/init", "Same as retro init: create RETRO.md, .retro/config.yaml and .retro/.gitignore when missing.", True),
    ("/model [name]", "Show the current model, or switch to profile name.", True),
    ("/mode [mode]", "Show the current permission mode, or switch to default, plan or auto.", True),
    ("/skills", "List available skills and their source.", True),
    ("/mcp", "List connected MCP servers and their tools.", True),
    ("/clear", "Clear the conversation. Project memory is not affected.", True),
    ("/help [command]", "Show help.", True),
    ("/exit", "End the session.", True),
)  # fmt: skip
COMMANDS = tuple(usage.split()[0] for usage, _, _ in HELP)
AVAILABLE = tuple(usage.split()[0] for usage, _, available in HELP if available)
MODEL_COMMANDS = ("/analyze", "/select", "/design")


class CommandError(Exception):
    """A slash command that does not exist, or was used with invalid arguments."""


class NotAvailable(CommandError):
    """A command of cli.md that this build does not have yet."""


@dataclass(frozen=True)
class Command:
    name: str  # one of COMMANDS
    target: str | tuple[str, ...] = "suite"  # /run: "suite", "all" or test case IDs
    on: str = "candidate"  # /run
    limit: int = HISTORY_DEFAULT  # /history
    argument: str | None = None  # /model, /mode, /help
    refs: tuple[str, ...] = ()  # /analyze: () or (base, candidate)
    scope: str | None = None  # /design: the words after the command, joined by one space


def is_command(line: str) -> bool:
    """Whether a line is a slash command rather than a message to the model."""
    return line.lstrip().startswith("/")


def parse(line: str) -> Command:
    """Parse one slash command. Raises ``CommandError``, or ``NotAvailable`` for a command of a later slice."""
    try:
        words = shlex.split(line)
    except ValueError as error:
        raise CommandError(str(error)) from error
    if not words or not words[0].startswith("/"):
        raise CommandError(f"not a command: {line.strip()}")
    name, args = words[0], words[1:]
    if name not in COMMANDS:
        raise CommandError(f"unknown command {name}; /help lists the commands")
    if name not in AVAILABLE:
        raise NotAvailable(f"{name} is not available yet in this build")
    if name == "/run":
        return _parse_run(args)
    if name == "/history":
        if len(args) > 1 or (args and not (args[0].isdigit() and int(args[0]) > 0)):
            raise CommandError("usage: /history [n], where n is a positive integer")
        return Command(name, limit=int(args[0]) if args else HISTORY_DEFAULT)
    if name == "/analyze":
        if len(args) not in (0, 2):
            raise CommandError("usage: /analyze [base] [candidate]: give both refs, or none")
        return Command(name, refs=tuple(args))
    if name == "/design":
        return Command(name, scope=" ".join(args) or None)
    if name in ("/model", "/mode", "/help"):
        if len(args) > 1:
            raise CommandError(f"usage: {name} [{'name' if name == '/model' else name[1:]}]")
        argument = args[0] if args else None
        if name == "/mode" and argument is not None and argument not in tools.MODES:
            raise CommandError(f"unknown mode {argument}; use one of default, plan, auto")
        return Command(name, argument=argument)
    if args:
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


def help_rows(command: str | None = None) -> list[tuple[str, str]]:
    """``/help [command]``: usage and description of every command, or of one. Raises ``CommandError``."""
    if command is not None and not command.startswith("/"):
        command = "/" + command
    rows = [
        (usage, description if available else f"{description} Not available yet in this build.")
        for usage, description, available in HELP
        if command is None or usage.split()[0] == command
    ]
    if not rows:
        raise CommandError(f"unknown command {command}; /help lists the commands")
    return rows


# /run ----------------------------------------------------------------------------------------------------------------


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
    error: ToolError | None = None  # the run_tests call that failed or was refused; no run was stored for it
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


def run(
    session: Session,
    target: str | Sequence[str] = "suite",
    on: str = "candidate",
    *,
    ask: turn.Ask | None = None,
    interrupt: threading.Event | None = None,
    listener: Callable[[object], None] | None = None,
) -> RunOutcome:
    """``/run``: one ``test_runner.run_tests`` call for each version, through the checks of the runtime and the MCP
    server. ``both`` runs the baseline first, and the candidate only when the baseline run is ``completed``."""
    if on not in ON:
        raise ValueError(f"on must be one of {', '.join(ON)}")
    if isinstance(target, str) and target in ("suite", "all"):
        arguments = {"scope": target}
    else:
        arguments = {"scope": "selected", "test_case_ids": list(target)}
    roles = ("base", "candidate") if on == "both" else (on,)
    runs: list[RunRow] = []
    for role in roles:
        if runs and runs[-1].status != "completed":
            return RunOutcome(runs, not_run=f"the candidate was not run: {runs[-1].run_id} is {runs[-1].status}")
        before = _latest_run_id(session)
        try:
            result = turn.call_tool(
                session,
                permissions.RUN_TESTS,
                {"version": role, **arguments},
                ask=ask,
                listener=listener,
                interrupt=interrupt,
            )
        except ToolError as error:
            return RunOutcome(runs, error=error)
        except turn.Interrupted:
            latest = _latest_run_id(session)
            if latest is not None and latest != before:
                runs.append(_row(session.conn, execution.get_run(session.conn, latest)))
            return RunOutcome(runs, interrupted=True)
        runs.append(_row(session.conn, execution.get_run(session.conn, result["run_id"])))
    return RunOutcome(runs)


def _latest_run_id(session: Session) -> str | None:
    rows = execution.list_runs(session.conn, 1, session_id=session.id)
    return rows[0]["id"] if rows else None


# /status and /history ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Status:
    session_id: int
    base: Version | None
    candidate: Version | None
    test_cases: dict[str, int]  # active test cases by status
    current_suite_size: int | None  # None when there is no current suite
    latest_run: RunRow | None
    mode: str = "default"
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


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
        mode=session.mode,
        model_calls=session.usage.calls,
        input_tokens=session.usage.input_tokens,
        output_tokens=session.usage.output_tokens,
    )


def history(session: Session, limit: int = HISTORY_DEFAULT) -> list[RunRow]:
    """``/history [n]``: the latest runs of the project, from every session."""
    return [_row(session.conn, row) for row in execution.list_runs(session.conn, limit)]


# Session state ------------------------------------------------------------------------------------------------------


def set_mode(session: Session, mode: str) -> None:
    """``/mode <mode>`` and Shift+Tab."""
    if mode not in tools.MODES:
        raise CommandError(f"unknown mode {mode}; use one of default, plan, auto")
    session.mode = mode


CYCLE = ("default", "plan", "auto")  # the order of Shift+Tab (cli.md, Keyboard shortcuts)


def next_mode(mode: str) -> str:
    return CYCLE[(CYCLE.index(mode) + 1) % len(CYCLE)]


def switch_model(session: Session, name: str) -> list[str]:
    """``/model <name>``. Returns the lines to show. Raises ``CommandError`` and keeps the current model."""
    try:
        return session.switch_model(name)
    except SessionError as error:
        raise CommandError(f"the model was not changed: {error}") from error


def clear(session: Session) -> None:
    """``/clear``: the conversation and the loaded skill."""
    session.conversation.clear()


@dataclass(frozen=True)
class SkillRow:
    name: str
    source: str  # bundled, user or project
    description: str


def skill_rows(session: Session) -> tuple[list[SkillRow], list[str]]:
    """``/skills``: the available skills, and the skills that were skipped with their reason."""
    rows = [SkillRow(s.name, s.level, s.description) for s in session.skills.available.values()]
    problems = [f"{p.level} skill {p.folder}: {p.reason}" for p in session.skills.problems]
    return rows, problems


def server_tools(session: Session) -> list[tuple[str, list[str]]]:
    """``/mcp``: each connected MCP server with its tools, then the tools of the runtime itself."""
    connected = session.client.tools() if session.client else {}
    rows = [(name, sorted(tool.name for tool in defined)) for name, defined in connected.items()]
    rows.append(("runtime (built in, not an MCP server)", sorted(t.name for t in session.servers()["runtime"])))
    return rows


# Model commands -----------------------------------------------------------------------------------------------------


def analyze(
    session: Session,
    refs: Sequence[str] = (),
    *,
    ask: turn.Ask | None = None,
    listener: Callable[[object], None] | None = None,
    interrupt: threading.Event | None = None,
) -> turn.TurnResult:
    """``/analyze [base] [candidate]``: an empty conversation; ``runtime.set_versions`` first when refs are given;
    then the template with the tools of the step ``analyze``. Raises ``ToolError`` when the refs do not resolve (the
    model is not called) and ``turn.TurnError``."""
    session.conversation.clear()
    if refs:
        base, candidate = refs
        turn.call_tool(session, "runtime__set_versions", {"base": base, "candidate": candidate}, ask=ask)
    return _model_command(session, ANALYZE, ANALYZE_TOOL_SET, ask=ask, listener=listener, interrupt=interrupt)


def select(
    session: Session,
    *,
    ask: turn.Ask | None = None,
    listener: Callable[[object], None] | None = None,
    interrupt: threading.Event | None = None,
) -> turn.TurnResult:
    """``/select``: an empty conversation, then the template with the tools of the step ``select``."""
    return _model_command(session, SELECT, SELECT_TOOL_SET, ask=ask, listener=listener, interrupt=interrupt)


def design_message(scope: str | None) -> str:
    """The message of ``/design [scope]``."""
    return DESIGN.format(scope=scope) if scope else DESIGN_DEFAULT


def design_tests(
    session: Session,
    scope: str | None = None,
    *,
    ask: turn.Ask | None = None,
    listener: Callable[[object], None] | None = None,
    interrupt: threading.Event | None = None,
) -> turn.TurnResult:
    """``/design [scope]``: an empty conversation, then the template with the tools of the step ``design``."""
    message = design_message(scope)
    return _model_command(session, message, DESIGN_TOOL_SET, ask=ask, listener=listener, interrupt=interrupt)


def _model_command(session: Session, message: str, tool_set: str, *, ask, listener, interrupt) -> turn.TurnResult:
    """A model command: the conversation is emptied, then one turn with the tools of the step."""
    session.conversation.clear()
    return turn.run_turn(
        session,
        message,
        provider=session.provider,
        client=session.client,
        ask=ask,
        listener=listener,
        tool_set=tool_set,
        interrupt=interrupt,
    )


# The outcome of a session, for non-interactive mode ------------------------------------------------------------------

EXIT_OK, EXIT_RUNTIME_ERROR, EXIT_USAGE, EXIT_DO_NOT_RELEASE, EXIT_DENIED = 0, 1, 2, 3, 4


@dataclass(frozen=True)
class SessionOutcome:
    runs: list[str]
    reports: list[dict]  # {"id", "path"}
    decision: str | None
    denied: int


def session_outcome(session: Session) -> SessionOutcome:
    """The runs, reports and decision of this session, and its calls refused by the mode, a permission or the
    approval of the project commands (runtime.md, Non-interactive mode)."""
    conn = session.conn
    runs = [row["id"] for row in conn.execute("SELECT id FROM run WHERE session_id = ? ORDER BY id", (session.id,))]
    row = conn.execute(
        "SELECT e.decision FROM evaluation e JOIN run r ON r.id = e.run_id WHERE r.session_id = ?"
        " ORDER BY e.id DESC LIMIT 1",
        (session.id,),
    ).fetchone()
    reports = []
    for call in conn.execute(
        "SELECT arguments FROM tool_call WHERE session_id = ? AND server = 'reports' AND tool = 'render_report'"
        " AND outcome = 'ok' ORDER BY id",
        (session.id,),
    ):
        report_id = json.loads(call["arguments"]).get("report_id")
        report = conn.execute("SELECT id, path FROM report WHERE id = ?", (report_id,)).fetchone()
        if report is not None:
            reports.append({"id": report["id"], "path": report["path"]})
    return SessionOutcome(runs, reports, row["decision"] if row else None, session.permission_refusals)


def exit_code(runtime_error: bool, summary: SessionOutcome) -> int:
    """cli.md, Exit codes: ``1``, then ``4``, then ``3``, then ``0``."""
    if runtime_error:
        return EXIT_RUNTIME_ERROR
    if summary.denied:
        return EXIT_DENIED
    if summary.decision == "do_not_release":
        return EXIT_DO_NOT_RELEASE
    return EXIT_OK
