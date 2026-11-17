"""Modes and permissions of spec/runtime.md: the order of the checks, the two tables, the question to the user, the
session grants, and the approval of the project commands.

``check`` decides a tool call before dispatch. It reads nothing and asks nothing: the turn asks the user to approve
the project commands when the decision says ``approve_commands``, asks about the permissions when the decision is
``ask``, and stores a grant when the answer is ``session``.
"""

import difflib
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

# The approval of the project commands (runtime.md, Project commands): approve, which is stored, or deny.
APPROVE = "approve"
APPROVAL_ANSWERS = (APPROVE, DENY)

PROJECT_COMMANDS = "the project commands (tests.setup, tests.command, tests.select, service.start and tests.env)"
COMMANDS_NOT_APPROVED = (
    f"{PROJECT_COMMANDS} are not approved in their current content, and there is no one to ask in non-interactive"
    " mode; approve them in an interactive session, or start the session with --trust-commands"
)
COMMANDS_REFUSED = f"the user did not approve {PROJECT_COMMANDS}"


# Why a call is refused. Only the refusals of the mode, of a permission and of the approval of the project commands
# make the exit code 4 and are counted in ``denied`` (cli.md, Exit codes); the model can correct the others.
NOT_FOUND, USER_ONLY_TOOL, NOT_IN_STEP = "not_found", "user_only", "not_in_step"
BY_MODE, BY_PERMISSION, BY_APPROVAL = "mode", "permission", "approval"
PERMISSION_REFUSALS = frozenset({BY_MODE, BY_PERMISSION, BY_APPROVAL})


@dataclass(frozen=True)
class Decision:
    """``run``, ``ask`` (the permissions to ask for), or a refusal with its error code, message and reason."""

    action: str  # run, ask, refuse
    permissions: tuple[str, ...] = ()
    code: str | None = None  # not_found or denied
    message: str | None = None
    reason: str | None = None  # a refusal: one of the reasons above
    approve_commands: bool = False  # the project commands must be approved before the question and the dispatch


RUN = Decision("run")


def refuse(code: str, message: str, reason: str) -> Decision:
    return Decision("refuse", code=code, message=message, reason=reason)


@dataclass(frozen=True)
class PermissionRequest:
    """What the user is asked: the tool, the permissions it needs, and what will happen."""

    tool: str
    permissions: tuple[str, ...]
    details: tuple[str, ...]


@dataclass(frozen=True)
class ApprovalRequest:
    """The approval of the project commands: every command and every variable of ``tests.env``, in full. Answered
    with one of ``APPROVAL_ANSWERS``."""

    project: str
    commands: tuple[tuple[str, str | None], ...]  # (key, command), None when not set
    env: tuple[tuple[str, str], ...]  # tests.env
    stored_in: str  # where an approval is stored

    @property
    def details(self) -> tuple[str, ...]:
        return (
            f"Project: {self.project}",
            "They run on this machine with your privileges; RetroAgent is not a sandbox.",
            *(f"  {key}: {command if command is not None else '(not set)'}" for key, command in self.commands),
            "  tests.env:" + ("" if self.env else " (none)"),
            *(f"    {name}={value}" for name, value in self.env),
            f"An approval is stored in {self.stored_in}; a command that changes is asked again.",
        )


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
    by_user: bool = False,
) -> Decision:
    """Decide a tool call, in the order of runtime.md: the tool exists, is not user only, is in the tool set of the
    step, is allowed by the mode and is not ``deny``; then the approval of the project commands; then the question.
    A ``run_tests`` whose commands are not approved is flagged ``approve_commands``, whatever the mode: the turn asks
    for the approval, or refuses the call when there is no one to ask.

    ``known`` holds the exposed name of every existing tool; ``permissions`` the effective value of each permission.
    ``by_user`` is a call of the runtime for a direct command of the user, the only caller of a user-only tool.
    """
    if name not in known:
        return refuse("not_found", f"there is no tool {name}", NOT_FOUND)
    if name in USER_ONLY and not by_user:
        return refuse("denied", f"{name} is called only by the user, with a direct command", USER_ONLY_TOOL)
    if tool_set is not None and not in_tool_set(name, STEP_TOOLS[tool_set]):
        has = ", ".join(step_tools(known, mode=mode, tool_set=tool_set))
        return refuse("denied", f"{name} is not a tool of the step {tool_set}; this step has: {has}", NOT_IN_STEP)
    required = needed(name, service_configured)
    if not required:
        return RUN
    if mode == PLAN:
        message = f"plan mode does not allow {name}: it needs the permission {' and '.join(required)}"
        return refuse("denied", message, BY_MODE)
    denied = [p for p in required if permissions[p] == DENY]
    if denied:
        return refuse("denied", f"the permission {' and '.join(denied)} is deny", BY_PERMISSION)
    approve = name == RUN_TESTS and not commands_approved
    to_ask = tuple(p for p in required if permissions[p] == ASK)
    if to_ask and mode != AUTO:
        return Decision("ask", permissions=to_ask, approve_commands=approve)
    return Decision("run", approve_commands=approve)


def no_one_to_ask(permissions: tuple[str, ...]) -> str:
    return (
        f"the permission {' and '.join(permissions)} is ask, and there is no one to ask in non-interactive mode;"
        " use --mode auto or set the permission to allow"
    )


def refused_by_user(permissions: tuple[str, ...]) -> str:
    return f"the user denied the permission {' and '.join(permissions)}"


def write_test_details(arguments: Mapping[str, object], previous: tuple[int, str] | None = None) -> tuple[str, ...]:
    """What ``test_runner.write_test`` will do: the file, the test and the full code; in a rewrite, ``previous`` is
    the revision and the code written now, and the question shows the difference with it (ADR-0024)."""
    file, code = arguments.get("file"), str(arguments.get("code", ""))
    lines = [
        f"Test case: {arguments.get('test_case_id')}",
        f"File: .retro/tests/{file}",
        f"Test: {arguments.get('test_name')}",
    ]
    if previous is None:
        return (*lines, "Code:", code)
    revision, current = previous
    diff = difflib.unified_diff(
        current.splitlines(keepends=True),
        code.splitlines(keepends=True),
        fromfile=f"{file} (revision {revision})",
        tofile=f"{file} (revision {revision + 1})",
    )
    text = "".join(line if line.endswith("\n") else line + "\n" for line in diff).rstrip("\n")
    lines.append(f"Rewrite: revision {revision + 1}. Changes to the code:")
    lines.append(text or "(the code does not change)")
    fields = arguments.get("fields")
    if isinstance(fields, Mapping) and fields:
        lines.append(f"Design fields that change with it: {', '.join(sorted(map(str, fields)))}")
    return tuple(lines)


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
