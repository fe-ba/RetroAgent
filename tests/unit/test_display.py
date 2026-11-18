"""The lines shown for the events of a turn, in normal and verbose mode, and the question of a permission."""

import pytest

from retroagent.cli import display
from retroagent.llm.provider import ProviderNotice, Usage, Wait
from retroagent.runtime.permissions import PermissionRequest
from retroagent.runtime.turn import ModelCalled, Retried, ToolCalled, Warned

MODEL = ModelCalled(2, 41_230, Usage(10_400, 230), 2.13, "tool_calls", None)
TOOL_OK = ToolCalled("git__get_diff", '{"path": "src/shop/pricing.py"}', "ok", None, 0.31)
TOOL_ERROR = ToolCalled("git__get_diff", '{"path": "nowhere.py"}', "error", "not_found", 0.05)
DENIED = ToolCalled("test_runner__run_tests", '{"version": "base", "scope": "all"}', "denied", "denied", 0.0)


@pytest.mark.parametrize(
    "event, verbose, line",
    [
        (TOOL_OK, False, "git__get_diff: ok"),
        (TOOL_ERROR, False, "git__get_diff: error not_found"),
        (DENIED, False, "test_runner__run_tests: denied denied"),
        (TOOL_OK, True, 'tool git__get_diff {"path": "src/shop/pricing.py"}: ok, 0.3 s'),
        (TOOL_ERROR, True, 'tool git__get_diff {"path": "nowhere.py"}: error not_found, 0.1 s'),
        (MODEL, False, None),
        (MODEL, True,
         "model call 2: 41,230 characters sent, 10,400 input and 230 output tokens, 2.1 s, finish tool_calls"),
        (ModelCalled(1, 900, None, 1.0, "stop", "Let me think."), True,
         "model call 1: 900 characters sent, usage not reported, 1.0 s, finish stop\n  thinking: Let me think."),
        (Retried("context_window_exceeded"), True,
         "retry: the provider refused the context as too long; freeing context and calling again"),
        (Retried("length"), True,
         "retry: the answer was cut at max_output_tokens before its tool calls were complete;"
         " asking for a shorter one"),
        (Retried("length"), False, None),
        (Wait("rate_limit", 1, 4.0), True, "wait 4.0 s: rate limited by the provider, retry 1"),
        (Wait("unavailable", 2, 8.0), True, "wait 8.0 s: the provider is unavailable, retry 2"),
        (Wait("pacing", 0, 3.25), True, "wait 3.2 s: pacing under requests_per_minute"),
        (Wait("pacing", 0, 3.25), False, None),
        (ProviderNotice("Deprecated: temperature"), True, "provider notice: Deprecated: temperature"),
        (ProviderNotice("Deprecated: temperature"), False, None),
        (Warned("the provider reports no usage"), False, "warning: the provider reports no usage"),
    ],
)  # fmt: skip
def test_event_lines(event, verbose, line):
    assert display.event_line(event, verbose) == line


def test_long_arguments_are_cut_in_verbose_mode():
    arguments = '{"code": "' + "x" * 1000 + '"}'
    line = display.event_line(ToolCalled("test_runner__write_test", arguments, "ok", None, 0.2), True)
    assert line == f"tool test_runner__write_test {arguments[:300]}... (1,012 characters): ok, 0.2 s"


def test_the_permission_question_shows_the_details_and_the_three_answers():
    request = PermissionRequest(
        "test_runner__run_tests", ("run_tests", "start_service"), ("Version: base v1.0 (c7d45ad)", "Scope: all")
    )
    assert display.permission_question(request) == (
        "Permission needed: test_runner__run_tests needs run_tests and start_service.\n"
        "Version: base v1.0 (c7d45ad)\n"
        "Scope: all\n"
        "\n"
        "  1. Allow once\n"
        "  2. Allow for the rest of the session\n"
        "  3. Deny (Esc)"
    )
    assert [display.answer_line(a) for a in ("once", "session", "deny")] == [
        "Allow once",
        "Allow for the rest of the session",
        "Deny",
    ]


def test_the_approval_question_shows_every_command_and_the_two_answers():
    from retroagent.runtime.permissions import ApprovalRequest

    request = ApprovalRequest("/work/shop", (("tests.command", "pytest"),), (), "/home/me/.retro/approvals.json")
    assert display.question(request) == (
        "The project commands are not approved in their current content.\n"
        "Project: /work/shop\n"
        "They run on this machine with your privileges; RetroAgent is not a sandbox.\n"
        "  tests.command: pytest\n"
        "  tests.env: (none)\n"
        "An approval is stored in /home/me/.retro/approvals.json; a command that changes is asked again.\n"
        "\n"
        "  1. Approve these commands\n"
        "  2. Deny (Esc)"
    )
    assert [display.answer_line(a, request) for a in ("approve", "deny")] == ["Approve these commands", "Deny"]
    assert [value for _, value, _ in display.choices(request)] == ["approve", "deny"]


def test_the_recorded_line_lists_the_write_tools_of_the_turn_with_their_count():
    recorded = (("memory__save_triage", 4), ("memory__register_defect", 1))
    assert display.recorded_line(recorded) == "Recorded: 4 memory__save_triage, 1 memory__register_defect."


def test_the_recorded_line_of_a_turn_that_recorded_nothing():
    assert display.recorded_line(()) == "Nothing was recorded."
