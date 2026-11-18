"""Modes and permissions of runtime.md as a decision: both tables, per mode, and the order of the checks.

The rows of ``test_runner.run_tests`` also run through the turn in ``tests/integration/test_turn_permissions.py``,
and the approval of the project commands in ``tests/integration/test_sc03_approval.py``.
"""

import pytest

from retroagent.runtime import permissions
from retroagent.runtime.permissions import RUN_TESTS, WRITE_TEST, check, needed

KNOWN = {
    RUN_TESTS,
    WRITE_TEST,
    "git__resolve_ref",
    "git__analyze_changes",
    "memory__get_suite",
    "memory__close_defect",
    "runtime__load_skill",
}
PERMISSION_KEYS = ("run_tests", "write_tests", "start_service")


def decide(
    name, *, mode="default", value="allow", values=None, service=False, approved=True, tool_set=None, by_user=False
):
    effective = dict.fromkeys(PERMISSION_KEYS, value) | (values or {})
    return check(
        name,
        known=KNOWN,
        tool_set=tool_set,
        mode=mode,
        permissions=effective,
        service_configured=service,
        commands_approved=approved,
        by_user=by_user,
    )


# The first table: the permission each tool needs.


def test_write_test_needs_write_tests():
    assert needed(WRITE_TEST, service_configured=True) == ("write_tests",)


def test_run_tests_needs_run_tests_and_start_service_when_a_service_is_configured():
    assert needed(RUN_TESTS, service_configured=False) == ("run_tests",)
    assert needed(RUN_TESTS, service_configured=True) == ("run_tests", "start_service")


@pytest.mark.parametrize("name", ["git__resolve_ref", "memory__get_suite", "runtime__load_skill"])
@pytest.mark.parametrize("mode", ["default", "auto", "plan"])
@pytest.mark.parametrize("value", ["allow", "ask", "deny"])
def test_every_other_tool_needs_no_permission_and_runs_in_every_mode(name, mode, value):
    assert needed(name, service_configured=True) == ()
    assert decide(name, mode=mode, value=value) == permissions.RUN


# The second table: mode by effective value, for each tool that needs a permission.

TABLE = {
    ("default", "allow"): "run",
    ("default", "ask"): "ask",
    ("default", "deny"): "refuse",
    ("auto", "allow"): "run",
    ("auto", "ask"): "run",
    ("auto", "deny"): "refuse",
    ("plan", "allow"): "refuse",
    ("plan", "ask"): "refuse",
    ("plan", "deny"): "refuse",
}


@pytest.mark.parametrize(("mode", "value"), list(TABLE))
@pytest.mark.parametrize(("name", "service"), [(WRITE_TEST, False), (RUN_TESTS, False), (RUN_TESTS, True)])
def test_mode_and_permission_table(mode, value, name, service):
    decision = decide(name, mode=mode, value=value, service=service)
    assert decision.action == TABLE[(mode, value)]
    if decision.action == "refuse":
        assert decision.code == "denied"
    if decision.action == "ask":
        assert decision.permissions == needed(name, service)


def test_plan_mode_names_the_permission_the_tool_needs():
    decision = decide(WRITE_TEST, mode="plan")
    assert decision.message == f"plan mode does not allow {WRITE_TEST}: it needs the permission write_tests"


# run_tests with two permissions.


@pytest.mark.parametrize(
    ("values", "action", "named"),
    [
        ({"run_tests": "allow", "start_service": "deny"}, "refuse", "start_service"),
        ({"run_tests": "deny", "start_service": "allow"}, "refuse", "run_tests"),
        ({"run_tests": "deny", "start_service": "ask"}, "refuse", "run_tests"),  # a refusal never asks
        ({"run_tests": "allow", "start_service": "ask"}, "ask", ("start_service",)),
        ({"run_tests": "ask", "start_service": "ask"}, "ask", ("run_tests", "start_service")),
    ],
)
def test_run_tests_with_a_service_combines_both_permissions(values, action, named):
    decision = decide(RUN_TESTS, values=values, service=True)
    assert decision.action == action
    if action == "refuse":
        assert decision.message == f"the permission {named} is deny"
    else:
        assert decision.permissions == named  # one question names both


# The order of the checks.


def test_a_tool_that_does_not_exist_is_not_found():
    decision = decide("git__nothing")
    assert (decision.action, decision.code) == ("refuse", "not_found")


def test_a_user_only_tool_is_denied_in_every_mode():
    for mode in ("default", "auto", "plan"):
        decision = decide("memory__close_defect", mode=mode)
        assert (decision.code, decision.message) == (
            "denied",
            "memory__close_defect is called only by the user, with a direct command",
        )


def test_the_user_calls_a_user_only_tool_in_every_mode():
    """``/defects close`` calls memory.close_defect through the runtime; plan mode allows it (mcp-tools.md)."""
    for mode in ("default", "auto", "plan"):
        assert decide("memory__close_defect", mode=mode, by_user=True).action == "run"


def test_a_tool_outside_the_step_is_denied_and_the_message_names_the_tools_of_the_step():
    decision = decide("git__analyze_changes", tool_set="triage")
    assert decision.code == "denied"
    assert decision.message == (
        "git__analyze_changes is not a tool of the step triage; this step has: git__resolve_ref, memory__get_suite,"
        " runtime__load_skill"
    )


def test_the_tools_of_a_step_in_plan_mode_leave_out_the_tools_that_need_a_permission():
    decision = decide("git__analyze_changes", mode="plan", tool_set="implement")
    assert "test_runner" not in decision.message
    assert permissions.step_tools(KNOWN, mode="plan", tool_set="select") == [
        "git__resolve_ref",
        "memory__get_suite",
        "runtime__load_skill",
    ]
    assert RUN_TESTS in permissions.step_tools(KNOWN, mode="default", tool_set="select")


def test_the_mode_is_checked_before_deny_and_the_approval():
    decision = decide(RUN_TESTS, mode="plan", value="deny", approved=False)
    assert decision.message.startswith("plan mode does not allow")


def test_deny_is_checked_before_the_approval_of_the_project_commands():
    decision = decide(RUN_TESTS, value="deny", approved=False)
    assert decision.message == "the permission run_tests is deny"


@pytest.mark.parametrize(
    ("mode", "value", "action"), [("default", "ask", "ask"), ("default", "allow", "run"), ("auto", "ask", "run")]
)
def test_run_tests_without_approved_commands_needs_the_approval_first_whatever_the_mode(mode, value, action):
    """The approval does not depend on the mode or on permissions.*: auto never approves the commands."""
    decision = decide(RUN_TESTS, mode=mode, value=value, approved=False)
    assert (decision.action, decision.approve_commands) == (action, True)


@pytest.mark.parametrize("mode", ["default", "auto"])
def test_run_tests_with_approved_commands_needs_no_approval(mode):
    assert decide(RUN_TESTS, mode=mode, approved=True).approve_commands is False


def test_write_test_does_not_need_the_approval_of_the_project_commands():
    assert decide(WRITE_TEST, approved=False) == permissions.RUN


def test_the_approval_shows_every_command_and_variable_in_full():
    request = permissions.ApprovalRequest(
        project="/work/shop",
        commands=(("tests.setup", "make deps"), ("tests.command", "pytest --junitxml={junit}"), ("tests.select", None)),
        env=(("SHOP_MODE", "test"),),
        stored_in="/home/me/.retro/approvals.json",
    )
    assert request.details == (
        "Project: /work/shop",
        "They run on this machine with your privileges; RetroAgent is not a sandbox.",
        "  tests.setup: make deps",
        "  tests.command: pytest --junitxml={junit}",
        "  tests.select: (not set)",
        "  tests.env:",
        "    SHOP_MODE=test",
        "An approval is stored in /home/me/.retro/approvals.json; a command that changes is asked again.",
    )


def test_the_question_of_a_rewrite_shows_the_difference_with_the_current_code():
    arguments = {"test_case_id": "TC-027", "file": "test_a.py", "test_name": "test_a", "code": "x = 1\ny = 3\n"}
    details = permissions.write_test_details(arguments, (1, "x = 1\ny = 2\n"))
    assert details[:4] == (
        "Test case: TC-027",
        "File: .retro/tests/test_a.py",
        "Test: test_a",
        "Rewrite: revision 2. Changes to the code:",
    )
    assert details[4].splitlines() == [
        "--- test_a.py (revision 1)",
        "+++ test_a.py (revision 2)",
        "@@ -1,2 +1,2 @@",
        " x = 1",
        "-y = 2",
        "+y = 3",
    ]
    first = permissions.write_test_details(arguments)
    assert first[3:] == ("Code:", "x = 1\ny = 3\n")


# Effective values and session grants.


def config(**values):
    """A configuration with only the keys the permissions read."""
    return {f"permissions.{key}": value for key, value in values.items()}


def test_the_effective_value_is_the_configuration_and_a_grant_is_allow():
    configured = config(run_tests="ask", write_tests="deny", start_service="ask")
    assert permissions.effective(configured, set()) == {
        "run_tests": "ask",
        "write_tests": "deny",
        "start_service": "ask",
    }
    assert permissions.effective(configured, {"run_tests", "start_service"}) == {
        "run_tests": "allow",
        "write_tests": "deny",
        "start_service": "allow",
    }


def test_the_question_describes_the_code_of_write_test():
    details = permissions.write_test_details(
        {"test_case_id": "TC-027", "file": "test_req_002.py", "test_name": "test_req_002_x", "code": "def t(): ..."}
    )
    assert details == (
        "Test case: TC-027",
        "File: .retro/tests/test_req_002.py",
        "Test: test_req_002_x",
        "Code:",
        "def t(): ...",
    )


def test_the_question_describes_the_commands_of_run_tests():
    configured = {
        "tests.setup": "make venv",
        "tests.command": "pytest --junitxml={junit}",
        "tests.select": "pytest -k '{names}' --junitxml={junit}",
        "service.start": "serve --port {port}",
    }
    common = {"version": "base v1.0 (c7d45ad)", "test_cases": "3", "config": configured}
    suite = permissions.run_tests_details({"scope": "suite"}, **common)
    assert suite == (
        "Version: base v1.0 (c7d45ad)",
        "Scope: suite",
        "Test cases: 3",
        "Commands:",
        "  setup: make venv",
        "  tests: pytest -k '{names}' --junitxml={junit}",
        "  service: serve --port {port}",
    )
    assert "  tests: pytest --junitxml={junit}" in permissions.run_tests_details({"scope": "all"}, **common)
