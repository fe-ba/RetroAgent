"""The order from stable to volatile: what changes between calls never changes the bytes before it."""

import dataclasses
import datetime
import json

from retroagent.context import state as state_module
from retroagent.context.state import Digest, SessionState, Version, call_messages, state_message
from retroagent.llm.provider import Message, ToolCall, ToolDefinition

SYSTEM = "# Steering\n\n## Identity\n\nRules.\n"
TOOLS = (ToolDefinition("memory__get_suite", "Read the suite.", {"type": "object"}),)
NO_DEFECTS = dict.fromkeys(state_module.SEVERITIES, 0)


def session(**changes) -> SessionState:
    values = dict(
        date=datetime.date(2026, 11, 19),
        project_name="shop-api",
        project_path="/work/shop-api",
        base=Version("v1.0", "a" * 40),
        candidate=Version("v1.1", "b" * 40),
        mode="default",
        permissions={"run_tests": "ask", "write_tests": "ask", "start_service": "ask"},
        commands_approved=False,
        model="fake/model",
        language="en",
    )
    values.update(changes)
    return SessionState(**values)


def serialized(tools, messages) -> bytes:
    """The bytes of a call, in the order they are sent."""
    parts = [json.dumps(dataclasses.asdict(t), sort_keys=True) for t in tools]
    parts += [json.dumps(dataclasses.asdict(m), sort_keys=True) for m in messages]
    return "\n".join(parts).encode("utf-8")


def test_the_system_context_is_first_and_the_state_message_last():
    conversation = (Message("user", "Analyze the change."),)
    state = state_message(session(), Digest(None, None, None, None, None, NO_DEFECTS, None))
    messages = call_messages(SYSTEM, conversation, state)
    assert messages[0] == Message("system", SYSTEM)
    assert messages[1:-1] == conversation
    assert messages[-1] == state
    assert state not in conversation


def test_two_calls_of_a_turn_share_every_byte_before_the_added_messages():
    conversation = [Message("user", "Analyze the change.")]
    first_state = state_message(session(), Digest(None, None, None, None, None, NO_DEFECTS, None))
    first = serialized(TOOLS, call_messages(SYSTEM, conversation, first_state))

    call = ToolCall("call-1", "memory__get_suite", {})
    conversation += [Message("assistant", "", (call,)), Message("tool", '{"suite": null}', tool_call_id="call-1")]
    second_state = state_message(
        session(date=datetime.date(2026, 11, 20), mode="auto"),
        Digest(None, None, None, None, None, {**NO_DEFECTS, "high": 1}, None),
    )
    assert second_state != first_state
    second = serialized(TOOLS, call_messages(SYSTEM, conversation, second_state))

    stable = serialized(TOOLS, call_messages(SYSTEM, conversation[:1], first_state)[:-1])
    assert first.startswith(stable)
    assert second.startswith(stable)
    assert len(stable) > len(SYSTEM)


def test_changing_only_the_state_changes_only_the_last_message():
    conversation = (Message("user", "Status?"),)
    a = call_messages(
        SYSTEM, conversation, state_message(session(), Digest(None, None, None, None, None, NO_DEFECTS, None))
    )
    b = call_messages(
        SYSTEM,
        conversation,
        state_message(session(mode="plan"), Digest(None, None, None, None, None, NO_DEFECTS, None)),
    )
    assert a[:-1] == b[:-1]
    assert a[-1] != b[-1]


def test_the_state_message_is_never_stored_in_the_conversation():
    conversation = [Message("user", "Status?")]
    state = state_message(session(), Digest(None, None, None, None, None, NO_DEFECTS, None))
    call_messages(SYSTEM, conversation, state)
    call_messages(SYSTEM, conversation, state)
    assert conversation == [Message("user", "Status?")]
