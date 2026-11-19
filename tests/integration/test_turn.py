"""The turn of runtime.md with FakeProvider and the real bundled servers on the example project: order, audit,
iteration limit, ``deferred``, the two retries of the turn, invalid arguments, the truncation guard, transactions
during dispatch, and provider errors (SC-19, the parts that need no run)."""

import dataclasses
import json

import pytest
from fixtures.agent_session import answer, call, calls, tool_results, tool_rows

from retroagent.context import budget, state
from retroagent.llm import ContextWindowExceeded, FakeProvider, RateLimitExceeded, Usage
from retroagent.llm.provider import request_characters
from retroagent.memory import sessions
from retroagent.runtime import turn as turn_module
from retroagent.runtime.turn import BRIEFLY, ModelCalled, Retried, ToolCalled, TurnError, run_turn
from retroagent.servers.errors import ToolError


def run(session, script, message="Go.", *, ask=None, listener=None, provider=None, **options):
    provider = provider or FakeProvider(script)
    result = run_turn(session, message, provider=provider, client=session.client, ask=ask, listener=listener, **options)
    return result, provider


def with_config(session, **values):
    """Replace configuration values of a running session, by dotted key with ``__`` for the dot."""
    changed = {key.replace("__", "."): value for key, value in values.items()}
    session.config = dataclasses.replace(session.config, values={**session.config.values, **changed})


def error_of(content: str) -> dict:
    return json.loads(content)["error"]


def test_tool_calls_run_one_by_one_in_the_order_given_and_a_refused_one_does_not_stop_the_others(agent):
    first = call("runtime__set_versions", {"base": "v1.1", "candidate": "v1.2"})
    refused = call("test_runner__run_tests", {"version": "base", "scope": "all"})  # ask, and no one to ask
    third = call("git__resolve_ref", {"ref": "v1.2"})
    result, provider = run(agent, [calls(first, refused, third), answer("Versions set.")])

    assert result.text == "Versions set."
    rows = tool_rows(agent.conn, agent.id)
    assert [(r["server"], r["tool"], r["outcome"]) for r in rows] == [
        ("runtime", "set_versions", "ok"),
        ("test_runner", "run_tests", "denied"),
        ("git", "resolve_ref", "ok"),
    ]
    tool_messages = [m for m in agent.conversation.messages if m.role == "tool"]
    assert [m.tool_call_id for m in tool_messages] == [first.id, refused.id, third.id]
    assert error_of(tool_messages[1].content)["code"] == "denied"
    assert json.loads(tool_messages[2].content)["commit"] == agent.versions()["candidate"].commit
    # The model saw every result in its next call, after its own message.
    second_request = provider.requests[1].messages
    assert [m.tool_call_id for m in second_request if m.role == "tool"] == [first.id, refused.id, third.id]


def test_every_call_is_recorded_with_its_arguments_outcome_and_times_also_when_refused(agent):
    script = [
        calls(
            call("git__resolve_ref", {"ref": "v1.0"}),
            call("test_runner__run_tests", {"version": "base", "scope": "all"}),
            call("git__nothing", {}),
        ),
        answer(),
    ]
    run(agent, script)
    rows = tool_rows(agent.conn, agent.id)
    assert [(r["outcome"], r["error"] and r["error"].split(":")[0]) for r in rows] == [
        ("ok", None),
        ("denied", "denied"),
        ("error", "not_found"),
    ]
    assert json.loads(rows[0]["arguments"]) == {"ref": "v1.0"}
    assert json.loads(rows[1]["arguments"]) == {"version": "base", "scope": "all"}
    for row in rows:
        assert row["started_at"] and row["ended_at"] and row["started_at"] <= row["ended_at"]
        assert row["error"] != sessions.UNANSWERED


def test_a_secret_value_in_an_argument_is_replaced_in_the_record_and_in_the_events(agent, monkeypatch):
    secret = "not-a-real-key-7c1f2a"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    events = []
    run(agent, [calls(call("git__resolve_ref", {"ref": f"tag-{secret}"})), answer()], listener=events.append)
    (row,) = tool_rows(agent.conn, agent.id)
    assert row["outcome"] == "error"  # the ref does not exist; the server names it in its message
    assert secret not in row["arguments"] and secret not in row["error"]
    assert json.loads(row["arguments"]) == {"ref": "tag-***"}
    assert "tag-***" in row["error"]
    (event,) = [e for e in events if isinstance(e, ToolCalled)]
    assert secret not in event.arguments


def test_a_dotted_tool_name_is_normalized(agent):
    run(agent, [calls(call("git.resolve_ref", {"ref": "v1.0"})), answer()])
    (row,) = tool_rows(agent.conn, agent.id)
    assert (row["server"], row["tool"], row["outcome"]) == ("git", "resolve_ref", "ok")


def test_a_tool_that_does_not_exist_is_not_found(agent):
    nameless, unknown = call("nothing"), call("git__nothing")
    run(agent, [calls(nameless, unknown), answer()])
    rows = tool_rows(agent.conn, agent.id)
    assert [(r["server"], r["tool"], r["outcome"]) for r in rows] == [
        ("", "nothing", "error"),
        ("git", "nothing", "error"),
    ]
    results = tool_results(agent.conversation)
    assert error_of(results[nameless.id]) == {"code": "not_found", "message": "there is no tool nothing"}
    assert error_of(results[unknown.id])["code"] == "not_found"


def test_a_tool_outside_the_tool_set_of_the_step_is_denied_and_the_message_names_its_tools(agent):
    # the call of the real triage: a new analysis is the work of another step
    outside = call("git__analyze_changes", {})
    _, provider = run(agent, [calls(outside), answer()], tool_set="triage")
    error = error_of(tool_results(agent.conversation)[outside.id])
    offered = [tool.name for tool in provider.requests[0].tools]
    assert offered and "git__analyze_changes" not in offered and "memory__save_triage" in offered
    assert error == {
        "code": "denied",
        "message": f"git__analyze_changes is not a tool of the step triage; this step has: {', '.join(offered)}",
    }
    (row,) = tool_rows(agent.conn, agent.id)
    assert row["outcome"] == "denied"


def test_the_turn_stops_at_the_iteration_limit_after_running_the_calls_of_the_last_call(agent):
    with_config(agent, agent__max_iterations=3)
    # Different arguments each time: an identical read would not be dispatched again (Repeated calls).
    script = [calls(call("git__resolve_ref", {"ref": ref})) for ref in ("v1.0", "v1.1", "v1.2", "HEAD", "main")]
    result, provider = run(agent, script)
    assert result.limit_reached and "3 model calls" in result.text and "agent.max_iterations" in result.text
    assert len(provider.requests) == 3 and provider.remaining == 2
    assert [r["outcome"] for r in tool_rows(agent.conn, agent.id)] == ["ok", "ok", "ok"]
    assert agent.conversation.messages[-1].role == "tool"  # every call has its result


def test_the_retries_of_the_turn_count_toward_the_iteration_limit(agent):
    with_config(agent, agent__max_iterations=2)
    result, provider = run(agent, [ContextWindowExceeded("too long"), calls(call("git__resolve_ref", {"ref": "v1.0"}))])
    assert result.limit_reached and len(provider.requests) == 2


def test_calls_after_the_results_fill_their_share_of_the_context_are_deferred(agent):
    path_args = {"path": "src/shop/pricing.py", "version": "base"}
    result_characters = len(json.dumps(agent.client.call("git", "read_file", path_args), ensure_ascii=False))
    # A variable space of half the tokens of that result: its 40% is reached by that result alone, and the
    # conversation still fits in it at the next call.
    variable = result_characters // 4 // 2 * 2 + 200
    system_context = agent.system_context()
    fixed = budget.fixed_characters(system_context, agent.definitions(), agent.state_message())
    reserve = agent.budget.output_reserve
    agent.budget = budget.Budget(
        window=reserve + budget.estimate(fixed, budget.INITIAL_RATIO) + variable, output_reserve=reserve
    )

    read, later, last = call("git__read_file", path_args), call("git__resolve_ref", {"ref": "v1.0"}), call("nothing")
    run(agent, [calls(read, later, last), answer()])
    rows = tool_rows(agent.conn, agent.id)
    assert [r["outcome"] for r in rows] == ["ok", "error", "error"]
    assert rows[1]["error"].startswith("deferred: ") and rows[2]["error"].startswith("deferred: ")
    results = tool_results(agent.conversation)
    assert error_of(results[later.id])["code"] == "deferred"


def test_a_context_window_exceeded_frees_context_and_retries_once(agent):
    events = []
    result, provider = run(agent, [ContextWindowExceeded("too long"), answer("ok")], listener=events.append)
    assert result.text == "ok" and len(provider.requests) == 2
    assert Retried("context_window_exceeded") in events


def test_a_second_context_window_exceeded_is_a_runtime_error(agent):
    with pytest.raises(TurnError, match="still too long"):
        run(agent, [ContextWindowExceeded("too long"), ContextWindowExceeded("too long")])


def test_a_response_cut_with_tool_calls_is_retried_once_with_an_instruction_to_answer_briefly(agent):
    cut = calls(call("git__resolve_ref", {"ref": "v1.0"}), finish_reason="length")
    events = []
    result, provider = run(agent, [cut, answer("Brief.")], listener=events.append)
    assert result.text == "Brief." and Retried("length") in events
    assert tool_rows(agent.conn, agent.id) == []  # the cut calls were neither recorded nor run
    assert BRIEFLY in provider.requests[1].messages[-1].content
    assert BRIEFLY not in provider.requests[0].messages[-1].content
    assert all(BRIEFLY not in m.content and not m.tool_calls for m in agent.conversation.messages)


def test_a_response_cut_twice_with_tool_calls_is_a_runtime_error(agent):
    cut = calls(call("git__resolve_ref", {"ref": "v1.0"}), finish_reason="length")
    with pytest.raises(TurnError, match="cut by max_output_tokens twice"):
        run(agent, [cut, cut])
    assert tool_rows(agent.conn, agent.id) == []


def test_a_response_cut_without_tool_calls_is_kept_and_marked_incomplete(agent):
    result, _ = run(agent, [answer("Half an ans", finish_reason="length")])
    assert (result.text, result.incomplete) == ("Half an ans", True)
    assert agent.conversation.messages[-1].content == "Half an ans"


def test_arguments_that_are_not_a_json_object_are_answered_with_invalid_argument(agent):
    broken = call("git__resolve_ref", invalid='{"ref": "v1.0"')
    unknown_property = call("git__resolve_ref", {"ref": "v1.0", "extra": 1})
    run(agent, [calls(broken, unknown_property), answer()])
    rows = tool_rows(agent.conn, agent.id)
    assert rows[0]["arguments"] == '{"ref": "v1.0"'  # as received
    assert rows[0]["outcome"] == "error" and rows[0]["error"].startswith("invalid_argument: ")
    assert rows[1]["outcome"] == "error" and rows[1]["error"].startswith("invalid_argument: ")
    results = tool_results(agent.conversation)
    assert error_of(results[broken.id])["code"] == "invalid_argument"
    assert error_of(results[unknown_property.id])["code"] == "invalid_argument"


def test_the_truncation_guard_stops_the_session_and_names_the_window(agent):
    def quarter(request, response):
        return Usage(request_characters(request) // 16, 1)

    before = agent.conn.execute("SELECT COUNT(*) FROM analysis").fetchone()[0]
    provider = FakeProvider([calls(call("git__analyze_changes"))], usage=quarter)
    with pytest.raises(TurnError) as raised:
        run(agent, None, provider=provider)
    assert raised.value.ends_session
    assert "context window of 32768 tokens" in str(raised.value)
    assert tool_rows(agent.conn, agent.id) == []  # no tool call of the truncated call ran
    assert agent.conn.execute("SELECT COUNT(*) FROM analysis").fetchone()[0] == before


def test_a_provider_that_reports_no_usage_is_warned_about_once(agent):
    def none(request, response):
        return None

    events = []
    provider = FakeProvider([calls(call("git__resolve_ref", {"ref": "v1.0"})), answer()], usage=none)
    run(agent, None, provider=provider, listener=events.append)
    warnings = [e for e in events if isinstance(e, turn_module.Warned)]
    assert [w.message for w in warnings] == [budget.NO_USAGE_WARNING]
    assert [e.iteration for e in events if isinstance(e, ModelCalled)] == [1, 2]


def test_the_runtime_holds_no_open_transaction_while_a_call_is_dispatched(agent, monkeypatch):
    seen = []
    real_call = agent.client.call

    def watched(*args, **kwargs):
        seen.append(agent.conn.in_transaction)
        return real_call(*args, **kwargs)

    monkeypatch.setattr(agent.client, "call", watched)
    analyze = call("git__analyze_changes")
    run(agent, [calls(analyze), answer()])
    assert seen == [False]
    (row,) = tool_rows(agent.conn, agent.id)
    assert row["outcome"] == "ok"  # the server wrote its analysis while the runtime waited
    analysis_id = json.loads(tool_results(agent.conversation)[analyze.id])["analysis_id"]
    assert agent.conn.execute("SELECT 1 FROM analysis WHERE id = ?", (analysis_id,)).fetchone()


def test_a_provider_error_ends_the_turn_and_leaves_no_partial_record(agent):
    resolved = call("git__resolve_ref", {"ref": "v1.0"})
    with pytest.raises(TurnError, match="per minute"):
        run(agent, [calls(resolved), RateLimitExceeded("still limited per minute after 3 retries")])
    (row,) = tool_rows(agent.conn, agent.id)
    assert row["outcome"] == "ok" and row["ended_at"] is not None
    assert resolved.id in tool_results(agent.conversation)  # completed results stay


def test_events_report_each_model_call_and_tool_call(agent):
    events = []
    run(agent, [calls(call("git__resolve_ref", {"ref": "v1.0"})), answer()], listener=events.append)
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["ModelCalled", "ToolCalled", "ModelCalled"]
    tool_event = events[1]
    assert (tool_event.name, tool_event.outcome, tool_event.code) == ("git__resolve_ref", "ok", None)
    assert events[0].usage is not None and events[0].characters > 0


# What the turn recorded (runtime.md, Display)


def test_a_turn_of_read_tools_records_nothing(agent):
    result, _ = run(agent, [calls(call("memory__get_requirements"), call("git__resolve_ref", {"ref": "v1.0"})),
                            answer("Read.")])  # fmt: skip
    assert result.recorded == ()


def test_a_refused_or_failed_call_is_not_counted_and_writes_of_earlier_turns_are_not_either(agent):
    set_versions = call("runtime__set_versions", {"base": "v1.0", "candidate": "v1.1"})
    first, _ = run(agent, [calls(set_versions), answer("Set.")])
    assert first.recorded == (("runtime__set_versions", 1),)

    again = call("runtime__set_versions", {"base": "v1.0", "candidate": "v1.1"})
    analysis = call("git__analyze_changes", {})  # the call of the real triage: not a tool of the step
    sync = call("memory__sync_requirements")  # neither
    triage = {"execution_id": 99_999, "classification": "regression", "justification": "j"}
    unknown = call("memory__save_triage", triage)  # a refusal of the server: not_found
    result, _ = run(agent, [calls(again, analysis, sync, unknown), answer("Done.")], tool_set="triage")

    assert result.recorded == (("runtime__set_versions", 1),)
    outcomes = [(row["tool"], row["outcome"]) for row in tool_rows(agent.conn, agent.id)][1:]
    assert outcomes == [
        ("set_versions", "ok"), ("analyze_changes", "denied"), ("sync_requirements", "denied"),
        ("save_triage", "error"),
    ]  # fmt: skip


def test_a_turn_that_ends_with_a_runtime_error_still_says_what_it_recorded(agent):
    set_versions = call("runtime__set_versions", {"base": "v1.0", "candidate": "v1.1"})
    cut = calls(call("git__resolve_ref", {"ref": "v1.0"}), finish_reason="length")
    with pytest.raises(TurnError) as raised:
        run(agent, [calls(set_versions), cut, cut])
    assert raised.value.recorded == (("runtime__set_versions", 1),)


# Repeated calls (runtime.md, Turn) -----------------------------------------------------------------------------------


def counted(agent, monkeypatch, fail_once: dict | None = None) -> list[tuple[str, str, dict]]:
    """The calls dispatched to the MCP servers, in order. ``fail_once`` maps a tool name to the ``ToolError`` its
    first dispatch raises instead of reaching the server."""
    dispatched, real, failures = [], agent.client.call, dict(fail_once or {})

    def call_and_count(server, tool, arguments=None, timeout=None):
        dispatched.append((server, tool, dict(arguments or {})))
        if (error := failures.pop(f"{server}__{tool}", None)) is not None:
            raise error
        return real(server, tool, arguments, timeout)

    monkeypatch.setattr(agent.client, "call", call_and_count)
    return dispatched


def assert_blocked(agent, repeated, earlier) -> None:
    error = error_of(tool_results(agent.conversation)[repeated.id])
    assert error["code"] == "invalid_argument"
    assert f"call {earlier.id}" in error["message"] and "change the arguments" in error["message"]


def test_a_second_identical_read_is_not_dispatched_and_names_the_earlier_call(agent, monkeypatch):
    dispatched = counted(agent, monkeypatch)
    first, second = call("git__resolve_ref", {"ref": "v1.0"}), call("git__resolve_ref", {"ref": "v1.0"})
    result, _ = run(agent, [calls(first), calls(second), answer("Resolved.")])
    assert result.text == "Resolved." and len(dispatched) == 1
    assert_blocked(agent, second, first)
    rows = tool_rows(agent.conn, agent.id)
    assert [r["outcome"] for r in rows] == ["ok", "error"] and rows[1]["error"].startswith("invalid_argument: ")


def test_a_read_with_a_different_argument_is_dispatched(agent, monkeypatch):
    dispatched = counted(agent, monkeypatch)
    run(agent, [calls(call("git__resolve_ref", {"ref": "v1.0"})), calls(call("git__resolve_ref", {"ref": "v1.1"})),
                answer()])  # fmt: skip
    assert len(dispatched) == 2
    assert [r["outcome"] for r in tool_rows(agent.conn, agent.id)] == ["ok", "ok"]


def test_the_same_read_after_a_successful_write_is_dispatched(agent, monkeypatch):
    dispatched = counted(agent, monkeypatch)
    read = {"ref": "v1.0"}
    write = call("runtime__set_versions", {"base": "v1.0", "candidate": "v1.1"})
    run(agent, [calls(call("git__resolve_ref", read)), calls(write), calls(call("git__resolve_ref", read)), answer()])
    assert [d[1] for d in dispatched] == ["resolve_ref", "resolve_ref"]
    assert [r["outcome"] for r in tool_rows(agent.conn, agent.id)] == ["ok", "ok", "ok"]


def test_the_same_read_after_a_failed_write_is_still_blocked(agent):
    first, second = call("git__resolve_ref", {"ref": "v1.0"}), call("git__resolve_ref", {"ref": "v1.0"})
    failed = call("runtime__set_versions", {"base": "v1.0", "candidate": "no-such-ref"})
    run(agent, [calls(first), calls(failed), calls(second), answer()])
    assert [r["outcome"] for r in tool_rows(agent.conn, agent.id)] == ["ok", "error", "error"]
    assert_blocked(agent, second, first)


def test_a_repeated_write_tool_is_dispatched(agent):
    arguments = {"base": "v1.0", "candidate": "v1.1"}
    run(agent, [calls(call("runtime__set_versions", arguments)), calls(call("runtime__set_versions", arguments)),
                answer()])  # fmt: skip
    assert [r["outcome"] for r in tool_rows(agent.conn, agent.id)] == ["ok", "ok"]


def test_arguments_in_another_order_are_the_same_call(agent, monkeypatch):
    dispatched = counted(agent, monkeypatch)
    first = call("git__read_file", {"path": "src/shop/pricing.py", "version": "base"})
    second = call("git__read_file", {"version": "base", "path": "src/shop/pricing.py"})
    run(agent, [calls(first), calls(second), answer()])
    assert len(dispatched) == 1
    assert_blocked(agent, second, first)


def test_an_empty_list_is_the_same_as_an_absent_one(agent, monkeypatch):
    # The loop of the local model: get_test_cases with {"ids": []} again and again.
    dispatched = counted(agent, monkeypatch)
    first, second = call("memory__get_test_cases", {"ids": []}), call("memory__get_test_cases", {})
    run(agent, [calls(first), calls(second), answer()])
    assert len(dispatched) == 1
    assert_blocked(agent, second, first)


def test_a_runtime_read_tool_follows_the_same_rule(agent):
    first = call("runtime__load_skill", {"name": "test-selection"})
    second = call("runtime__load_skill", {"name": "test-selection"})
    run(agent, [calls(first), calls(second), answer()])
    assert [r["outcome"] for r in tool_rows(agent.conn, agent.id)] == ["ok", "error"]
    assert_blocked(agent, second, first)


def test_two_identical_reads_in_one_model_message_are_one_dispatch(agent, monkeypatch):
    dispatched = counted(agent, monkeypatch)
    first, second = call("git__resolve_ref", {"ref": "v1.0"}), call("git__resolve_ref", {"ref": "v1.0"})
    run(agent, [calls(first, second), answer()])
    assert len(dispatched) == 1
    assert_blocked(agent, second, first)


def test_a_repeat_after_not_found_is_blocked(agent, monkeypatch):
    dispatched = counted(agent, monkeypatch)
    first, second = call("git__resolve_ref", {"ref": "no-such-ref"}), call("git__resolve_ref", {"ref": "no-such-ref"})
    run(agent, [calls(first), calls(second), answer()])
    assert error_of(tool_results(agent.conversation)[first.id])["code"] == "not_found"
    assert len(dispatched) == 1
    assert_blocked(agent, second, first)


def test_a_repeat_after_unavailable_is_dispatched(agent, monkeypatch):
    stopped = ToolError("unavailable", "the server git did not answer in time")
    dispatched = counted(agent, monkeypatch, fail_once={"git__resolve_ref": stopped})
    first, second = call("git__resolve_ref", {"ref": "v1.0"}), call("git__resolve_ref", {"ref": "v1.0"})
    run(agent, [calls(first), calls(second), answer()])
    assert len(dispatched) == 2
    assert [r["outcome"] for r in tool_rows(agent.conn, agent.id)] == ["error", "ok"]
    assert error_of(tool_results(agent.conversation)[first.id])["code"] == "unavailable"


def test_a_denied_read_is_denied_again_not_blocked(agent):
    # get_report is a read tool, but not a tool of the step triage.
    first, second = call("reports__get_report", {"report_id": "RPT-0001"}), call("reports__get_report",
                                                                                 {"report_id": "RPT-0001"})  # fmt: skip
    run(agent, [calls(first), calls(second), answer()], tool_set="triage")
    assert [r["outcome"] for r in tool_rows(agent.conn, agent.id)] == ["denied", "denied"]


def test_a_repeat_after_the_earlier_result_was_freed_is_dispatched(agent, monkeypatch):
    path_args = {"path": "src/shop/pricing.py", "version": "base"}
    result_characters = len(json.dumps(agent.client.call("git", "read_file", path_args), ensure_ascii=False))
    # Ratio 1.0, as the honest FakeProvider reports. The conversation with that result fits in a variable space of
    # 3/8 of its characters, and is above half of it: the forced freeing after a context window exceeded replaces it.
    agent.calibration = budget.Calibration((1.0,))
    variable = result_characters * 3 // 8
    fixed = budget.fixed_characters(agent.system_context(), agent.definitions(), agent.state_message())
    reserve = agent.budget.output_reserve
    agent.budget = budget.Budget(window=reserve + budget.estimate(fixed, 1.0) + variable, output_reserve=reserve)
    dispatched = counted(agent, monkeypatch)

    first, small, again = (call("git__read_file", path_args), call("git__resolve_ref", {"ref": "v1.0"}),
                           call("git__read_file", path_args))  # fmt: skip
    script = [calls(first), calls(small), ContextWindowExceeded("too long"), calls(again), answer()]
    _, provider = run(agent, script)

    retried = {m.tool_call_id: m.content for m in provider.requests[3].messages if m.role == "tool"}
    assert retried[first.id] == budget.result_note("git__read_file", first.id)
    assert [d[1] for d in dispatched] == ["read_file", "resolve_ref", "read_file"]
    assert [r["outcome"] for r in tool_rows(agent.conn, agent.id)] == ["ok", "ok", "ok"]


def test_a_model_that_repeats_a_call_twice_ends_with_its_own_answer(agent, monkeypatch):
    # Two blocked model calls in a row: the most the rule allows before it stops the turn.
    dispatched = counted(agent, monkeypatch)
    repeated = [call("memory__get_test_cases", {"ids": []}) for _ in range(3)]
    result, provider = run(agent, [*(calls(c) for c in repeated), answer("No test cases yet.")])
    assert result.text == "No test cases yet." and not result.limit_reached and provider.remaining == 0
    assert len(dispatched) == 1
    rows = tool_rows(agent.conn, agent.id)
    assert [r["outcome"] for r in rows] == ["ok"] + ["error"] * 2
    for later in repeated[1:]:
        assert_blocked(agent, later, repeated[0])


def test_in_a_free_message_the_blocked_message_names_no_write_tools(agent):
    first, second = call("memory__get_test_cases", {}), call("memory__get_test_cases", {})
    run(agent, [calls(first), calls(second), answer()])
    error = error_of(tool_results(agent.conversation)[second.id])
    assert error["message"].endswith(f"Use the result of call {first.id}, or change the arguments.")
    assert "write tools" not in error["message"]


def test_in_a_cycle_step_the_blocked_message_names_the_write_tools_of_the_step(agent):
    first, second = call("memory__get_test_cases", {}), call("memory__get_test_cases", {})
    step = state.CycleStep("design", 4, 8)
    run(agent, [calls(first), calls(second), answer()], tool_set="design", cycle_step=step)
    assert_blocked(agent, second, first)
    assert error_of(tool_results(agent.conversation)[second.id])["message"].endswith(
        " The next call of this step is one of its write tools: memory__design_test_case, memory__retire_test_case,"
        " memory__update_test_case."
    )


def test_three_model_calls_in_a_row_with_only_blocked_calls_stop_the_turn(agent, monkeypatch):
    dispatched = counted(agent, monkeypatch)
    repeated = [call("git__resolve_ref", {"ref": "v1.0"}) for _ in range(4)]
    result, provider = run(agent, [*(calls(c) for c in repeated), answer("never reached")])
    assert result.limit_reached and result.text == turn_module.repeat_message('git__resolve_ref {"ref": "v1.0"}')
    assert "max_iterations" not in result.text
    assert len(provider.requests) == 4 and provider.remaining == 1 and len(dispatched) == 1
    assert [r["outcome"] for r in tool_rows(agent.conn, agent.id)] == ["ok"] + ["error"] * 3
    assert agent.conversation.messages[-1].role == "tool"  # every call has its result


def test_a_dispatched_call_between_blocked_model_calls_resets_the_count(agent):
    a, b = {"ref": "v1.0"}, {"ref": "v1.1"}
    script = [calls(call("git__resolve_ref", a)), calls(call("git__resolve_ref", a)),
              calls(call("git__resolve_ref", a)), calls(call("git__resolve_ref", b)),
              calls(call("git__resolve_ref", a)), calls(call("git__resolve_ref", a)), answer("Resolved.")]  # fmt: skip
    result, provider = run(agent, script)
    assert result.text == "Resolved." and not result.limit_reached and provider.remaining == 0
    assert [r["outcome"] for r in tool_rows(agent.conn, agent.id)] == ["ok", "error", "error", "ok", "error", "error"]


def test_a_model_call_with_one_blocked_and_one_dispatched_call_resets_the_count(agent):
    a, c = {"ref": "v1.0"}, {"ref": "v1.2"}
    script = [calls(call("git__resolve_ref", a)), calls(call("git__resolve_ref", a)),
              calls(call("git__resolve_ref", a)),
              calls(call("git__resolve_ref", a), call("git__resolve_ref", c)),
              calls(call("git__resolve_ref", a)), calls(call("git__resolve_ref", a)), answer("Resolved.")]  # fmt: skip
    result, provider = run(agent, script)
    assert result.text == "Resolved." and not result.limit_reached and provider.remaining == 0
    outcomes = [r["outcome"] for r in tool_rows(agent.conn, agent.id)]
    assert outcomes == ["ok", "error", "error", "error", "ok", "error", "error"]
