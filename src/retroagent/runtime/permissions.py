"""Modes and permissions of spec/runtime.md: the order of the checks, the two tables, the question to the user and
the session grants.

``check`` decides a tool call before dispatch. It reads nothing and asks nothing: the turn asks the user when the
decision is ``ask``, and stores a grant when the answer is ``session``.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from retroagent.config import Config
from retroagent.context.state import PERMISSION_KEYS
from retroagent.context.tools import PERMISSIONS, PLAN, SERVICE_PERMISSION, USER_ONLY, in_tool_set
from retroagent.context.tools import TOOL_SETS as STEP_TOOLS

ALLOW, ASK, DENY = "allow", "ask", "deny"
AUTO = "auto"
RUN_TESTS, WRITE_TEST = "test_runner__run_tests", "test_runner__write_test"

# Answers to the question: allow once, allow for the rest of the session, or deny.
ONCE, SESSION = "once", "session"
ANSWERS = (ONCE, SESSION, DENY)

COMMANDS_NOT_APPROVED = (
    "the project commands (tests.setup, tests.command, tests.select, service.start and tests.env) are not approved;"
    " start the session with --trust-commands to approve them for this session"
)


@dataclass(frozen=True)
class Decision:
    """``run``, ``ask`` (the permissions to ask for), or a refusal with its error code and message."""

    action: str  # run, ask, refuse
    permissions: tuple[str, ...] = ()
    code: str | None = None  # not_found or denied
    message: str | None = None


RUN = Decision("run")


def refuse(code: str, message: str) -> Decision:
    return Decision("refuse", code=code, message=message)


@dataclass(frozen=True)
class PermissionRequest:
    """What the user is asked: the tool, the permissions it needs, and what will happen."""

    tool: str
    permissions: tuple[str, ...]
    details: tuple[str, ...]


def needed(name: str, service_configured: bool) -> tuple[str, ...]:
    """The permissions a tool needs (the first table of runtime.md)."""
    if name not in PERMISSIONS:
        return ()
    if name == RUN_TESTS and service_configured:
        return (PERMISSIONS[name], SERVICE_PERMISSION)
    return (PERMISSIONS[name],)


def effective(config: Config, grants: Collection[str]) -> dict[str, str]:
    """The value of each permission in this session: the configuration, and ``allow`` for a session grant."""
    return {key: ALLOW if key in grants else config[f"permissions.{key}"] for key in PERMISSION_KEYS}


def step_tools(known: Collection[str], *, mode: str, tool_set: str | None) -> list[str]:
    """The tools the model has in this step and mode: those of its tool definitions."""
    return sorted(
        name
        for name in known
        if name not in USER_ONLY
        and (tool_set is None or in_tool_set(name, STEP_TOOLS[tool_set]))
        and not (mode == PLAN and name in PERMISSIONS)
    )


def check(
    name: str,
    *,
    known: Collection[str],
    tool_set: str | None,
    mode: str,
    permissions: Mapping[str, str],
    service_configured: bool,
    commands_approved: bool,
) -> Decision:
    """Decide a tool call, in the order of runtime.md: the tool exists, is not user only, is in the tool set of the
    step, is allowed by the mode and is not ``deny``; then the approval of the project commands; then the question.

    ``known`` holds the exposed name of every existing tool; ``permissions`` the effective value of each permission.
    """
    if name not in known:
        return refuse("not_found", f"there is no tool {name}")
    if name in USER_ONLY:
        return refuse("denied", f"{name} is called only by the user, with a direct command")
    if tool_set is not None and not in_tool_set(name, STEP_TOOLS[tool_set]):
        has = ", ".join(step_tools(known, mode=mode, tool_set=tool_set))
        return refuse("denied", f"{name} is not a tool of the step {tool_set}; this step has: {has}")
    required = needed(name, service_configured)
    if not required:
        return RUN
    if mode == PLAN:
        return refuse("denied", f"plan mode does not allow {name}: it needs the permission {' and '.join(required)}")
    denied = [p for p in required if permissions[p] == DENY]
    if denied:
        return refuse("denied", f"the permission {' and '.join(denied)} is deny")
    if name == RUN_TESTS and not commands_approved:
        return refuse("denied", COMMANDS_NOT_APPROVED)
    to_ask = tuple(p for p in required if permissions[p] == ASK)
    if to_ask and mode != AUTO:
        return Decision("ask", permissions=to_ask)
    return RUN


def no_one_to_ask(permissions: tuple[str, ...]) -> str:
    return (
        f"the permission {' and '.join(permissions)} is ask, and there is no one to ask in non-interactive mode;"
        " use --mode auto or set the permission to allow"
    )


def refused_by_user(permissions: tuple[str, ...]) -> str:
    return f"the user denied the permission {' and '.join(permissions)}"


def write_test_details(arguments: Mapping[str, object]) -> tuple[str, ...]:
    """What ``test_runner.write_test`` will do: the file, the test and the full code."""
    return (
        f"Test case: {arguments.get('test_case_id')}",
        f"File: .retro/tests/{arguments.get('file')}",
        f"Test: {arguments.get('test_name')}",
        "Code:",
        str(arguments.get("code", "")),
    )


def run_tests_details(
    arguments: Mapping[str, object], *, version: str, test_cases: str, config: Config
) -> tuple[str, ...]:
    """What ``test_runner.run_tests`` will do: the version, the scope, the number of test cases and the commands.

    ``version`` describes the session version (ref and commit); ``test_cases`` how many test cases the scope has.
    """
    scope = arguments.get("scope")
    if scope == "all" or not config["tests.select"]:
        test_command = config["tests.command"]
    else:
        test_command = config["tests.select"]
    commands = [("setup", config["tests.setup"]), ("tests", test_command), ("service", config["service.start"])]
    return (
        f"Version: {version}",
        f"Scope: {scope}",
        f"Test cases: {test_cases}",
        "Commands:",
        *(f"  {label}: {command}" for label, command in commands if command),
    )
