"""The context budget: measuring, calibration, limits at start, bounds, freeing context and the truncation guard
(spec/context-loading.md, Context budget; ADR-0028).

Sizes are estimated as characters divided by 4, multiplied by a calibration ratio that follows the input tokens the
provider reports. Thresholds apply to the variable space: the budget (window minus output reserve) minus the fixed
part (system context, tool definitions and state message).
"""

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from retroagent.llm.provider import (
    Capabilities,
    Message,
    Request,
    Response,
    ToolDefinition,
    definition_characters,
    message_characters,
    request_characters,
)

CHARACTERS_PER_TOKEN = 4
INITIAL_RATIO = 1.3
MIN_RATIO = 1.0
CALIBRATION_CALLS = 3
TRUNCATION_SHARE = 0.6  # reported tokens below this share of characters / 4: the server dropped context
WARN_SHARE, REFUSE_SHARE = 0.25, 0.5  # of the budget, for the fixed part of the largest tool set
RESULT_LIMIT = 20_000  # characters
MESSAGE_RESULTS_SHARE = 0.4  # of the variable space, for the results of one model message
FREE_ABOVE, FREE_DOWN_TO = 0.8, 0.5  # of the variable space, for the conversation

NO_USAGE_WARNING = (
    "The provider does not report input tokens: RetroAgent cannot detect a server that drops part of the context."
)


class ContextBudgetError(Exception):
    """The session cannot start with this model: the window is unknown or too small (exit code 2)."""


class ContextFull(Exception):
    """Even after freeing, the conversation does not fit in the variable space: the call is not made."""


class TruncationDetected(Exception):
    """The provider read far fewer tokens than were sent: the model did not receive the whole context."""


# Measuring -----------------------------------------------------------------------------------------------------------


def estimate(characters: int, ratio: float) -> int:
    """Estimated tokens: characters divided by 4, multiplied by the ratio, rounded up."""
    return math.ceil(round(characters * ratio / CHARACTERS_PER_TOKEN, 6))


def conversation_characters(conversation: Sequence[Message]) -> int:
    return sum(message_characters(m) for m in conversation)


def fixed_characters(system_context: str, tools: Sequence[ToolDefinition], state: Message) -> int:
    """Characters of the fixed part: system context, tool definitions and state message."""
    return len(system_context) + sum(definition_characters(t) for t in tools) + message_characters(state)


@dataclass(frozen=True)
class Calibration:
    """Reported input tokens divided by characters / 4, for the last three calls that reported them."""

    samples: tuple[float, ...] = ()

    @property
    def ratio(self) -> float:
        if not self.samples:
            return INITIAL_RATIO
        return max(MIN_RATIO, *self.samples)

    def observe(self, characters: int, input_tokens: int) -> "Calibration":
        if characters <= 0:
            return self
        sample = input_tokens / (characters / CHARACTERS_PER_TOKEN)
        return Calibration((*self.samples, sample)[-CALIBRATION_CALLS:])


def check_truncation(characters: int, input_tokens: int, window: int) -> None:
    """The truncation guard. Raises ``TruncationDetected`` when fewer than 60% of characters / 4 were read."""
    sent = characters / CHARACTERS_PER_TOKEN
    if input_tokens < TRUNCATION_SHARE * sent:
        raise TruncationDetected(
            f"The model read {input_tokens} input tokens of about {math.floor(sent)} sent: the server dropped part of"
            f" the context, and with it the steering. RetroAgent was configured with a context window of {window}"
            f" tokens; configure the server with at least that context size, or set context_window in the model"
            f" profile to what the server uses."
        )


def after_call(calibration: Calibration, request: Request, response: Response, window: int) -> Calibration:
    """Apply the truncation guard to a completed call and calibrate with it. A response without usage changes
    nothing; the runtime then warns once with ``NO_USAGE_WARNING``."""
    if response.usage is None:
        return calibration
    characters = request_characters(request)
    check_truncation(characters, response.usage.input_tokens, window)
    return calibration.observe(characters, response.usage.input_tokens)


# Window and limits at start ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Budget:
    window: int
    output_reserve: int

    @property
    def tokens(self) -> int:
        """Window minus output reserve."""
        return self.window - self.output_reserve

    def variable_space(self, fixed_tokens: int) -> int:
        """What the conversation may use."""
        return self.tokens - fixed_tokens


def budget(profile: Mapping[str, object], capabilities: Capabilities) -> Budget:
    """The budget of a model profile. The ``context_window`` of the profile takes precedence over the provider."""
    window = profile.get("context_window") or capabilities.context_window
    if not window:
        raise ContextBudgetError(
            "The context window of the model is unknown: the provider does not report it. Set context_window in the"
            " model profile."
        )
    return Budget(window=window, output_reserve=profile["max_output_tokens"])


def check_start(budget: Budget, fixed_tokens: int) -> str | None:
    """Check the fixed part of the largest tool set against the budget. Raises ``ContextBudgetError`` above half of
    it; returns a warning above a quarter, otherwise None."""
    if budget.tokens <= 0:
        raise ContextBudgetError(
            f"max_output_tokens ({budget.output_reserve}) leaves no room in a context window of {budget.window}"
            " tokens. Lower max_output_tokens or use a model with a larger context window."
        )
    described = (
        f"The fixed part of the context (system context, tool definitions and state message) takes about"
        f" {fixed_tokens} tokens of a budget of {budget.tokens} (context window {budget.window} minus"
        f" max_output_tokens {budget.output_reserve})"
    )
    if fixed_tokens > REFUSE_SHARE * budget.tokens:
        needed = 2 * fixed_tokens + budget.output_reserve
        raise ContextBudgetError(
            f"{described}, more than half. The model is too small for RetroAgent: it needs a context window of at"
            f" least {needed} tokens."
        )
    if fixed_tokens > WARN_SHARE * budget.tokens:
        return f"{described}, more than a quarter. Little space is left for the conversation."
    return None


# Bounds --------------------------------------------------------------------------------------------------------------


def result_limit(budget: Budget) -> int:
    """Largest tool result, in characters: 20,000, or 15% of the budget when that is less. Tokens become characters
    with the starting ratio, because the limit is written once, when the session starts: 0.15 * 4 / 1.3 = 6 / 13."""
    return min(RESULT_LIMIT, budget.tokens * 6 // 13)


def defer_remaining(results_characters: int, variable_space: int, ratio: float) -> bool:
    """Whether the next tool call of a model message returns ``deferred``: the results of that message already
    reach 40% of the variable space."""
    return estimate(results_characters, ratio) >= MESSAGE_RESULTS_SHARE * variable_space


# Freeing context -----------------------------------------------------------------------------------------------------


TURNS_NOTE = re.compile(r"^\[(\d+) earlier turns? removed to save context\.\]\n\n")


def result_note(tool: str, call_id: str) -> str:
    return f"[Result of {tool} (call {call_id}) removed to save context. Call the tool again if you need it.]"


def turns_note(count: int) -> str:
    return f"[{count} earlier {'turn' if count == 1 else 'turns'} removed to save context.]\n\n"


def free_context(
    conversation: Sequence[Message],
    *,
    variable_space: int,
    ratio: float,
    loaded_skill_call: str | None = None,
    force: bool = False,
) -> tuple[Message, ...]:
    """The conversation to send, freed when it exceeds 80% of the variable space, down to 50% or less.

    First the oldest tool results are replaced, one by one, with a note; then the oldest whole turns are removed,
    and a note at the start of the first kept turn says how many. Never replaced: the loaded skill (the result of
    ``loaded_skill_call``), the user message of the current turn and the results of the current model message; a
    turn that holds the loaded skill is not removed. ``force`` frees down to 50% without the 80% trigger, for the
    retry after the provider refused the context as too long.

    The 50% is a target, not a condition: when everything that may be replaced was replaced, the conversation is
    returned if it fits in the variable space, whatever its share. Raises ``ContextFull`` only when it does not fit.
    """
    messages = list(conversation)

    def size() -> int:
        return estimate(conversation_characters(messages), ratio)

    def done() -> bool:
        return size() <= FREE_DOWN_TO * variable_space

    if not force and size() <= FREE_ABOVE * variable_space:
        return tuple(messages)

    # 1. The oldest tool results.
    tools_by_call = {call.id: call.name for m in messages for call in m.tool_calls}
    protected = _current_results(messages)
    for index, message in enumerate(messages):
        if done():
            return tuple(messages)
        if message.role != "tool" or index in protected or message.tool_call_id == loaded_skill_call:
            continue
        note = result_note(tools_by_call.get(message.tool_call_id, "unknown tool"), message.tool_call_id)
        if message.content != note:
            messages[index] = Message(role="tool", content=note, tool_call_id=message.tool_call_id)

    # 2. The oldest whole turns, except the current one and one that holds the loaded skill.
    while not done():
        starts = [i for i, m in enumerate(messages) if m.role == "user"]
        removable = None
        for start, end in zip(starts, starts[1:], strict=False):
            holds_skill = loaded_skill_call is not None and any(
                m.tool_call_id == loaded_skill_call for m in messages[start:end]
            )
            if not holds_skill:
                removable = (start, end)
                break
        if removable is None:
            if size() > variable_space:
                raise ContextFull(
                    f"The conversation needs about {size()} tokens after freeing, more than the {variable_space}"
                    " tokens available to it."
                )
            return tuple(messages)
        start, end = removable
        removed = 1 + _noted_turns(messages[start])
        del messages[start:end]
        first_kept = messages[start]  # the user message of the next turn
        count = removed + _noted_turns(first_kept)
        text = TURNS_NOTE.sub("", first_kept.content, count=1)
        messages[start] = Message(role="user", content=turns_note(count) + text)
    return tuple(messages)


def _current_results(messages: list[Message]) -> set[int]:
    """Indexes of the tool results at the end of the conversation: the results of the current model message."""
    indexes = set()
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role != "tool":
            break
        indexes.add(index)
    return indexes


def _noted_turns(message: Message) -> int:
    match = TURNS_NOTE.match(message.content)
    return int(match.group(1)) if match else 0
