"""``LiteLLMProvider``: the default ``LLMProvider``, over LiteLLM (spec/llm-providers.md, ADR-0003).

The only module of RetroAgent that imports ``litellm``. It classifies errors and does the retries that only wait;
the retries that change the request are done by the turn. Waits go through an injected clock and sleep.
"""

import json
import logging
import os
import re
import time
from collections import deque
from collections.abc import Callable, Mapping

from retroagent.llm.provider import (
    AuthenticationRejected,
    Capabilities,
    ContextWindowExceeded,
    InvalidRequest,
    Message,
    MissingCredential,
    ProviderError,
    ProviderNotice,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimitExceeded,
    Request,
    Response,
    ToolCall,
    Usage,
    Wait,
)

# provider of the profile -> LiteLLM model prefix (llm-providers.md, Providers)
MODEL_PREFIX = {
    "anthropic": "anthropic",
    "openai": "openai",
    "xai": "xai",
    "google": "gemini",
    "ollama": "ollama_chat",
    "openai_compatible": "openai",
}
LOCAL_PROVIDERS = ("ollama", "openai_compatible")

RATE_LIMIT_WAITS = (15, 30, 60)
UNAVAILABLE_WAITS = (2, 4, 8)
QUOTA_WAIT = 120  # a rate limit that asks to wait longer is an exhausted quota
PACING_WINDOW = 60

# Sent by an ollama profile, and by an openai_compatible profile without api_key_env, so LiteLLM never picks a key
# by itself (OLLAMA_API_KEY, OPENAI_API_KEY, litellm.api_key).
NO_KEY = "no-key"
REASONING_EFFORT = {"off": "none", "on": "medium"}  # thinking "default" sends nothing
BLOCKED = "The provider blocked the response with a content filter."

_PER_DAY = re.compile(r"per\s*day|insufficient_quota", re.IGNORECASE)
_QUOTA_ID = re.compile(r'"?quotaId"?\s*:\s*"([^"]+)"')
_RETRY_DELAY = re.compile(r'"?retryDelay"?\s*:\s*"(\d+(?:\.\d+)?)s"|retry in (\d+(?:\.\d+)?)\s*s', re.IGNORECASE)


# The loggers of LiteLLM. Each has a handler of its own that writes to the terminal.
LITELLM_LOGGERS = ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy")


class _Notices(logging.Handler):
    """Keeps the lines LiteLLM logs at WARNING and above, instead of writing them to the terminal; the provider
    reports them as ``ProviderNotice`` after each call (runtime.md, Display)."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(record.getMessage())
        except Exception:  # a record that cannot be formatted is dropped, never raised into the model call
            pass

    def drain(self) -> list[str]:
        self.acquire()
        try:
            lines, self.lines = self.lines, []
        finally:
            self.release()
        return lines


NOTICES = _Notices()


def _litellm():
    """LiteLLM, set to make no network call other than model calls: its model list comes from the bundled copy.
    Its log lines go to ``NOTICES``, not to the terminal."""
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["LITELLM_OFFLINE_MODE"] = "true"
    import litellm

    litellm.suppress_debug_info = True
    for name in LITELLM_LOGGERS:
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            if handler is not NOTICES:
                logger.removeHandler(handler)
        if NOTICES not in logger.handlers:
            logger.addHandler(NOTICES)
        logger.propagate = False
    return litellm


class LiteLLMProvider:
    def __init__(
        self,
        profile: Mapping[str, object],
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        on_wait: Callable[[Wait], None] | None = None,
        on_notice: Callable[[ProviderNotice], None] | None = None,
        completion: Callable[..., object] | None = None,
    ):
        """``profile`` is a validated model profile. ``completion`` replaces ``litellm.completion`` in tests.
        ``on_notice`` receives each line LiteLLM logged during a call."""
        self._litellm = _litellm()
        self._profile = dict(profile)
        self._provider = profile["provider"]
        self._model = f"{MODEL_PREFIX[self._provider]}/{profile['name']}"
        self._clock = clock
        self._sleep = sleep
        self._on_wait = on_wait
        self._on_notice = on_notice
        self._completion = completion or self._litellm.completion
        self._sent: deque[float] = deque()

    # Credentials

    def check_credential(self) -> None:
        """Raise ``MissingCredential`` when the variable of the profile is not set. Used at session start."""
        self._api_key()

    def _api_key(self) -> str:
        """Read at each call and never kept (NFR-06)."""
        variable = self._profile["api_key_env"]
        if variable is None:  # only ollama and openai_compatible: the schema requires it for hosted providers
            return NO_KEY
        value = os.environ.get(variable)
        if not value:
            raise MissingCredential(variable)
        return value

    # Calls

    def capabilities(self) -> Capabilities:
        window = self._profile["context_window"]
        tool_calling = None
        if self._provider not in LOCAL_PROVIDERS:  # for a local server LiteLLM would ask it over the network
            try:
                info = self._litellm.get_model_info(self._model)
            except Exception:  # a model missing from LiteLLM's list is unknown, not an error
                info = {}
            tool_calling = info.get("supports_function_calling")
            if window is None:
                window = info.get("max_input_tokens")
        return Capabilities(tool_calling=tool_calling, context_window=window)

    def complete(self, request: Request) -> Response:
        api_key = self._api_key()
        arguments = self._arguments(request, api_key)
        retries = {"rate_limit": 0, "unavailable": 0}
        while True:
            self._pace()
            failure = None
            try:
                raw = self._completion(**arguments)
            except Exception as error:  # classified below; what is not LiteLLM's is re-raised
                failure = self._classify(error, api_key)
                if failure is None:
                    raise
            finally:
                self._report_notices(api_key)
            if failure is None:
                return _response(raw)
            # Raised outside the except clause, so the LiteLLM error and the request it may carry are not chained.
            if isinstance(failure, ProviderError):
                raise failure
            kind, wait, message = failure
            if retries[kind] == 3:
                final = RateLimitExceeded if kind == "rate_limit" else ProviderUnavailable
                raise final(f"{message} (after 3 retries)")
            waits = RATE_LIMIT_WAITS if kind == "rate_limit" else UNAVAILABLE_WAITS
            seconds = wait if wait is not None else waits[retries[kind]]
            retries[kind] += 1
            self._wait(Wait(reason=kind, attempt=retries[kind], seconds=seconds))

    def _report_notices(self, api_key: str) -> None:
        for line in NOTICES.drain():
            if self._on_notice is not None:
                self._on_notice(ProviderNotice(_scrub(line, api_key)))

    def _pace(self) -> None:
        """No window of one minute holds more than ``requests_per_minute`` calls; retries count. Records the send."""
        limit = self._profile["requests_per_minute"]
        if limit is None:
            return
        now = self._clock()
        while self._sent and now - self._sent[0] >= PACING_WINDOW:
            self._sent.popleft()
        if len(self._sent) >= limit:
            self._wait(Wait(reason="pacing", attempt=0, seconds=self._sent[0] + PACING_WINDOW - now))
            self._sent.popleft()
        self._sent.append(self._clock())

    def _wait(self, wait: Wait) -> None:
        if self._on_wait is not None:
            self._on_wait(wait)
        self._sleep(wait.seconds)

    def _arguments(self, request: Request, api_key: str) -> dict[str, object]:
        arguments: dict[str, object] = {
            "model": self._model,
            "messages": _messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "timeout": request.timeout,
            "num_retries": 0,  # the retries are ours: LiteLLM's and the OpenAI SDK's would multiply them
            "max_retries": 0,
            "drop_params": True,  # a provider that does not accept a setting ignores it
            "api_key": api_key,
        }
        if self._profile["base_url"] is not None:
            arguments["api_base"] = self._profile["base_url"]
        if request.tools:
            arguments["tools"] = [
                {
                    "type": "function",
                    "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
                }
                for tool in request.tools
            ]
        if request.thinking in REASONING_EFFORT:
            arguments["reasoning_effort"] = REASONING_EFFORT[request.thinking]
        if self._provider == "ollama" and request.context_window is not None:
            arguments["num_ctx"] = request.context_window  # into the options of /api/chat
        return arguments

    def _classify(self, error: Exception, api_key: str):
        """None for an error that is not LiteLLM's; ``(kind, wait, message)`` for a retry of kind ``rate_limit`` or
        ``unavailable``; otherwise the ``ProviderError`` to raise."""
        import openai  # a dependency of LiteLLM, whose API errors all derive from openai.APIError

        lite = self._litellm
        if not isinstance(error, openai.APIError):
            return None
        message = _scrub(str(error), api_key)
        if isinstance(error, lite.ContextWindowExceededError):
            return ContextWindowExceeded(message)
        if isinstance(error, lite.exceptions.PaymentRequiredError):
            return QuotaExhausted(f"Quota exhausted: {message}")
        if isinstance(error, lite.RateLimitError):
            wait = _indicated_wait(error)
            if _PER_DAY.search(str(error)) or (wait is not None and wait > QUOTA_WAIT):
                quota = _QUOTA_ID.search(str(error))
                return QuotaExhausted(f"Quota exhausted: {quota.group(1) if quota else message}")
            return "rate_limit", wait, f"Rate limit: {message}"
        if isinstance(error, lite.AuthenticationError | lite.PermissionDeniedError):
            variable = self._profile["api_key_env"]
            # The provider message is left out: some providers echo part of the key.
            named = f"the API key in {variable}" if variable else "the request: the profile has no api_key_env"
            return AuthenticationRejected(f"The provider rejected {named}.", variable)
        if isinstance(error, lite.ContentPolicyViolationError):
            return InvalidRequest(f"{BLOCKED} {message}")
        if isinstance(
            error,
            lite.Timeout
            | lite.APIConnectionError
            | lite.InternalServerError
            | lite.ServiceUnavailableError
            | lite.BadGatewayError,
        ):
            return "unavailable", None, f"Provider unavailable: {message}"
        status = getattr(error, "status_code", None)
        if isinstance(error, lite.APIError) and isinstance(status, int) and status >= 500:
            return "unavailable", None, f"Provider unavailable: {message}"
        return InvalidRequest(f"Invalid request: {message}")


def _scrub(text: str, api_key: str) -> str:
    if api_key != NO_KEY:
        text = text.replace(api_key, "***")
    return text


def _indicated_wait(error: Exception) -> float | None:
    """Seconds the provider asks to wait: a ``retry-after`` header, or Gemini's ``retryDelay`` in the message."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or {}
    for name, scale in (("retry-after-ms", 1000), ("retry-after", 1)):
        value = headers.get(name)
        if value is not None:
            try:
                return float(value) / scale
            except ValueError:
                pass
    match = _RETRY_DELAY.search(str(error))
    if match:
        return float(match.group(1) or match.group(2))
    return None


def _messages(messages: tuple[Message, ...]) -> list[dict[str, object]]:
    """OpenAI format. The state message, last and with the user role, is merged into a preceding user message."""
    result: list[dict[str, object]] = []
    for message in messages:
        item: dict[str, object] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            item["content"] = message.content or None
            item["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(dict(call.arguments))},
                }
                for call in message.tool_calls
            ]
        if message.tool_call_id is not None:
            item["tool_call_id"] = message.tool_call_id
        result.append(item)
    if len(result) >= 2 and result[-1]["role"] == "user" and result[-2]["role"] == "user":
        state = result.pop()
        result[-1] = {**result[-1], "content": f"{result[-1]['content']}\n\n{state['content']}"}
    return result


def _response(raw) -> Response:
    choice = raw.choices[0]
    message = choice.message
    text = message.content or ""
    calls = tuple(_tool_call(call, index) for index, call in enumerate(message.tool_calls or ()))
    reason = choice.finish_reason
    if reason == "content_filter" and not text and not calls:
        raise InvalidRequest(BLOCKED)
    if reason == "length":
        finish = "length"
    else:
        finish = "tool_calls" if calls else "stop"
    usage = getattr(raw, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", None)
    reported = Usage(input_tokens, getattr(usage, "completion_tokens", None) or 0) if input_tokens else None
    return Response(
        text=text,
        tool_calls=calls,
        finish_reason=finish,
        thinking=getattr(message, "reasoning_content", None) or None,
        usage=reported,
    )


def _tool_call(call, index: int) -> ToolCall:
    raw = call.function.arguments
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        arguments, invalid = {}, None
    else:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            arguments, invalid = parsed, None
        else:
            arguments, invalid = {}, raw if isinstance(raw, str) else json.dumps(raw)
    # The ID is kept verbatim: for Gemini 3 it carries the thought signature that must come back with the call.
    return ToolCall(
        id=call.id or f"call_{index}", name=call.function.name or "", arguments=arguments, invalid_arguments=invalid
    )
