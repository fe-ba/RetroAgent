"""The interactive prompt of this build: only the direct commands ``/run``, ``/status``, ``/history``, ``/help`` and
``/exit``. Any other input is answered with a message that it is not available yet."""

from collections.abc import Callable

from rich.console import Console
from rich.table import Table

from retroagent.cli import tables
from retroagent.runtime import commands
from retroagent.runtime.commands import Command, CommandError, RunOutcome
from retroagent.runtime.session import Session

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_DENIED = 4

PROMPT = "retro> "


def exit_code(outcome: RunOutcome) -> int:
    """Exit code of ``/run`` (cli.md, Exit codes): a refused call is 4; another tool error, an interruption or a run
    that is not ``completed`` is 1. Failed tests in a completed run are 0: ``/run`` produces no decision."""
    if outcome.error is not None:
        return EXIT_DENIED if outcome.error.code == "denied" else EXIT_RUNTIME_ERROR
    if outcome.interrupted or any(row.status != "completed" for row in outcome.runs):
        return EXIT_RUNTIME_ERROR
    return EXIT_OK


def execute(session: Session, command: Command, out: Console, err: Console) -> int:
    """Run one direct command and show its result. Returns its exit code."""
    if command.name == "/run":
        outcome = commands.run(session, command.target, command.on)
        if outcome.runs:
            out.print(tables.runs_table(outcome.runs))
        for row in outcome.runs:
            if row.error:
                err.print(f"{row.run_id}: {row.error}", markup=False, highlight=False)
        if outcome.not_run:
            err.print(outcome.not_run, markup=False, highlight=False)
        if outcome.interrupted:
            err.print("interrupted by the user", markup=False, highlight=False)
        if outcome.error is not None:
            err.print(str(outcome.error), markup=False, highlight=False)
            if outcome.error.code == "denied":
                err.print("start the session with --trust-commands to approve the project commands", markup=False)
        return exit_code(outcome)
    if command.name == "/status":
        for table in tables.status_tables(commands.status(session)):
            out.print(table)
        return EXIT_OK
    if command.name == "/history":
        out.print(tables.history_table(commands.history(session, command.limit)))
        return EXIT_OK
    if command.name == "/help":
        table = Table(show_header=False, box=None)
        for usage, description in commands.HELP:
            table.add_row(usage, description)
        out.print(table)
        return EXIT_OK
    raise ValueError(f"not a command to execute: {command.name}")


def loop(session: Session, read_line: Callable[[], str], out: Console, err: Console) -> None:
    """Read and answer lines until ``/exit``, end of input, or Ctrl+C twice in a row at the prompt."""
    interrupts = 0
    while True:
        try:
            line = read_line()
        except EOFError:
            return
        except KeyboardInterrupt:
            interrupts += 1
            if interrupts >= 2:
                return
            err.print("Press Ctrl+C again to exit.")
            continue
        interrupts = 0
        if not handle(session, line, out, err):
            return


def handle(session: Session, line: str, out: Console, err: Console) -> bool:
    """Answer one line. False when the session must end."""
    if not line.strip():
        return True
    try:
        command = commands.parse(line)
    except CommandError as error:
        err.print(str(error), markup=False, highlight=False)
        if not line.lstrip().startswith("/") or str(error).startswith("not available yet"):
            err.print(f"Available: {', '.join(commands.COMMANDS)}.", markup=False, highlight=False)
        return True
    if command.name == "/exit":
        return False
    execute(session, command, out, err)
    return True


def prompt_reader() -> Callable[[], str]:
    from prompt_toolkit import PromptSession

    prompt = PromptSession()
    return lambda: prompt.prompt(PROMPT)
