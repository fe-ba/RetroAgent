"""The MCP client: starts the bundled servers, lists their tools, calls them and stops them (ADR-0004, ADR-0026).

The runtime is synchronous; the MCP SDK is asynchronous. The client runs an event loop in a background thread
(an ``anyio`` blocking portal), with one long-lived task per server that holds its connection until ``stop()``.
Every method is called from ordinary threads, and ``stop()`` may be called while a ``call()`` waits in another one.

A server that dies, that does not answer in time or that cannot start is a ``ServerUnavailable`` error, a
``ToolError`` with code ``unavailable`` (mcp-tools.md, Errors), never a hang. A server that fails is not restarted;
a server stopped to cancel its call with ``interrupt()`` is started again (runtime.md, Interruption).
"""

import json
import sys
import tempfile
import threading
from collections.abc import Mapping, Sequence
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import IO

import anyio
import mcp.client.stdio as mcp_stdio
from anyio.from_thread import BlockingPortal, start_blocking_portal
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from retroagent.config import Config
from retroagent.llm.provider import ToolDefinition
from retroagent.servers.errors import ToolError
from retroagent.servers.test_runner.process import GRACE_SECONDS, clean_environment

BUNDLED = ("git", "memory", "test_runner")

START_TIMEOUT = 30.0  # seconds to start a server and list its tools
CALL_TIMEOUT = 120.0  # seconds for a tool call, unless the caller gives another bound
# A server stopped during a run ends the process groups of the run (up to GRACE_SECONDS each for the test command
# and the service), stores the run and removes its worktree before it exits. The SDK waits this long after closing
# its standard input before it signals it; the default of 2 seconds could cut that cleanup with a SIGKILL.
SHUTDOWN_WAIT = 2 * GRACE_SECONDS + 5.0
STDERR_LINES = 10


class ServerUnavailable(ToolError):
    def __init__(self, message: str):
        super().__init__("unavailable", message)


def bundled_command(name: str, project_dir: Path, session_id: int) -> list[str]:
    module = f"retroagent.servers.{name}.server"
    return [sys.executable, "-m", module, "--project", str(project_dir), "--session", str(session_id)]


def run_tests_timeout(config: Config) -> float:
    """The longest a ``run_tests`` call can take: setup, the test command and each rerun round, and the service."""
    rounds = (1 if config["tests.setup"] else 0) + 1 + config["tests.reruns"]
    service = config["service.ready_timeout"] if config["service.start"] else 0
    return rounds * config["tests.timeout"] + service + 60.0


class _Server:
    def __init__(self, name: str, command: Sequence[str]):
        self.name, self.command = name, list(command)
        self.stderr: IO[str] = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
        self.ready = threading.Event()
        self.session: ClientSession | None = None
        self.tools: tuple[ToolDefinition, ...] = ()
        self.failure: str | None = None
        self.stop_event: anyio.Event | None = None
        self.task: Future | None = None

    def unavailable(self, what: str) -> ServerUnavailable:
        self.failure = self.failure or what
        tail = self.stderr_tail()
        return ServerUnavailable(f"server {self.name}: {self.failure}" + (f"\n{tail}" if tail else ""))

    def stderr_tail(self) -> str:
        try:
            self.stderr.flush()
            self.stderr.seek(0)
            lines = self.stderr.read().splitlines()
        except (OSError, ValueError):
            return ""
        return "\n".join(lines[-STDERR_LINES:])


class Client:
    """The bundled servers of one project and one session."""

    def __init__(
        self,
        project_dir: str | Path,
        session_id: int,
        credential_env_names: Sequence[str] = (),
        commands: Mapping[str, Sequence[str]] | None = None,
    ):
        self.project_dir = Path(project_dir).resolve()
        self.session_id = session_id
        # The environment of retro without model credentials (configuration.md, Environment of subprocesses).
        self.environment = clean_environment(credential_env_names)
        if commands is None:
            commands = {name: bundled_command(name, self.project_dir, session_id) for name in BUNDLED}
        self._servers = {name: _Server(name, command) for name, command in commands.items()}
        self._replaced: list[_Server] = []  # servers stopped by interrupt(); their stderr is closed by stop()
        self._portal_context = None
        self._portal: BlockingPortal | None = None

    def start(self) -> None:
        """Start every server and list its tools. Raises ``ServerUnavailable`` and stops them all when one fails."""
        if self._portal is not None:
            return
        mcp_stdio.PROCESS_TERMINATION_TIMEOUT = max(mcp_stdio.PROCESS_TERMINATION_TIMEOUT, SHUTDOWN_WAIT)
        self._portal_context = start_blocking_portal()
        self._portal = self._portal_context.__enter__()
        for server in self._servers.values():
            server.task = self._portal.start_task_soon(self._hold, server)
        for server in self._servers.values():
            error = self._wait_ready(server)
            if error is not None:
                self.stop()
                raise error

    def interrupt(self, name: str) -> None:
        """Cancel the call in progress on one server: stop it, which ends the work in progress through its stop path
        (a run is stored ``interrupted``), then start it again. The cancelled ``call()`` raises ``ServerUnavailable``.
        Raises ``ServerUnavailable`` when the server does not start again."""
        old = self._servers[name]
        self._stop_server(old)
        self._replaced.append(old)
        new = _Server(name, old.command)
        self._servers[name] = new
        new.task = self._portal.start_task_soon(self._hold, new)
        error = self._wait_ready(new)
        if error is not None:
            raise error

    @staticmethod
    def _wait_ready(server: _Server) -> ServerUnavailable | None:
        if not server.ready.wait(START_TIMEOUT + 5.0) or server.session is None:
            return server.unavailable(server.failure or f"did not start within {START_TIMEOUT:.0f} seconds")
        return None

    def tools(self) -> dict[str, tuple[ToolDefinition, ...]]:
        """The tools of each server with bare names, the input of ``context.tools.tool_definitions``."""
        return {name: server.tools for name, server in self._servers.items()}

    def call(self, server: str, tool: str, arguments: Mapping[str, object] | None = None, timeout=None) -> dict:
        """Call a tool and return its result. Raises ``ToolError``: the error of the tool, or ``unavailable``."""
        target = self._servers.get(server)
        if target is None:
            raise ToolError("not_found", f"there is no server {server!r}")
        if self._portal is None or target.session is None:
            raise target.unavailable("is not running")
        try:
            result = self._portal.call(self._call, target.session, tool, dict(arguments or {}), timeout)
        except Exception as error:  # noqa: BLE001 - every failure of the connection is the same for the caller
            if isinstance(error, TimeoutError):
                failure = f"did not answer {tool} within {timeout or CALL_TIMEOUT:.0f} seconds"
            else:
                failure = f"stopped during {tool}: {type(error).__name__}: {error}".rstrip(": ")
            unavailable = target.unavailable(failure)
            self._stop_server(target)
            raise unavailable from error
        content = result.structured_content
        if content is None:
            text = "".join(getattr(block, "text", "") for block in result.content)
            content = json.loads(text) if text else {}
        if result.is_error:
            error = content.get("error", {}) if isinstance(content, dict) else {}
            raise ToolError(error.get("code", "execution_failed"), error.get("message", str(content)))
        return content

    def stop(self) -> None:
        """Stop every server: each one ends the work in progress and exits. Safe to call more than once."""
        if self._portal is None:
            return
        for server in self._servers.values():
            self._stop_server(server)
        self._portal_context.__exit__(None, None, None)
        self._portal = self._portal_context = None
        for server in (*self._servers.values(), *self._replaced):
            server.stderr.close()
        self._replaced = []

    def __enter__(self) -> "Client":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def _stop_server(self, server: _Server) -> None:
        server.session = None
        if server.stop_event is not None and self._portal is not None:
            self._portal.call(server.stop_event.set)
        if server.task is not None:
            try:
                server.task.result(timeout=SHUTDOWN_WAIT + 10.0)
            except (FutureTimeout, Exception):  # noqa: BLE001 - recorded in server.failure by _hold
                pass

    async def _hold(self, server: _Server) -> None:
        """Start one server, keep its connection until it is asked to stop, then stop it."""
        server.stop_event = anyio.Event()
        parameters = StdioServerParameters(
            command=server.command[0], args=server.command[1:], env=self.environment, cwd=str(self.project_dir)
        )
        try:
            async with stdio_client(parameters, errlog=server.stderr) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    with anyio.fail_after(START_TIMEOUT):
                        await session.initialize()
                        listed = await session.list_tools()
                    server.tools = tuple(
                        ToolDefinition(tool.name, tool.description or "", tool.input_schema) for tool in listed.tools
                    )
                    server.session = session
                    server.ready.set()
                    await server.stop_event.wait()
        except Exception as error:  # noqa: BLE001 - the caller reads it from server.failure
            if server.failure is None and not server.ready.is_set():
                server.failure = f"could not start: {_describe(error)}"
        finally:
            server.session = None
            server.ready.set()

    @staticmethod
    async def _call(session: ClientSession, tool: str, arguments: dict, timeout: float | None):
        with anyio.fail_after(timeout or CALL_TIMEOUT):
            return await session.call_tool(tool, arguments)


def _describe(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
        return _describe(error.exceptions[0])
    if isinstance(error, TimeoutError):
        return f"no answer within {START_TIMEOUT:.0f} seconds"
    return f"{type(error).__name__}: {error}"
