"""What the bundled MCP servers share: tool definitions, the session context, paged output, errors and the stdio
loop (mcp-tools.md, Conventions and Errors; ADR-0026).

A server is started by the runtime for one project and one session::

    python -m retroagent.servers.<name>.server --project <dir> --session <id>

It reads the session versions, the model and the result limit from the ``session`` record on every call. A tool is
a plain function ``function(context, **arguments) -> dict``; this module validates the arguments against the schema
of the tool, calls the function and returns its result, or its ``ToolError``, in the shape of ``mcp-tools.md``.

Tool calls run in the main thread and the MCP loop runs in a background thread. When the server is asked to stop
(end of its standard input, SIGTERM or SIGINT) the call in progress receives ``ServerStopped``, a
``KeyboardInterrupt``: a run ends its process groups and is stored as ``interrupted`` before the server exits
(runtime.md, Robustness).
"""

import argparse
import json
import os
import queue
import signal
import sqlite3
import sys
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import jsonschema
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from retroagent.memory import InvariantViolation, SchemaTooNew, connect, database_path
from retroagent.servers.errors import ToolError

ROLES = ("base", "candidate")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: Mapping[str, object]  # JSON schema of the arguments, with additionalProperties false
    function: Callable[..., dict]


def schema(properties: dict | None = None, required: tuple[str, ...] = ()) -> dict:
    """The JSON schema of the arguments of a tool: no property other than those listed (mcp-tools.md)."""
    value: dict = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        value["required"] = list(required)
    return value


@dataclass(frozen=True)
class Version:
    ref: str
    commit: str


@dataclass(frozen=True)
class Context:
    """The project and the session a server was started for."""

    project_dir: Path
    session_id: int

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """A connection to project memory for one call, closed when the call ends."""
        conn = connect(self.project_dir)
        try:
            yield conn
        finally:
            conn.close()

    def session(self, conn: sqlite3.Connection) -> sqlite3.Row:
        return conn.execute("SELECT * FROM session WHERE id = ?", (self.session_id,)).fetchone()

    def versions(self, conn: sqlite3.Connection) -> dict[str, Version | None]:
        row = self.session(conn)
        return {
            role: Version(row[f"{role}_ref"], row[f"{role}_commit"]) if row[f"{role}_ref"] is not None else None
            for role in ROLES
        }

    def version(self, conn: sqlite3.Connection, role: str) -> Version:
        """A session version; ``invalid_state`` when it is not set."""
        if role not in ROLES:
            raise ToolError("invalid_argument", f"version must be base or candidate, not {role!r}")
        version = self.versions(conn)[role]
        if version is None:
            raise ToolError("invalid_state", f"the {role} version of the session is not set")
        return version

    def both_versions(self, conn: sqlite3.Connection) -> tuple[Version, Version]:
        versions = self.versions(conn)
        if versions["base"] is None or versions["candidate"] is None:
            raise ToolError("invalid_state", "the session versions are not set")
        return versions["base"], versions["candidate"]

    def result_limit(self, conn: sqlite3.Connection) -> int:
        return self.session(conn)["result_char_limit"]


def lines_of(text: str) -> list[str]:
    """The lines of ``text`` with their endings; only ``\\n`` ends a line, as in git."""
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def page(text: str, start_line: int, limit: int) -> tuple[str, dict]:
    """At most ``limit`` characters of ``text`` from ``start_line``, cut at a line boundary (mcp-tools.md, Large
    output). Returns the text and ``{truncated[, next_line][, cut_line]}``; pages joined give ``text`` back.

    A single line longer than the limit is returned cut at the limit and named in ``cut_line``.
    """
    lines = lines_of(text)
    if start_line < 1 or (start_line > len(lines) and start_line != 1):
        raise ToolError("invalid_argument", f"start_line must be between 1 and {max(len(lines), 1)}")
    index, size, taken = start_line - 1, 0, []
    while index < len(lines) and size + len(lines[index]) <= limit:
        taken.append(lines[index])
        size += len(lines[index])
        index += 1
    meta: dict = {}
    if not taken and index < len(lines):
        taken.append(lines[index][:limit])
        meta["cut_line"] = index + 1
        index += 1
    meta = {"truncated": index < len(lines) or "cut_line" in meta, **meta}
    if index < len(lines):
        meta["next_line"] = index + 1
    return "".join(taken), meta


EXPLICIT_CODES = ("invalid_argument", "invalid_state")


def tool_error(error: BaseException) -> ToolError:
    """The error code of an exception raised by a tool function (P14 of slice 3).

    A refusal of the data layer whose message starts with ``invalid_argument: `` or ``invalid_state: `` has that
    code; otherwise ``INV-13`` is ``not_found``, any other invariant ``invalid_state``, and the rest
    ``invalid_argument``.
    """
    if isinstance(error, ToolError):
        return error
    if isinstance(error, InvariantViolation | sqlite3.IntegrityError):
        message = str(error)
        code, separator, rest = message.partition(": ")
        if separator and code in EXPLICIT_CODES:
            return ToolError(code, rest)
        if message.startswith("INV-13"):
            return ToolError("not_found", message)
        if message.startswith("INV-"):
            return ToolError("invalid_state", message)
        return ToolError("invalid_argument", message)
    return ToolError("execution_failed", f"{type(error).__name__}: {error}")


def call(context: Context, tool: Tool, arguments: Mapping[str, object] | None) -> dict:
    """Validate the arguments, call the tool and return its result. Raises ``ToolError``."""
    arguments = dict(arguments or {})
    try:
        jsonschema.validate(arguments, tool.parameters)
    except jsonschema.ValidationError as error:
        where = "/".join(str(part) for part in error.absolute_path)
        raise ToolError("invalid_argument", f"{where + ': ' if where else ''}{error.message}") from None
    try:
        return tool.function(context, **arguments)
    except Exception as error:
        raise tool_error(error) from error


def result(value: dict) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(text=json.dumps(value, ensure_ascii=False))], structured_content=value
    )


def error_result(error: ToolError) -> types.CallToolResult:
    value = {"error": {"code": error.code, "message": error.message}}
    return types.CallToolResult(
        content=[types.TextContent(text=json.dumps(value, ensure_ascii=False))],
        structured_content=value,
        is_error=True,
    )


class ServerStopped(KeyboardInterrupt):
    """The server was asked to stop while a call was in progress."""

    def __init__(self):
        super().__init__("the server was stopped")


@dataclass
class _Job:
    tool: Tool
    arguments: Mapping[str, object] | None
    done: threading.Event = field(default_factory=threading.Event)
    outcome: types.CallToolResult | None = None


def serve(name: str, tools: list[Tool], argv: list[str] | None = None) -> None:
    """The entry point of a bundled server. Exits non-zero, with a message on stderr, when the project or the
    session cannot be used."""
    parser = argparse.ArgumentParser(prog=f"retroagent.servers.{name}")
    parser.add_argument("--project", required=True)
    parser.add_argument("--session", required=True, type=int)
    args = parser.parse_args(argv)
    context = Context(Path(args.project).resolve(), args.session)
    problem = _check(context)
    if problem:
        print(f"{name}: {problem}", file=sys.stderr)
        sys.exit(2)

    by_name = {tool.name: tool for tool in tools}
    jobs: queue.Queue[_Job] = queue.Queue()
    stopping = threading.Event()

    def stop(signal_number, frame):
        if stopping.is_set():
            return  # the first stop is being handled: its cleanup must not be interrupted again
        stopping.set()
        raise ServerStopped

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name=t.name, description=t.description, input_schema=dict(t.parameters)) for t in tools]
        )

    async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        tool = by_name.get(params.name)
        if tool is None:
            return error_result(ToolError("not_found", f"the {name} server has no tool {params.name!r}"))
        job = _Job(tool, params.arguments)
        jobs.put(job)
        await anyio.to_thread.run_sync(job.done.wait, abandon_on_cancel=True)
        return job.outcome

    server = Server(name, on_list_tools=list_tools, on_call_tool=call_tool)

    async def run_loop() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    main = threading.main_thread().ident

    def loop() -> None:
        try:
            anyio.run(run_loop)
        except BaseException as error:  # noqa: BLE001 - reported, then the server stops
            print(f"{name}: {type(error).__name__}: {error}", file=sys.stderr)
        finally:
            if not stopping.is_set():
                signal.pthread_kill(main, signal.SIGINT)  # end of standard input: stop the main thread

    threading.Thread(target=loop, name=f"{name}-mcp", daemon=True).start()
    try:
        while True:
            job = jobs.get()
            try:
                job.outcome = result(call(context, job.tool, job.arguments))
            except ToolError as error:
                job.outcome = error_result(error)
            job.done.set()
    except KeyboardInterrupt:
        pass
    sys.stderr.flush()
    os._exit(0)  # the loop thread may still be blocked on standard input


def _check(context: Context) -> str | None:
    if not database_path(context.project_dir).is_file():
        return f"project memory {database_path(context.project_dir)} does not exist"
    try:
        with context.connection() as conn:
            row = context.session(conn)
    except (sqlite3.Error, SchemaTooNew) as error:
        return f"project memory cannot be opened: {error}"
    if row is None:
        return f"session {context.session_id} does not exist"
    if row["ended_at"] is not None:
        return f"session {context.session_id} has ended"
    return None
