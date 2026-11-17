"""Tool definitions for a mode and a tool set (spec/context-loading.md, Tool definitions; spec/runtime.md).

The servers report their tools with bare names; the model sees ``<server>__<tool>``, because some providers do not
accept dots in tool names. The reference documentation writes ``<server>.<tool>``; a call written that way is
accepted and normalized.
"""

from collections.abc import Mapping, Sequence

from retroagent.llm.provider import ToolDefinition

SEPARATOR = "__"
RUNTIME = "runtime"
MODES = ("default", "auto", "plan")
PLAN = "plan"

# The tools that need a permission, and the permission each one always needs (runtime.md, Modes and permissions).
# test_runner.run_tests also needs start_service when service.start is configured. Every other tool needs none.
PERMISSIONS: Mapping[str, str] = {
    "test_runner__write_test": "write_tests",
    "test_runner__run_tests": "run_tests",
}
SERVICE_PERMISSION = "start_service"

# Called only by the runtime, for a direct command of the user; never in the tool definitions (mcp-tools.md).
USER_ONLY = frozenset({"memory__close_defect"})

# The tools exposed by each model step of /cycle and by the model command of the same skill (runtime.md, Cycle
# command). An entry is a server, meaning all its tools, or one tool. A free message exposes every tool.
TOOL_SETS: Mapping[str, tuple[str, ...]] = {
    "analyze": ("runtime", "git", "memory"),
    "select": ("runtime", "git", "memory", "test_runner__run_tests"),
    "design": ("runtime", "git", "memory"),
    "implement": ("runtime", "git", "memory", "test_runner__write_test", "test_runner__get_evidence"),
    "triage": ("runtime", "git", "memory", "test_runner__get_evidence"),
    "report": ("runtime", "memory", "reports"),
}


def exposed_name(server: str, tool: str) -> str:
    if not server or not tool or SEPARATOR in server or "." in server or "." in tool:
        raise ValueError(f"invalid server or tool name: {server!r}, {tool!r}")
    return f"{server}{SEPARATOR}{tool}"


def normalize(name: str) -> str:
    """The exposed name of a tool named by the model: ``<server>.<tool>`` becomes ``<server>__<tool>``."""
    if SEPARATOR not in name and "." in name:
        server, tool = name.split(".", 1)
        return exposed_name(server, tool)
    return name


def split(name: str) -> tuple[str, str]:
    """``(server, tool)`` of an exposed or documented tool name."""
    server, separator, tool = normalize(name).partition(SEPARATOR)
    if not separator or not server or not tool:
        raise ValueError(f"{name!r} is not a tool name of the form <server>__<tool>")
    return server, tool


def in_tool_set(name: str, entries: Sequence[str]) -> bool:
    return name in entries or split(name)[0] in entries


def tool_definitions(
    servers: Mapping[str, Sequence[ToolDefinition]], *, mode: str, tool_set: str | None = None
) -> tuple[ToolDefinition, ...]:
    """The definitions sent to the model, sorted by exposed name.

    ``servers`` maps each server, ``runtime`` included, to its tools with bare names. ``tool_set`` is a key of
    ``TOOL_SETS``, or None for a free message. User-only tools are never exposed; in plan mode, neither are the tools
    that need a permission.
    """
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    entries = TOOL_SETS[tool_set] if tool_set is not None else None
    selected: dict[str, ToolDefinition] = {}
    for server, tools in servers.items():
        for tool in tools:
            name = exposed_name(server, tool.name)
            if name in selected:
                raise ValueError(f"tool {name} is defined twice")
            if name in USER_ONLY or (mode == PLAN and name in PERMISSIONS):
                continue
            if entries is not None and not in_tool_set(name, entries):
                continue
            selected[name] = ToolDefinition(name=name, description=tool.description, parameters=tool.parameters)
    return tuple(selected[name] for name in sorted(selected))
