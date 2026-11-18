"""The turn of spec/runtime.md: from a user message to an answer of the model without tool calls.

Every iteration builds the context (system context, tool definitions of the mode and tool set, the conversation,
freed when the budget requires it, and the state message), calls the model, applies the truncation guard, and
processes the tool calls one by one in the order given: each one is recorded in ``tool_call`` before dispatch,
checked, asked about when needed, dispatched, and answered in the conversation.

The turn prints nothing. It returns a ``TurnResult`` and reports events to a listener: ``ModelCalled``,
``ToolCalled``, ``Retried``, ``Warned``, and the ``Wait`` of the provider adapter.

However the turn ends, ``recorded`` on its result or on its ``TurnError`` is computed from ``tool_call``: the write
tools that succeeded in the turn and how many times (runtime.md, Display). The answer of the model can claim an action;
``recorded`` is what was actually recorded.

``call_tool`` runs one tool call of the user, for a direct command, through the same path: recorded, checked, asked
about and dispatched, but not added to the conversation (runtime.md, Slash commands).

Interruption: the caller sets ``interrupt``, a ``threading.Event``. Model calls and tool calls of MCP servers then
run in a worker thread; the turn stops waiting for a model call, and stops the server of a tool call, which ends
its work through its stop path and is started again (runtime.md, Interruption).
"""

import dataclasses
import json
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from retroagent.config import approvals
from retroagent.context import budget, state, tools
from retroagent.llm.provider import (
    ContextWindowExceeded,
    LLMProvider,
    Message,
    ProviderError,
    Request,
    Response,
    ToolCall,
    Usage,
    request_characters,
    request_from_profile,
)
from retroagent.mcp_client import Client
from retroagent.mcp_client.client import run_tests_timeout
from retroagent.memory import design, sessions
from retroagent.runtime import permissions
from retroagent.runtime import tools as runtime_tools
from retroagent.runtime.permissions import ApprovalRequest, PermissionRequest
from retroagent.runtime.session import CommandsState, Session
from retroagent.servers.errors import ToolError
from retroagent.servers.test_runner import generated
from retroagent.servers.test_runner.process import WELL_KNOWN_KEYS

BRIEFLY = (
    "Your previous answer was cut at the output limit before its tool calls were complete, and it was discarded."
    " Answer again more briefly: fewer tool calls in one answer, and shorter arguments."
)
NOT_COMPLETED = "not completed: interrupted by the user"
SECRET = "***"
POLL_SECONDS = 0.05

# Asks the user: a permission, answered with one of ``permissions.ANSWERS``, or the approval of the project commands,
# answered with one of ``permissions.APPROVAL_ANSWERS``.
Ask = Callable[[PermissionRequest | ApprovalRequest], str]


# Events -------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelCalled:
    iteration: int  # model calls of this turn so far, this one included
    characters: int  # characters sent
    usage: Usage | None
    seconds: float
    finish_reason: str
    thinking: str | None  # shown in verbose mode, never kept in the conversation


@dataclass(frozen=True)
class ToolCalled:
    name: str  # exposed name, normalized
    arguments: str  # as recorded: secret values replaced
    outcome: str  # ok, error or denied
    code: str | None  # error code of mcp-tools.md
    seconds: float


@dataclass(frozen=True)
class Retried:
    reason: str  # context_window_exceeded or length


@dataclass(frozen=True)
class Warned:
    message: str


# Results ------------------------------------------------------------------------------------------------------------


# The write tools that succeeded in a turn, by exposed name, with how many times, in the order of the first success.
Recorded = tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class TurnResult:
    text: str
    incomplete: bool = False  # the answer was cut by the output limit
    limit_reached: bool = False  # agent.max_iterations was reached
    interrupted: bool = False
    recorded: Recorded = ()


class TurnError(Exception):
    """A runtime error that ends the turn. ``ends_session`` when the session must not continue: the model did not
    receive the whole context (the truncation guard)."""

    def __init__(self, message: str, *, ends_session: bool = False):
        super().__init__(message)
        self.ends_session = ends_session
        self.recorded: Recorded = ()  # set by run_turn


class Interrupted(Exception):
    """The user interrupted a tool call of a direct command; the call is recorded as not completed."""


class _LimitReached(Exception):
    pass


def limit_message(calls: int) -> str:
    return (
        f"The turn stopped after {calls} model calls, the limit set by agent.max_iterations. The work done is in"
        " project memory; send a message to continue."
    )


def call_tool(
    session: Session,
    name: str,
    arguments: Mapping[str, object],
    *,
    ask: Ask | None,
    client: Client | None = None,
    listener: Callable[[object], None] | None = None,
    interrupt: threading.Event | None = None,
) -> object:
    """A tool call of the user, for a direct command: the checks of a free message (no tool set), the question when
    the permission is ``ask``, the dispatch and the ``tool_call`` row. Returns the result of the tool. Raises
    ``ToolError``, or ``Interrupted`` when ``interrupt`` is set during the call."""
    turn = _Turn(session, None, client or session.client, ask, listener, None, None, interrupt)
    turn.by_user = True
    call = ToolCall(id="user", name=name, arguments=dict(arguments))
    outcome, code, result = turn.run_call(call, deferred=False)
    if code is not None:
        raise ToolError(code, result["error"]["message"])
    return result


def run_turn(
    session: Session,
    message: str,
    *,
    provider: LLMProvider,
    client: Client,
    ask: Ask | None,
    listener: Callable[[object], None] | None = None,
    tool_set: str | None = None,
    cycle_step: state.CycleStep | None = None,
    interrupt: threading.Event | None = None,
) -> TurnResult:
    """Run one turn of the session on ``message``. ``ask`` asks the user about a permission and returns one of
    ``permissions.ANSWERS``; None in non-interactive mode. ``tool_set`` is a key of ``context.tools.TOOL_SETS``,
    or None for a free message. Raises ``TurnError``."""
    previous = session.listener
    session.listener = listener
    before = sessions.last_tool_call_id(session.conn, session.id)
    try:
        result = _Turn(session, provider, client, ask, listener, tool_set, cycle_step, interrupt).run(message)
    except TurnError as error:
        error.recorded = recorded_since(session, before)
        raise
    finally:
        session.listener = previous
    return dataclasses.replace(result, recorded=recorded_since(session, before))


def recorded_since(session: Session, after_id: int) -> Recorded:
    """The write tools of the calls after ``after_id`` whose outcome is ``ok``, counted. A refused call, a call that
    failed and a call left not completed are not counted."""
    counts: dict[str, int] = {}
    for row in sessions.succeeded_tool_calls(session.conn, session.id, after_id):
        name = f"{row['server']}{tools.SEPARATOR}{row['tool']}"
        if name in tools.WRITE_TOOLS:
            counts[name] = counts.get(name, 0) + 1
    return tuple(counts.items())


class _Turn:
    def __init__(self, session, provider, client, ask, listener, tool_set, cycle_step, interrupt):
        self.session, self.provider, self.client, self.ask = session, provider, client, ask
        self.report = listener or (lambda event: None)
        self.tool_set, self.cycle_step = tool_set, cycle_step
        self.interrupt = interrupt
        self.by_user = False  # a direct command of the user, which may call the user-only tools
        self.calls = 0
        self.secrets = secret_values(session.config.credential_env_names)

    # The loop -------------------------------------------------------------------------------------------------------

    def run(self, message: str) -> TurnResult:
        conversation = self.session.conversation
        conversation.messages.append(Message(role="user", content=message))
        system_context = self.session.system_context()  # RETRO.md is read once per turn
        while True:
            try:
                response, variable_space = self._model_step(system_context)
            except Interrupted:
                return TurnResult("", interrupted=True)
            except _LimitReached:
                return TurnResult(limit_message(self.calls), limit_reached=True)
            # Thinking is never kept in the conversation.
            conversation.messages.append(
                Message(role="assistant", content=response.text, tool_calls=response.tool_calls)
            )
            if not response.tool_calls:
                return TurnResult(response.text, incomplete=response.finish_reason == "length")
            if not self._tool_calls(response.tool_calls, variable_space):
                return TurnResult("", interrupted=True)
            if self.calls >= self.session.config["agent.max_iterations"]:
                return TurnResult(limit_message(self.calls), limit_reached=True)

    # The model call -------------------------------------------------------------------------------------------------

    def _model_step(self, system_context: str) -> tuple[Response, int]:
        """One model call with the two retries of the turn. Returns the response and the variable space."""
        free, briefly = False, False
        while True:
            if self.calls >= self.session.config["agent.max_iterations"]:
                raise _LimitReached
            request, variable_space = self._request(system_context, force_free=free, briefly=briefly)
            self.calls += 1
            started = time.monotonic()
            try:
                response = self._wait(lambda request=request: self.provider.complete(request))
            except ContextWindowExceeded as error:
                if free:
                    raise TurnError(f"The context is still too long after freeing it: {error}") from error
                free = True
                self.report(Retried("context_window_exceeded"))
                continue
            except ProviderError as error:
                raise TurnError(str(error)) from error
            self._after(request, response, time.monotonic() - started)
            if response.finish_reason == "length" and response.tool_calls:
                if briefly:
                    raise TurnError(
                        "The answer of the model was cut by max_output_tokens twice before its tool calls were"
                        " complete. Raise max_output_tokens in the model profile."
                    )
                briefly = True
                self.report(Retried("length"))
                continue
            return response, variable_space

    def _request(self, system_context: str, *, force_free: bool, briefly: bool) -> tuple[Request, int]:
        session = self.session
        definitions = session.definitions(self.tool_set)
        state_message = session.state_message(self.cycle_step)
        ratio = session.calibration.ratio
        fixed = budget.estimate(budget.fixed_characters(system_context, definitions, state_message), ratio)
        variable_space = session.budget.variable_space(fixed)
        conversation = session.conversation
        try:
            freed = budget.free_context(
                conversation.messages,
                variable_space=variable_space,
                ratio=ratio,
                loaded_skill_call=conversation.loaded_skill_call,
                force=force_free,
            )
        except budget.ContextFull as error:
            raise TurnError(f"{error} Use /clear to start a new conversation.") from error
        conversation.messages = list(freed)
        if briefly:  # for this request only; never stored
            state_message = Message(role="user", content=f"{state_message.content}\n\n{BRIEFLY}")
        messages = state.call_messages(system_context, conversation.messages, state_message)
        return request_from_profile(session.profile, messages, definitions), variable_space

    def _after(self, request: Request, response: Response, seconds: float) -> None:
        session = self.session
        session.usage.calls += 1
        if response.usage is not None:
            session.usage.input_tokens += response.usage.input_tokens
            session.usage.output_tokens += response.usage.output_tokens
        elif not session.warned_no_usage:
            session.warned_no_usage = True
            self.report(Warned(budget.NO_USAGE_WARNING))
        characters = request_characters(request)
        self.report(
            ModelCalled(self.calls, characters, response.usage, seconds, response.finish_reason, response.thinking)
        )
        try:
            session.calibration = budget.after_call(session.calibration, request, response, session.budget.window)
        except budget.TruncationDetected as error:
            raise TurnError(str(error), ends_session=True) from error

    # Tool calls -----------------------------------------------------------------------------------------------------

    def _tool_calls(self, calls: Sequence[ToolCall], variable_space: int) -> bool:
        """Process the tool calls of one model message, in order. False when the user interrupted them."""
        results = 0  # characters of the results of this model message
        for index, call in enumerate(calls):
            if self.interrupt is not None and self.interrupt.is_set():
                self._not_completed(calls[index:])
                return False
            deferred = budget.defer_remaining(results, variable_space, self.session.calibration.ratio)
            try:
                content = self._tool_call(call, deferred)
            except Interrupted:
                self._not_completed(calls[index + 1 :])
                return False
            results += len(content)
        return True

    def _tool_call(self, call: ToolCall, deferred: bool) -> str:
        """Run the call and answer it in the conversation. Returns the content added to the conversation. Raises
        ``Interrupted`` after answering the call as not completed."""
        try:
            _, _, result = self.run_call(call, deferred)
        except Interrupted:
            self._add_result(call, NOT_COMPLETED)
            raise
        content = result if isinstance(result, str) else _json(result)
        self._add_result(call, content)
        return content

    def run_call(self, call: ToolCall, deferred: bool) -> tuple[str, str | None, object]:
        """Record, check, ask, dispatch and record the outcome. Returns the outcome, the error code and the result,
        which is the error object of mcp-tools.md when there is a code. Raises ``Interrupted`` after recording the
        call as not completed."""
        name, server, tool = _names(call.name)
        recorded = self._recorded_arguments(call)
        row = sessions.start_tool_call(
            self.session.conn, session_id=self.session.id, server=server, tool=tool, arguments=recorded
        )
        started = time.monotonic()
        outcome, code, result = "ok", None, None
        try:
            result = self._decide_and_dispatch(call, name, server, tool, deferred)
        except ToolError as error:
            code = error.code
            outcome = "denied" if code == "denied" else "error"
            result = {"error": {"code": code, "message": error.message}}
        except Interrupted:
            self._finish(row, name, recorded, "error", None, NOT_COMPLETED, time.monotonic() - started)
            raise
        if code is not None:
            error = f"{code}: {result['error']['message']}"
        elif outcome == "error":
            error = result if isinstance(result, str) else _json(result)
        else:
            error = None
        self._finish(row, name, recorded, outcome, code, error, time.monotonic() - started)
        return outcome, code, result

    def _recorded_arguments(self, call: ToolCall) -> str:
        arguments = call.invalid_arguments if call.invalid_arguments is not None else _json(dict(call.arguments))
        return self._redact(arguments)

    def _finish(self, row, name, recorded, outcome, code, error, seconds) -> None:
        sessions.finish_tool_call(
            self.session.conn, row, outcome=outcome, error=self._redact(error) if error is not None else None
        )
        self.report(ToolCalled(name, recorded, outcome, code, seconds))

    def _add_result(self, call: ToolCall, content: str) -> None:
        self.session.conversation.messages.append(Message(role="tool", content=content, tool_call_id=call.id))

    def _not_completed(self, calls: Sequence[ToolCall]) -> None:
        """The calls after an interrupted one: recorded and answered as not completed, so every call has a result."""
        for call in calls:
            name, server, tool = _names(call.name)
            recorded = self._recorded_arguments(call)
            row = sessions.start_tool_call(
                self.session.conn, session_id=self.session.id, server=server, tool=tool, arguments=recorded
            )
            self._finish(row, name, recorded, "error", None, NOT_COMPLETED, 0.0)
            self._add_result(call, NOT_COMPLETED)

    def _decide_and_dispatch(self, call: ToolCall, name: str, server: str, tool: str, deferred: bool):
        session = self.session
        if deferred:
            raise ToolError(
                "deferred",
                "the results of this answer already fill their share of the context; the call was not executed:"
                " call it again in your next step",
            )
        if call.invalid_arguments is not None:
            raise ToolError("invalid_argument", f"the arguments are not a valid JSON object: {call.invalid_arguments}")
        # The project commands are read again before every run: the content checked is the content the run reads.
        commands = session.commands_state() if name == permissions.RUN_TESTS else None
        config = commands.config if commands is not None and commands.config is not None else session.config
        decision = permissions.check(
            name,
            known=session.known_tools(),
            tool_set=self.tool_set,
            mode=session.mode,
            permissions=session.permissions(),
            service_configured=bool(config["service.start"]),
            commands_approved=commands is None or commands.ready,
            by_user=self.by_user,
        )
        if decision.action == "refuse":
            if decision.reason in permissions.PERMISSION_REFUSALS:
                session.permission_refusals += 1
            raise ToolError(decision.code, decision.message)
        if commands is not None and commands.config_error is not None:
            raise ToolError("invalid_state", f"the configuration cannot be read: {commands.config_error}")
        if decision.approve_commands:
            self._approve(commands)
        if decision.action == "ask":
            self._ask(name, call.arguments, decision.permissions, config)
        if server == tools.RUNTIME:
            return runtime_tools.call(session, tool, call.arguments, call.id)
        timeout = run_tests_timeout(session.config) if name == permissions.RUN_TESTS else None
        return self._wait(
            lambda: self.client.call(server, tool, call.arguments, timeout),
            on_interrupt=lambda: self._interrupt_server(server),
        )

    def _approve(self, commands: CommandsState) -> None:
        """Ask the user to approve the project commands in their current content, and store the approval (runtime.md,
        Project commands). Raises ``ToolError`` ``denied`` when there is no one to ask, the user does not approve, or
        ``approvals.json`` cannot be read."""
        session = self.session
        if commands.approvals_error is not None:
            session.permission_refusals += 1
            raise ToolError("denied", f"{permissions.PROJECT_COMMANDS} cannot be checked: {commands.approvals_error}")
        if self.ask is None:
            session.permission_refusals += 1
            raise ToolError("denied", permissions.COMMANDS_NOT_APPROVED)
        values = approvals.project_commands(commands.config)
        env = values.pop("tests.env") or {}
        request = ApprovalRequest(
            project=str(session.project_dir),
            commands=tuple((key, value) for key, value in values.items()),
            env=tuple((str(key), str(value)) for key, value in env.items()),
            stored_in=str(approvals.approvals_path()),
        )
        answer = self.ask(request)
        if answer not in permissions.APPROVAL_ANSWERS:
            raise ValueError(f"the answer to an approval is one of {', '.join(permissions.APPROVAL_ANSWERS)}")
        if answer != permissions.APPROVE:
            session.permission_refusals += 1
            raise ToolError("denied", permissions.COMMANDS_REFUSED)
        try:
            approvals.store(session.project_dir, commands.digest)
        except approvals.ApprovalsError as error:
            session.permission_refusals += 1
            raise ToolError("denied", f"the approval was not stored: {error}") from error

    def _ask(self, name: str, arguments: Mapping[str, object], asked: tuple[str, ...], config) -> None:
        if self.ask is None:
            self.session.permission_refusals += 1
            raise ToolError("denied", permissions.no_one_to_ask(asked))
        answer = self.ask(PermissionRequest(name, asked, self._details(name, arguments, config)))
        if answer not in permissions.ANSWERS:
            raise ValueError(f"the answer to a permission is one of {', '.join(permissions.ANSWERS)}, not {answer!r}")
        if answer == permissions.DENY:
            self.session.permission_refusals += 1
            raise ToolError("denied", permissions.refused_by_user(asked))
        if answer == permissions.SESSION:
            self.session.grants.update(asked)

    def _details(self, name: str, arguments: Mapping[str, object], config) -> tuple[str, ...]:
        if name == permissions.WRITE_TEST:
            return permissions.write_test_details(arguments, self._previous_code(arguments))
        session = self.session
        role = arguments.get("version")
        version = session.versions().get(role) if role in ("base", "candidate") else None
        described = f"{role} {version.ref} ({version.commit})" if version else f"{role} (not set)"
        return permissions.run_tests_details(
            arguments, version=described, test_cases=self._test_cases(arguments), config=config
        )

    def _previous_code(self, arguments: Mapping[str, object]) -> tuple[int, str] | None:
        """The revision and the code of a generated test that a ``write_test`` call rewrites; None for a first
        write, or when the code cannot be read (the server then decides the call)."""
        test_case_id = arguments.get("test_case_id")
        row = design.get_test_case(self.session.conn, test_case_id) if isinstance(test_case_id, str) else None
        if row is None or row["origin"] != "designed" or row["status"] != "implemented":
            return None
        try:
            path = generated.target(self.session.project_dir, row["implementation"].rpartition("::")[0])
            code = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        except (generated.GeneratedError, OSError):
            return None
        return row["revision"], code

    def _test_cases(self, arguments: Mapping[str, object]) -> str:
        """How many test cases the scope of a ``run_tests`` call has, from project memory."""
        scope, conn = arguments.get("scope"), self.session.conn
        if scope == "selected":
            return str(len(arguments.get("test_case_ids") or []))
        if scope == "all":
            known = sum(design.count_active_test_cases(conn).values())
            return f"every test of the project; {known} test cases are known"
        versions = self.session.versions()
        if versions["base"] is None or versions["candidate"] is None:
            return "no current suite: the session versions are not set"
        suite_id = design.current_suite(conn, versions["base"].commit, versions["candidate"].commit)
        if suite_id is None:
            return "no current suite"
        rows = design.suite_test_cases(conn, suite_id)
        return str(sum(1 for row in rows if row["status"] == "implemented"))

    def _interrupt_server(self, server: str) -> None:
        try:
            self.client.interrupt(server)
        except ToolError as error:
            self.report(Warned(f"the server {server} did not start again after the interruption: {error.message}"))

    # Waiting with interruption --------------------------------------------------------------------------------------

    def _wait(self, function: Callable[[], object], on_interrupt: Callable[[], None] | None = None):
        """Run ``function`` and return its result. With an ``interrupt`` event, it runs in a worker thread: when the
        event is set first, ``on_interrupt`` runs, the worker is waited for when there is an ``on_interrupt`` and
        abandoned otherwise, and ``Interrupted`` is raised."""
        if self.interrupt is None:
            return function()
        if self.interrupt.is_set():
            raise Interrupted
        outcome: dict = {}
        done = threading.Event()

        def work() -> None:
            try:
                outcome["value"] = function()
            except BaseException as error:  # noqa: BLE001 - raised again in the waiting thread
                outcome["error"] = error
            finally:
                done.set()

        threading.Thread(target=work, name="retro-turn-call", daemon=True).start()
        while not done.wait(POLL_SECONDS):
            if self.interrupt.is_set():
                if on_interrupt is not None:
                    on_interrupt()
                    done.wait()
                raise Interrupted
        if "error" in outcome:
            raise outcome["error"]
        return outcome["value"]

    def _redact(self, text: str) -> str:
        return redact(text, self.secrets)


def secret_values(credential_names: Sequence[str]) -> tuple[str, ...]:
    """The values of the known secret variables: those removed from every subprocess (configuration.md, Environment
    of subprocesses), as set now."""
    names = dict.fromkeys((*WELL_KNOWN_KEYS, *credential_names))
    return tuple(value for name in names if (value := os.environ.get(name)))


def redact(text: str, secrets: Sequence[str]) -> str:
    """``text`` with every secret value, and its form inside a JSON string, replaced by ``***``."""
    for secret in sorted(secrets, key=len, reverse=True):
        for form in dict.fromkeys((secret, json.dumps(secret)[1:-1])):
            text = text.replace(form, SECRET)
    return text


def _names(raw: str) -> tuple[str, str, str]:
    """The exposed name, the server and the tool of a name given by the model. A name that is not of the form
    ``<server>__<tool>`` has an empty server."""
    try:
        name = tools.normalize(raw)
        server, tool = tools.split(name)
    except ValueError:
        return raw, "", raw
    return name, server, tool


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)
