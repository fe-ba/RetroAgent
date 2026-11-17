"""The context budget: measuring, calibration, the truncation guard, limits at start, bounds and freeing context."""

import pytest

from retroagent.context import budget as b
from retroagent.context import skills
from retroagent.context.budget import Budget, Calibration
from retroagent.llm import Capabilities, FakeProvider, Message, Request, Response, ToolCall, ToolDefinition, Usage
from retroagent.llm.provider import request_characters

PROFILE = {"context_window": 32_768, "max_output_tokens": 4_096}


def request(text="x" * 4_000) -> Request:
    return Request(
        messages=(Message("system", "rules " * 100), Message("user", text)),
        tools=(ToolDefinition("memory__get_suite", "Read the suite.", {"type": "object"}),),
        temperature=0,
        max_output_tokens=4_096,
        context_window=32_768,
        thinking="default",
        timeout=60,
    )


# Measuring -----------------------------------------------------------------------------------------------------------


def test_estimate_is_characters_divided_by_4_times_the_ratio_rounded_up():
    assert b.estimate(400, 1.0) == 100
    assert b.estimate(400, 1.3) == 130
    assert b.estimate(401, 1.0) == 101
    assert b.estimate(40, 1.3) == 13  # 13.000000000000002 in floating point
    assert b.estimate(0, 1.3) == 0


def test_the_fixed_part_counts_system_context_tool_definitions_and_state_message():
    tool = ToolDefinition("memory__get_suite", "Read the suite.", {"type": "object"})
    state = Message("user", "<session-state>x</session-state>")
    expected = 10 + len("memory__get_suite") + len("Read the suite.") + len('{"type": "object"}') + len(state.content)
    assert b.fixed_characters("s" * 10, [tool], state) == expected


# Calibration ---------------------------------------------------------------------------------------------------------


def test_the_ratio_starts_at_1_3():
    assert Calibration().ratio == 1.3


def test_the_ratio_is_the_highest_of_the_last_three_calls():
    calibration = Calibration().observe(4_000, 1_500).observe(4_000, 1_200).observe(4_000, 1_100)
    assert calibration.ratio == 1.5
    calibration = calibration.observe(4_000, 1_150)  # the 1.5 call is now four calls old
    assert calibration.ratio == 1.2


def test_the_ratio_is_never_below_1():
    assert Calibration().observe(4_000, 700).ratio == 1.0


def test_an_honest_provider_and_one_that_reports_more_tokens_calibrate_the_ratio():
    honest = FakeProvider([Response("ok")])
    sent = request()
    calibration = b.after_call(Calibration(), sent, honest.complete(sent), window=32_768)
    assert calibration.ratio == 1.0

    more = FakeProvider([Response("ok")], usage=lambda req, resp: Usage(request_characters(req) * 3 // 8, 1))
    calibration = b.after_call(Calibration(), sent, more.complete(sent), window=32_768)
    assert calibration.ratio == pytest.approx(1.5, abs=0.001)


def test_without_usage_nothing_is_calibrated_or_guarded():
    silent = FakeProvider([Response("ok")], usage=lambda req, resp: None)
    sent = request()
    assert b.after_call(Calibration(), sent, silent.complete(sent), window=32_768) == Calibration()
    assert "cannot detect" in b.NO_USAGE_WARNING


# Truncation guard ----------------------------------------------------------------------------------------------------


def test_the_guard_stops_a_provider_that_read_a_quarter_of_the_context():
    dropping = FakeProvider([Response("ok")], usage=lambda req, resp: Usage(request_characters(req) // 16, 1))
    sent = request()
    response = dropping.complete(sent)
    with pytest.raises(b.TruncationDetected, match="context window of 32768 tokens"):
        b.after_call(Calibration(), sent, response, window=32_768)


def test_the_guard_threshold_is_60_percent_of_characters_divided_by_4():
    b.check_truncation(4_000, 600, window=8_192)
    with pytest.raises(b.TruncationDetected):
        b.check_truncation(4_000, 599, window=8_192)


# Window and limits at start ------------------------------------------------------------------------------------------


def test_the_window_of_the_profile_takes_precedence_over_the_provider():
    assert b.budget(PROFILE, Capabilities(True, 1_000_000)) == Budget(32_768, 4_096)
    assert b.budget({**PROFILE, "context_window": None}, Capabilities(True, 128_000)) == Budget(128_000, 4_096)


def test_an_unknown_window_stops_the_session():
    with pytest.raises(b.ContextBudgetError, match="Set context_window in the model profile"):
        b.budget({**PROFILE, "context_window": None}, Capabilities(None, None))


def test_limits_at_start():
    budget = Budget(32_768, 4_096)  # 28,672 tokens
    assert b.check_start(budget, 7_168) is None  # exactly 25%
    warning = b.check_start(budget, 7_169)
    assert "more than a quarter" in warning
    assert b.check_start(budget, 14_336) is not None  # exactly 50%: warned, not refused
    with pytest.raises(b.ContextBudgetError, match="needs a context window of at least 32772 tokens"):
        b.check_start(budget, 14_338)


def test_a_window_that_is_too_small_is_refused():
    with pytest.raises(b.ContextBudgetError, match="too small for RetroAgent"):
        b.check_start(Budget(8_192, 4_096), 3_000)


def test_an_output_reserve_that_fills_the_window_is_refused():
    with pytest.raises(b.ContextBudgetError, match="leaves no room"):
        b.check_start(Budget(4_096, 4_096), 0)


def test_variable_space_is_the_budget_minus_the_fixed_part():
    assert Budget(32_768, 4_096).variable_space(8_672) == 20_000


# Bounds --------------------------------------------------------------------------------------------------------------


def test_result_limit():
    assert b.result_limit(Budget(200_000, 8_192)) == 20_000
    assert b.result_limit(Budget(32_768, 4_096)) == 13_233  # 28,672 * 0.15 * 4 / 1.3
    assert b.result_limit(Budget(16_384, 4_096)) == 5_671


def test_results_of_one_model_message_are_deferred_at_40_percent_of_the_variable_space():
    assert not b.defer_remaining(15_996, 10_000, 1.0)  # 3,999 tokens
    assert b.defer_remaining(16_000, 10_000, 1.0)  # 4,000 tokens
    assert b.defer_remaining(12_310, 10_000, 1.3)  # 4,001 tokens with the ratio


# Freeing context -----------------------------------------------------------------------------------------------------
# With ratio 1.0, 400 characters are 100 tokens. The variable space is 1,000 tokens: freeing starts above 800 and
# ends at 500 or less.


def user(text, size=40):
    return Message("user", text.ljust(size, "."))


def answer(size=40):
    return Message("assistant", "a" * size)


def calling(call_id, tool="git__get_diff"):
    return Message("assistant", "", (ToolCall(call_id, tool, {}),))


def result(call_id, size):
    return Message("tool", "r" * size, tool_call_id=call_id)


def free(conversation, **options):
    return b.free_context(conversation, variable_space=1_000, ratio=1.0, **options)


def tokens(conversation):
    return b.estimate(b.conversation_characters(conversation), 1.0)


def test_nothing_is_freed_up_to_80_percent():
    conversation = (user("q1"), calling("c1"), result("c1", 3_000))
    assert tokens(conversation) <= 800
    assert free(conversation) == conversation


def test_the_oldest_tool_results_are_replaced_first_one_by_one():
    conversation = (
        user("q1"),
        calling("c1"),
        result("c1", 1_200),
        calling("c2", "git__read_file"),
        result("c2", 1_200),
        calling("c3"),
        result("c3", 800),
        answer(),
        user("q2"),
    )
    assert tokens(conversation) > 800
    freed = free(conversation)
    assert (
        freed[2].content
        == "[Result of git__get_diff (call c1) removed to save context. Call the tool again if you need it.]"
    )
    assert freed[4].content == (
        "[Result of git__read_file (call c2) removed to save context. Call the tool again if you need it.]"
    )
    assert freed[6] == conversation[6]  # 50% was reached before it
    assert tokens(freed) <= 500
    assert [m.role for m in freed] == [m.role for m in conversation]


def test_never_replaced_the_loaded_skill_the_current_user_message_and_the_current_results():
    conversation = (
        user("q1"),
        calling("skill", "runtime__load_skill"),
        result("skill", 800),
        answer(),
        user("q2", size=400),
        calling("c2"),
        result("c2", 1_600),
        calling("c3"),
        result("c3", 560),
    )
    assert tokens(conversation) > 800
    freed = free(conversation, loaded_skill_call="skill")
    assert freed[2] == conversation[2]  # the loaded skill
    assert freed[4] == conversation[4]  # the user message of the current turn
    assert freed[8] == conversation[8]  # the results of the current model message
    assert freed[6].content.startswith("[Result of git__get_diff (call c2) removed")
    assert tokens(freed) <= 500


def test_then_the_oldest_whole_turns_are_removed_with_a_note():
    conversation = (
        user("q1", size=1_000),
        answer(1_000),
        user("q2", size=1_000),
        answer(400),
        user("q3", size=400),
        answer(400),
        user("q4", size=40),
    )
    freed = free(conversation)
    assert freed[0].role == "user"
    assert freed[0].content.startswith("[2 earlier turns removed to save context.]\n\nq3")
    assert freed[1:] == conversation[5:]
    assert tokens(freed) <= 500


def test_turn_notes_add_up():
    conversation = (
        user("[3 earlier turns removed to save context.]\n\nq4", size=1_200),
        answer(1_200),
        user("q5", size=400),
        answer(400),
        user("q6"),
    )
    freed = free(conversation)
    assert freed[0].content.startswith("[4 earlier turns removed to save context.]\n\nq5")
    assert freed[0].content.count("removed to save context") == 1


def test_a_turn_that_holds_the_loaded_skill_is_not_removed():
    conversation = (
        user("q1"),
        calling("skill", "runtime__load_skill"),
        result("skill", 1_200),
        answer(),
        user("q2", size=1_200),
        answer(400),
        user("q3", size=400),
        answer(),
        user("q4"),
    )
    freed = free(conversation, loaded_skill_call="skill")
    assert freed[:4] == conversation[:4]
    assert freed[4].content.startswith("[1 earlier turn removed to save context.]\n\nq3")
    assert tokens(freed) <= 500


def test_when_the_conversation_does_not_fit_after_freeing_the_call_is_not_made():
    conversation = (user("q1", size=2_000), calling("c1"), result("c1", 2_000))
    assert tokens(conversation) > 1_000
    with pytest.raises(b.ContextFull, match="more than the 1000 tokens available"):
        free(conversation)


def test_50_percent_is_a_target_not_a_condition():
    conversation = (
        user("q1"),
        calling("c1"),
        result("c1", 800),
        answer(),
        user("q2", size=1_200),
        calling("c2"),
        result("c2", 1_600),
    )
    assert tokens(conversation) > 800
    freed = free(conversation)
    assert freed[0].content.startswith("[1 earlier turn removed to save context.]\n\nq2")
    assert freed[1:] == conversation[5:]
    assert 500 < tokens(freed) <= 1_000


def test_a_loaded_skill_and_the_current_results_above_half_of_a_32k_window_do_not_stop_the_call():
    """Window 32,768, output reserve 4,096, and a fixed part of 11,000 tokens: about the system context, the tool
    definitions and the state message. The loaded skill and the results of the current model message, at 40% of
    the variable space, are more than half of it together, and are never replaced."""
    variable = Budget(32_768, 4_096).variable_space(11_000)
    ratio = b.INITIAL_RATIO
    skill_body = skills.load_skill(skills.discover([skills.bundled_location()]), "test-design", None).content
    results = int(b.MESSAGE_RESULTS_SHARE * variable * b.CHARACTERS_PER_TOKEN / ratio)
    conversation = (
        user("Load the skill test-design and implement the test cases of the current suite."),
        calling("skill", "runtime__load_skill"),
        Message("tool", skill_body, tool_call_id="skill"),
        calling("c1", "memory__get_suite"),
        result("c1", 12_000),
        calling("c1b", "git__read_file"),
        result("c1b", 12_000),
        answer(),
        user("Now rewrite TC-027."),
        Message(
            "assistant",
            "",
            (ToolCall("c2", "memory__get_test_cases", {}), ToolCall("c3", "test_runner__get_evidence", {})),
        ),
        result("c2", results // 2),
        result("c3", results - results // 2),
    )
    current = conversation[8:]
    assert b.estimate(b.conversation_characters(current[2:]), ratio) >= b.MESSAGE_RESULTS_SHARE * variable
    protected = (conversation[2], *current)
    assert b.estimate(b.conversation_characters(protected), ratio) > variable / 2
    assert b.estimate(b.conversation_characters(conversation), ratio) > b.FREE_ABOVE * variable

    freed = b.free_context(conversation, variable_space=variable, ratio=ratio, loaded_skill_call="skill")
    assert freed[2] == conversation[2]
    assert freed[4].content.startswith("[Result of memory__get_suite (call c1) removed")
    assert freed[6].content.startswith("[Result of git__read_file (call c1b) removed")
    assert freed[8:] == current
    assert variable / 2 < b.estimate(b.conversation_characters(freed), ratio) <= variable


def test_force_frees_below_the_80_percent_trigger():
    conversation = (user("q1"), calling("c1"), result("c1", 2_400), answer(), user("q2"))
    assert 500 < tokens(conversation) <= 800
    assert free(conversation) == conversation
    forced = free(conversation, force=True)
    assert forced[2].content.startswith("[Result of git__get_diff (call c1) removed")
    assert tokens(forced) <= 500


def test_a_conversation_larger_than_a_small_window():
    """A long session in a window of 8,192 tokens with 2,048 reserved and a fixed part of 3,000 tokens."""
    variable = Budget(8_192, 2_048).variable_space(3_000)
    conversation = [user("q0"), calling("skill", "runtime__load_skill"), result("skill", 2_000), answer()]
    for n in range(1, 8):
        conversation += [user(f"q{n}"), calling(f"c{n}"), result(f"c{n}", 3_000), answer(200)]
    conversation += [user("q8"), calling("c8"), result("c8", 1_000)]
    ratio = 1.3
    assert b.estimate(b.conversation_characters(conversation), ratio) > variable
    freed = b.free_context(conversation, variable_space=variable, ratio=ratio, loaded_skill_call="skill")
    assert b.estimate(b.conversation_characters(freed), ratio) <= variable // 2
    assert freed[2] == conversation[2]  # loaded skill
    assert freed[-3:] == tuple(conversation[-3:])  # current user message, call and results
    assert all(m.content.startswith("[Result of") for m in freed[:-1] if m.role == "tool" and m.tool_call_id != "skill")
