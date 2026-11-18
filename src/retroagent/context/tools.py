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

# The tools whose access is write (mcp-tools.md, Summary); every other tool only reads.
WRITE_TOOLS = frozenset({
    "runtime__set_versions",
    "git__analyze_changes",
    "memory__sync_requirements", "memory__save_impact", "memory__add_risk", "memory__save_suite",
    "memory__design_test_case", "memory__update_test_case", "memory__retire_test_case", "memory__save_triage",
    "memory__register_defect", "memory__link_defect", "memory__close_defect",
    "test_runner__write_test", "test_runner__run_tests",
    "reports__evaluate", "reports__prepare_report", "reports__render_report",
})  # fmt: skip

# The read tools of the cycle steps: the tools of runtime and every tool of git and memory whose access is read
# (runtime.md, Cycle command).
READ_TOOLS: tuple[str, ...] = (
    "runtime",
    "git__resolve_ref", "git__get_diff", "git__read_file", "git__list_files",
    "memory__get_requirements", "memory__get_analysis", "memory__get_risks", "memory__get_suite",
    "memory__get_test_cases", "memory__get_runs", "memory__get_executions", "memory__get_test_case_history",
    "memory__get_defects",
)  # fmt: skip

# The tools exposed by each model step of /cycle and by the model command of the same skill (runtime.md, Cycle
# command): the read tools and the write tools of the step, so that a step never redoes or undoes another one. An
# entry is a server, meaning all its tools, or one tool. A free message exposes every tool the mode allows.
TOOL_SETS: Mapping[str, tuple[str, ...]] = {
    "analyze": (
        *READ_TOOLS, "memory__sync_requirements", "git__analyze_changes", "memory__save_impact", "memory__add_risk"
    ),
    "select": (*READ_TOOLS, "memory__save_suite", "test_runner__run_tests"),
    "design": (*READ_TOOLS, "memory__design_test_case", "memory__update_test_case", "memory__retire_test_case"),
    "implement": (
        *READ_TOOLS, "test_runner__write_test", "test_runner__get_evidence", "memory__update_test_case",
        "memory__retire_test_case",
    ),
    "triage": (
        *READ_TOOLS, "test_runner__get_evidence", "memory__save_triage", "memory__register_defect",
        "memory__link_defect",
    ),
    "report": (*READ_TOOLS, "reports"),
}  # fmt: skip


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
