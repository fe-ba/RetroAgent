"""What the terminal shows of a turn: one line per event, and the question of a permission (runtime.md, Display).

Without verbose mode a tool call is one line with its name and outcome, and warnings are shown. Verbose mode adds the
arguments (as recorded: secret values replaced) and the duration of each tool call, each model call with its token
usage, each retry of the turn, each wait of the provider adapter and each notice logged by the provider library.
Pure functions: they return text.
"""

from retroagent.llm.provider import ProviderNotice, Wait
from retroagent.runtime.permissions import PermissionRequest
from retroagent.runtime.turn import ModelCalled, Retried, ToolCalled, Warned

ARGUMENTS_SHOWN = 300  # characters of the arguments of a tool call shown in verbose mode

RETRIES = {
    "context_window_exceeded": "the provider refused the context as too long; freeing context and calling again",
    "length": "the answer was cut at max_output_tokens before its tool calls were complete; asking for a shorter one",
}
WAITS = {
    "rate_limit": "rate limited by the provider",
    "unavailable": "the provider is unavailable",
    "pacing": "pacing under requests_per_minute",
}

# The answers to a permission question, by key: allow once, allow for the rest of the session, deny.
ANSWER_CHOICES = (("1", "once", "Allow once"), ("2", "session", "Allow for the rest of the session"),
                  ("3", "deny", "Deny (Esc)"))  # fmt: skip


def event_line(event: object, verbose: bool) -> str | None:
    """The line shown for an event of the turn, or None when this mode shows nothing for it."""
    if isinstance(event, Warned):
        return f"warning: {event.message}"
    if isinstance(event, ToolCalled):
        result = event.outcome + (f" {event.code}" if event.code else "")
        if not verbose:
            return f"{event.name}: {result}"
        arguments = event.arguments
        if len(arguments) > ARGUMENTS_SHOWN:
            arguments = arguments[:ARGUMENTS_SHOWN] + f"... ({len(event.arguments):,} characters)"
        return f"tool {event.name} {arguments}: {result}, {event.seconds:.1f} s"
    if not verbose:
        return None
    if isinstance(event, ModelCalled):
        if event.usage is not None:
            usage = f"{event.usage.input_tokens:,} input and {event.usage.output_tokens:,} output tokens"
        else:
            usage = "usage not reported"
        line = (
            f"model call {event.iteration}: {event.characters:,} characters sent, {usage}, {event.seconds:.1f} s,"
            f" finish {event.finish_reason}"
        )
        if event.thinking:
            line += f"\n  thinking: {event.thinking}"
        return line
    if isinstance(event, Retried):
        return f"retry: {RETRIES.get(event.reason, event.reason)}"
    if isinstance(event, Wait):
        reason = WAITS.get(event.reason, event.reason)
        attempt = f", retry {event.attempt}" if event.attempt else ""
        return f"wait {event.seconds:.1f} s: {reason}{attempt}"
    if isinstance(event, ProviderNotice):
        return f"provider notice: {event.message}"
    return None


def permission_question(request: PermissionRequest) -> str:
    """The question of a permission: what will happen, then the three answers."""
    lines = [f"Permission needed: {request.tool} needs {' and '.join(request.permissions)}.", *request.details, ""]
    lines += [f"  {key}. {label}" for key, _, label in ANSWER_CHOICES]
    return "\n".join(lines)


def answer_line(answer: str) -> str:
    return next(label for _, value, label in ANSWER_CHOICES if value == answer).replace(" (Esc)", "")
