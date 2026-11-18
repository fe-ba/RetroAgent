"""The session in the terminal: a line is a slash command or a message to the model (cli.md, runtime.md).

``Shell.handle`` answers one line and is shared by the interactive session and non-interactive mode (``-p``). In an
interactive session, while a turn or a command runs, a watcher thread reads the keys: ``Esc`` and ``Ctrl+C`` interrupt
it, and a permission question is answered with ``1``, ``2`` or ``3`` (``Esc`` and ``Ctrl+C`` deny). At the prompt,
``Shift+Tab`` cycles the modes, ``Ctrl+C`` twice and ``Ctrl+D`` exit. In non-interactive mode there is no one to ask,
and ``SIGINT`` interrupts.
"""

import contextlib
import queue
import select
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass

from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from retroagent.cli import display, tables
from retroagent.llm.provider import ProviderError
from retroagent.runtime import commands, init, permissions, turn
from retroagent.runtime.commands import Command, CommandError, RunOutcome
from retroagent.runtime.session import Session
from retroagent.servers.errors import ToolError

KEY_POLL_SECONDS = 0.05  # also the time after which a lone Esc is taken as the Esc key


def run_failed(outcome: RunOutcome) -> bool:
    """Whether ``/run`` is a runtime error (cli.md, Exit codes): a tool error other than a refusal, an interruption,
    or a run that is not ``completed``. Failed tests in a completed run are not an error."""
    if outcome.error is not None and outcome.error.code != "denied":
        return True
    return outcome.interrupted or any(row.status != "completed" for row in outcome.runs)


@dataclass
class Outcome:
    """What one line did."""

    answer: str | None = None  # the final answer of the model
    recorded: turn.Recorded | None = None  # what the turn of the model recorded; None when no turn ran
    runtime_error: bool = False
    usage_error: bool = False
    end: bool = False  # the session must end


Work = Callable[[turn.Ask | None, threading.Event], object]


class Shell:
    """Answers lines of one session. ``keys`` is the terminal of an interactive session, None in ``-p``. ``out``
    receives answers and tables, and the recorded line after every turn of the model unless ``show_recorded`` is false;
    ``log`` the lines of the turn; ``err`` errors and warnings."""

    def __init__(
        self,
        session: Session,
        out: Console,
        err: Console,
        *,
        log: Console | None = None,
        verbose: bool = False,
        keys: "Keys | None" = None,
        confirm: Callable[[str], bool] | None = None,
        render_markdown: bool = True,
        show_recorded: bool = True,
    ):
        self.session, self.out, self.err, self.log = session, out, err, log or out
        self.verbose, self.keys, self.confirm = verbose, keys, confirm
        self.render_markdown, self.show_recorded = render_markdown, show_recorded

    # Lines --------------------------------------------------------------------------------------------------------

    def handle(self, line: str) -> Outcome:
        if not line.strip():
            return Outcome()
        if not commands.is_command(line):
            return self._model(lambda ask, interrupt: turn.run_turn(
                self.session, line, provider=self.session.provider, client=self.session.client, ask=ask,
                listener=self._listener, interrupt=interrupt,
            ))  # fmt: skip
        try:
            command = commands.parse(line)
        except CommandError as error:
            self._error(str(error))
            return Outcome(usage_error=True)
        return self.execute(command)

    def execute(self, command: Command) -> Outcome:
        name = command.name
        if name == "/exit":
            return Outcome(end=True)
        if name == "/analyze":
            return self._model(lambda ask, interrupt: commands.analyze(
                self.session, command.refs, ask=ask, listener=self._listener, interrupt=interrupt
            ))  # fmt: skip
        if name == "/select":
            return self._model(lambda ask, interrupt: commands.select(
                self.session, ask=ask, listener=self._listener, interrupt=interrupt
            ))  # fmt: skip
        if name == "/design":
            return self._model(lambda ask, interrupt: commands.design_tests(
                self.session, command.scope, ask=ask, listener=self._listener, interrupt=interrupt
            ))  # fmt: skip
        if name == "/implement":
            return self._model(lambda ask, interrupt: commands.implement(
                self.session, command.ids, ask=ask, listener=self._listener, interrupt=interrupt
            ))  # fmt: skip
        if name == "/triage":
            try:
                run_id = commands.triage_run(self.session, command.run_id)
            except CommandError as error:
                self._error(str(error))
                return Outcome(usage_error=True)
            return self._model(lambda ask, interrupt: commands.triage(
                self.session, run_id, ask=ask, listener=self._listener, interrupt=interrupt
            ))  # fmt: skip
        if name == "/run":
            return self._run(command)
        try:
            self._direct(command)
        except CommandError as error:
            self._error(str(error))
            return Outcome(usage_error=True)
        return Outcome()

    def _direct(self, command: Command) -> None:
        session, out, name = self.session, self.out, command.name
        if name == "/status":
            for table in tables.status_tables(commands.status(session)):
                out.print(table)
        elif name == "/history":
            out.print(tables.history_table(commands.history(session, command.limit)))
        elif name == "/defects":
            self._defects(command)
        elif name == "/clear":
            commands.clear(session)
            self._say("The conversation is cleared. Project memory is not affected.")
        elif name == "/mode":
            if command.argument is not None:
                commands.set_mode(session, command.argument)
            self._say(f"Mode: {session.mode}")
        elif name == "/model":
            if command.argument is None:
                self._say(f"Model profile: {session.profile_name}. {session.statement}")
                self._say(f"Profiles: {', '.join(sorted(session.config.models))}")
            else:
                for line in commands.switch_model(session, command.argument):
                    self._say(line)
        elif name == "/skills":
            rows, problems = commands.skill_rows(session)
            table = Table(title="Skills")
            for column in ("Skill", "Source", "Description"):
                table.add_column(column, overflow="fold")
            for row in rows:
                table.add_row(Text(row.name), Text(row.source), Text(row.description))
            out.print(table)
            for problem in problems:
                self._error(f"skipped: {problem}")
        elif name == "/mcp":
            table = Table(title="MCP servers")
            table.add_column("Server", overflow="fold")
            table.add_column("Tools", overflow="fold")
            for server, names in commands.server_tools(session):
                table.add_row(Text(server), Text(", ".join(names)))
            out.print(table)
        elif name == "/help":
            table = Table(show_header=False, box=None)
            for usage, description in commands.help_rows(command.argument):
                table.add_row(Text(usage), Text(description))
            out.print(table)
            if command.argument is None:
                self._say("Any other line is a message to the model.")
        elif name == "/init":
            self._init()
        else:
            raise ValueError(f"not a direct command: {name}")

    def _defects(self, command: Command) -> None:
        if command.defect_id is None:
            rows = commands.defects(self.session, command.include_closed)
            if rows:
                self.out.print(tables.defects_table(rows, include_closed=command.include_closed))
            else:
                self._say("No defects." if command.include_closed else "No open defects.")
            return
        try:
            commands.close_defect(self.session, command.defect_id, command.reason)
        except ToolError as error:
            raise CommandError(str(error)) from error
        self._say(f"{command.defect_id} is closed by the user: {command.reason}")

    def _init(self) -> None:
        project_dir = self.session.project_dir
        proposal = init.propose(project_dir)
        for line in init.describe(proposal):
            self._say(line)
        missing = [name for name in init.FILES if not (project_dir / name).exists()]
        if not missing:
            self._say(f"Nothing to create: {', '.join(init.FILES)} exist and are kept.")
            return
        if self.confirm is not None and not self.confirm(f"Create {', '.join(missing)}?"):
            self._say("Nothing was created.")
            return
        created, kept = init.write(project_dir, proposal)
        self._say(f"Created: {', '.join(created)}." + (f" Kept: {', '.join(kept)}." if kept else ""))
        self._say("The new configuration applies from the next session; RETRO.md is read at the next turn.")

    def _run(self, command: Command) -> Outcome:
        outcome = self.perform(
            lambda ask, interrupt: commands.run(
                self.session, command.target, command.on, ask=ask, interrupt=interrupt, listener=self._listener
            )
        )
        if outcome.runs:
            self.out.print(tables.runs_table(outcome.runs))
        for row in outcome.runs:
            if row.closed_defects:
                self._say(f"{row.run_id} closed {', '.join(row.closed_defects)}.")
        for row in outcome.runs:
            if row.error:
                self._error(f"{row.run_id}: {row.error}")
        if outcome.not_run:
            self._error(outcome.not_run)
        if outcome.interrupted:
            self._error("interrupted by the user")
        if outcome.error is not None:
            self._error(str(outcome.error))
        return Outcome(runtime_error=run_failed(outcome))

    def _model(self, work: Work) -> Outcome:
        try:
            result = self.perform(work)
        except ToolError as error:  # runtime.set_versions of /analyze: the model was not called
            self._error(str(error))
            return Outcome(usage_error=True)
        except turn.TurnError as error:
            self._error(str(error))
            if error.ends_session:
                self._error("The session ends: the model did not receive the whole context.")
            self._recorded(error.recorded)
            return Outcome(runtime_error=True, end=error.ends_session, recorded=error.recorded)
        except ProviderError as error:
            self._error(str(error))
            return Outcome(runtime_error=True)
        if result.interrupted:
            self._error("Interrupted. The results of completed tool calls stay in the conversation.")
            self._recorded(result.recorded)
            return Outcome(runtime_error=True, recorded=result.recorded)
        if result.limit_reached:
            self._error(result.text)
            self._recorded(result.recorded)
            return Outcome(answer=result.text, runtime_error=True, recorded=result.recorded)
        if self.render_markdown:
            self.out.print(Markdown(result.text))
        else:
            self.out.print(result.text, markup=False, highlight=False, soft_wrap=True)
        if result.incomplete:
            self._error("warning: the answer was cut at max_output_tokens of the model profile.")
        self._recorded(result.recorded)
        return Outcome(answer=result.text, recorded=result.recorded)

    def _recorded(self, recorded: turn.Recorded) -> None:
        if self.show_recorded:
            self._say(display.recorded_line(recorded))

    # Doing work that can be interrupted ----------------------------------------------------------------------------

    def perform(self, work: Work):
        """Run ``work(ask, interrupt)`` in this thread. Interactive: while the keys are watched. Non-interactive: with
        no one to ask, and ``SIGINT`` sets the interrupt."""
        interrupt = threading.Event()
        if self.keys is not None:
            return self.keys.watch(work, interrupt, self.out)
        previous = None
        if threading.current_thread() is threading.main_thread():
            previous = signal.signal(signal.SIGINT, lambda number, frame: interrupt.set())
        try:
            return work(None, interrupt)
        finally:
            if previous is not None:
                signal.signal(signal.SIGINT, previous)

    def _listener(self, event: object) -> None:
        line = display.event_line(event, self.verbose)
        if line is not None:
            self.log.print(line, style="dim", markup=False, highlight=False)

    def _say(self, text: str) -> None:
        self.out.print(text, markup=False, highlight=False)

    def _error(self, text: str) -> None:
        self.err.print(text, markup=False, highlight=False)


class Keys:
    """The terminal of an interactive session while work runs. The work runs in the calling thread, which owns the
    connection to project memory; a watcher thread reads the keys: ``Esc`` and ``Ctrl+C`` set the interrupt, and a
    question of the work is shown and answered there. ``input`` is a prompt_toolkit input."""

    def __init__(self, input):
        self.input = input

    def watch(self, work: Work, interrupt: threading.Event, out: Console):
        questions: queue.Queue = queue.Queue()
        stop = threading.Event()
        watcher = threading.Thread(
            target=self._watch, args=(questions, interrupt, stop, out), name="retro-keys", daemon=True
        )

        def ask(request: permissions.PermissionRequest | permissions.ApprovalRequest) -> str:
            reply: queue.Queue = queue.Queue(maxsize=1)
            questions.put((request, reply))
            while True:
                with contextlib.suppress(queue.Empty):
                    return reply.get(timeout=KEY_POLL_SECONDS)
                if not watcher.is_alive():  # no one can answer any more
                    return permissions.DENY

        watcher.start()
        try:
            return work(ask, interrupt)
        finally:
            stop.set()
            watcher.join()

    def _watch(self, questions: queue.Queue, interrupt: threading.Event, stop: threading.Event, out: Console) -> None:
        from prompt_toolkit.keys import Keys as Key

        pending = None
        with self.input.raw_mode():
            while not stop.is_set():
                if pending is None:
                    with contextlib.suppress(queue.Empty):
                        pending = questions.get_nowait()
                        out.print(display.question(pending[0]), markup=False, highlight=False)
                for press in self._read():
                    if pending is not None:
                        answer = _answer(press.key, Key, pending[0])
                        if answer is not None:
                            out.print(display.answer_line(answer, pending[0]), markup=False, highlight=False)
                            pending[1].put(answer)
                            pending = None
                    elif press.key in (Key.Escape, Key.ControlC) and not interrupt.is_set():
                        out.print("Interrupting...", style="dim")
                        interrupt.set()

    def _read(self) -> list:
        """The keys pressed within ``KEY_POLL_SECONDS``. A lone Esc is taken as the key when nothing follows it."""
        ready, _, _ = select.select([self.input.fileno()], [], [], KEY_POLL_SECONDS)
        if ready:
            return self.input.read_keys()
        return self.input.flush_keys()


def _answer(key, Key, request) -> str | None:
    if key in (Key.Escape, Key.ControlC):
        return permissions.DENY
    for choice, value, _ in display.choices(request):
        if key == choice:
            return value
    return None


# The prompt ---------------------------------------------------------------------------------------------------------


def prompt_session(session: Session, input=None, output=None):
    """The prompt: shows the mode; ``Shift+Tab`` cycles it."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings

    bindings = KeyBindings()

    @bindings.add("s-tab")
    def _cycle(event) -> None:
        commands.set_mode(session, commands.next_mode(session.mode))
        event.app.invalidate()

    return PromptSession(message=lambda: f"retro ({session.mode})> ", key_bindings=bindings, input=input, output=output)


def loop(shell: Shell, read_line: Callable[[], str]) -> None:
    """Read and answer lines until ``/exit``, ``Ctrl+D``, ``Ctrl+C`` twice in a row at the prompt, or an error that
    ends the session."""
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
            shell.err.print("Press Ctrl+C again to exit.")
            continue
        interrupts = 0
        if shell.handle(line).end:
            return


def choose_profile(names: list[str], read_line: Callable[[str], str], err: Console) -> str | None:
    """No model is set: the user chooses one of the profiles of the user configuration, for this session."""
    err.print("No model is set. Choose a model profile for this session:", markup=False)
    for number, name in enumerate(names, 1):
        err.print(f"  {number}. {name}", markup=False, highlight=False)
    while True:
        try:
            answer = read_line("Profile (number or name): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if answer in names:
            choice = answer
        elif answer.isdigit() and 1 <= int(answer) <= len(names):
            choice = names[int(answer) - 1]
        else:
            continue
        err.print(f"To use it by default, set model: {choice} in ~/.retro/config.yaml.", markup=False)
        return choice
