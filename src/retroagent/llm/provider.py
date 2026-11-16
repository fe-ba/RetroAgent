"""The ``LLMProvider`` interface: request, response, capabilities and errors (spec/llm-providers.md, ADR-0003).

The runtime depends only on this module. No module outside ``retroagent.llm`` imports a provider library.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

ROLES = ("system", "user", "assistant", "tool")
THINKING = ("default", "on", "off")
FINISH_REASONS = ("stop", "tool_calls", "length")


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, object]
    # Raw text of arguments that are not a valid JSON object; ``arguments`` is then empty and the runtime answers
    # the call with an ``invalid_argument`` error instead of dispatching it.
    invalid_arguments: str | None = None


@dataclass(frozen=True)
class Message:
    role: str  # one of ROLES
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()  # assistant messages only
    tool_call_id: str | None = None  # tool messages only: the call this message answers


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, object]  # JSON schema of the arguments


@dataclass(frozen=True)
class Request:
    messages: tuple[Message, ...]
    tools: tuple[ToolDefinition, ...]
    temperature: float
    max_output_tokens: int
    context_window: int | None
    thinking: str  # one of THINKING
    timeout: float


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Response:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = "stop"  # one of FINISH_REASONS
    thinking: str | None = None
    usage: Usage | None = None


@dataclass(frozen=True)
class Capabilities:
    tool_calling: bool | None
    context_window: int | None


class LLMProvider(Protocol):
    def complete(self, request: Request) -> Response: ...

    def capabilities(self) -> Capabilities: ...


def request_from_profile(
    profile: Mapping[str, object], messages: Sequence[Message], tools: Sequence[ToolDefinition] = ()
) -> Request:
    """A request with the settings of a model profile (``configuration.md``, Model profiles)."""
    return Request(
        messages=tuple(messages),
        tools=tuple(tools),
        temperature=profile["temperature"],
        max_output_tokens=profile["max_output_tokens"],
        context_window=profile["context_window"],
        thinking=profile["thinking"],
        timeout=profile["timeout"],
    )


@dataclass(frozen=True)
class Wait:
    """A wait before a model call, shown in verbose mode: a retry, or pacing under ``requests_per_minute``."""

    reason: str  # rate_limit, unavailable or pacing
    attempt: int  # number of the retry; 0 for pacing
    seconds: float


# Errors. Every ``ProviderError`` is a runtime error: it ends the current turn (llm-providers.md, Errors and
# retries). Messages never contain a credential.


class ProviderError(Exception):
    pass


class RateLimitExceeded(ProviderError):
    """Still rate limited after 3 retries."""


class QuotaExhausted(ProviderError):
    """A limit that does not clear within minutes, such as requests per day. Not retried."""


class ProviderUnavailable(ProviderError):
    """Network error, server error or timeout, still failing after 3 retries."""


class AuthenticationRejected(ProviderError):
    """The provider rejected the credential. Names the variable, never its value."""

    def __init__(self, message: str, variable: str | None):
        super().__init__(message)
        self.variable = variable


class MissingCredential(ProviderError):
    """The variable named by ``api_key_env`` is not set. At session start this is exit code 2."""

    def __init__(self, variable: str):
        super().__init__(f"The environment variable {variable}, named by api_key_env of the model profile, is not set.")
        self.variable = variable


class ContextWindowExceeded(ProviderError):
    """The provider refused the context as too long. The turn frees context and retries once."""


class InvalidRequest(ProviderError):
    """The provider refused the request, or blocked the response. Carries the provider message."""
