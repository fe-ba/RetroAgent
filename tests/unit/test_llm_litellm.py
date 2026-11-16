"""LiteLLMProvider with ``litellm.completion`` replaced by a stub, and a fake clock: no model, no network, no wait.

These tests check what the adapter gives to LiteLLM and how it reads what LiteLLM returns. What LiteLLM sends to
Ollama is checked at the HTTP layer in ``test_llm_ollama_request.py``.
"""

import re
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from retroagent.config.schema import validate
from retroagent.llm import (
    AuthenticationRejected,
    Capabilities,
    ContextWindowExceeded,
    InvalidRequest,
    Message,
    MissingCredential,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimitExceeded,
    ToolCall,
    ToolDefinition,
    Usage,
    Wait,
    request_from_profile,
)
from retroagent.llm.litellm_provider import NO_KEY, LiteLLMProvider, _litellm

lite = _litellm()  # through the adapter, so the test process makes no network call either

KEY_VARIABLE = "RETRO_TEST_MODEL_KEY"
KEY_VALUE = "sk-test-0123456789abcdef"
SRC = Path(__file__).resolve().parents[2] / "src" / "retroagent"


def profile(**keys):
    keys = {"provider": "google", "name": "gemini-3.1-flash-lite", "api_key_env": KEY_VARIABLE, **keys}
    keys = {name: value for name, value in keys.items() if value is not None}
    return validate("user", {"models": {"p": keys}})[1]["p"]


OLLAMA = {"provider": "ollama", "name": "qwen3.5:4b", "api_key_env": None, "base_url": "http://localhost:11434"}
OLLAMA_PROFILE = {**OLLAMA, "context_window": 32768}


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Stub:
    """Replaces ``litellm.completion``: records the keyword arguments and returns or raises scripted outcomes."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def model_response(content="Done.", tool_calls=None, finish_reason="stop", usage=(120, 8), reasoning=None):
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = [
            {"id": id, "type": "function", "function": {"name": name, "arguments": arguments}}
            for id, name, arguments in tool_calls
        ]
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    data = {"choices": [{"message": message, "finish_reason": finish_reason}]}
    if usage is not None:
        data["usage"] = {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}
    return lite.ModelResponse(**data)


def provider(stub, clock=None, waits=None, **keys):
    clock = clock or Clock()
    return LiteLLMProvider(
        profile(**keys),
        clock=clock,
        sleep=clock.sleep,
        on_wait=None if waits is None else waits.append,
        completion=stub,
    )


def request(messages=None, tools=(), **keys):
    messages = messages or [Message("system", "Steering."), Message("user", "State.")]
    return request_from_profile(profile(**keys), messages, tools)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv(KEY_VARIABLE, KEY_VALUE)


def error(cls, message="provider says no", **extra):
    return cls(message=message, model="gemini/gemini-3.1-flash-lite", llm_provider="gemini", **extra)


def rate_limit(message="429 Resource exhausted", headers=None):
    response = httpx.Response(429, headers=headers or {}, request=httpx.Request("POST", "https://example.invalid"))
    return error(lite.RateLimitError, message, response=response)


# Translation of a request


def test_request_without_tools():
    stub = Stub(model_response())
    provider(stub).complete(request())
    assert stub.calls == [
        {
            "model": "gemini/gemini-3.1-flash-lite",
            "messages": [{"role": "system", "content": "Steering."}, {"role": "user", "content": "State."}],
            "temperature": 0,
            "max_tokens": 4096,
            "timeout": 120,
            "num_retries": 0,
            "max_retries": 0,
            "drop_params": True,
            "api_key": KEY_VALUE,
        }
    ]


def test_request_with_tools_tool_calls_and_tool_results():
    call = ToolCall(id="call_1__thought__c2ln", name="git__diff", arguments={"base": "v1.0"})
    tool = ToolDefinition("git__diff", "Diff two versions.", {"type": "object", "properties": {"base": {}}})
    messages = [
        Message("system", "Steering."),
        Message("user", "Analyze."),
        Message("assistant", "", tool_calls=(call,)),
        Message("tool", '{"files": 2}', tool_call_id="call_1__thought__c2ln"),
        Message("user", "State."),
    ]
    stub = Stub(model_response())
    provider(stub, base_url="https://proxy.example.invalid").complete(request(messages, [tool]))
    sent = stub.calls[0]
    assert sent["messages"][2:] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1__thought__c2ln",
                    "type": "function",
                    "function": {"name": "git__diff", "arguments": '{"base": "v1.0"}'},
                }
            ],
        },
        {"role": "tool", "content": '{"files": 2}', "tool_call_id": "call_1__thought__c2ln"},
        {"role": "user", "content": "State."},
    ]
    assert sent["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "git__diff",
                "description": "Diff two versions.",
                "parameters": {"type": "object", "properties": {"base": {}}},
            },
        }
    ]
    assert sent["api_base"] == "https://proxy.example.invalid"


@pytest.mark.parametrize(
    ("keys", "model"),
    [
        ({"provider": "anthropic", "name": "m"}, "anthropic/m"),
        ({"provider": "openai", "name": "m"}, "openai/m"),
        ({"provider": "xai", "name": "m"}, "xai/m"),
        ({"provider": "google", "name": "m"}, "gemini/m"),
        (OLLAMA_PROFILE, "ollama_chat/qwen3.5:4b"),
        (
            {
                "provider": "openai_compatible",
                "name": "m",
                "base_url": "http://localhost:1234/v1",
                "context_window": 8192,
            },
            "openai/m",
        ),
    ],
)
def test_model_prefix_of_every_provider(keys, model):
    stub = Stub(model_response())
    provider(stub, **keys).complete(request())
    assert stub.calls[0]["model"] == model


def test_ollama_gets_the_context_size_its_base_url_and_the_placeholder_key():
    stub = Stub(model_response())
    provider(stub, **OLLAMA_PROFILE).complete(request(**OLLAMA_PROFILE))
    sent = stub.calls[0]
    assert sent["num_ctx"] == 32768
    assert sent["api_base"] == "http://localhost:11434"
    assert sent["api_key"] == NO_KEY


def test_other_providers_get_no_context_size():
    stub = Stub(model_response())
    provider(stub, context_window=32768).complete(request(context_window=32768))
    assert "num_ctx" not in stub.calls[0]


def test_openai_compatible_without_a_variable_sends_a_placeholder_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    keys = {
        "provider": "openai_compatible",
        "name": "m",
        "base_url": "http://localhost:1234/v1",
        "context_window": 8192,
        "api_key_env": None,
    }
    stub = Stub(model_response())
    provider(stub, **keys).complete(request())
    assert stub.calls[0]["api_key"] == NO_KEY


@pytest.mark.parametrize(("thinking", "effort"), [("default", None), ("off", "none"), ("on", "medium")])
def test_thinking_setting(thinking, effort):
    stub = Stub(model_response())
    provider(stub).complete(request(thinking=thinking))
    assert stub.calls[0].get("reasoning_effort") == effort


def test_state_message_is_merged_into_a_preceding_user_message():
    messages = [Message("system", "Steering."), Message("user", "Analyze v1.0 v1.1."), Message("user", "State.")]
    stub = Stub(model_response())
    provider(stub).complete(request(messages))
    assert stub.calls[0]["messages"] == [
        {"role": "system", "content": "Steering."},
        {"role": "user", "content": "Analyze v1.0 v1.1.\n\nState."},
    ]
    assert messages[1].content == "Analyze v1.0 v1.1."


def test_state_message_after_a_tool_result_is_not_merged():
    messages = [
        Message("system", "Steering."),
        Message("assistant", "", tool_calls=(ToolCall("c1", "memory__get_suite", {}),)),
        Message("tool", "{}", tool_call_id="c1"),
        Message("user", "State."),
    ]
    stub = Stub(model_response())
    provider(stub).complete(request(messages))
    assert [m["role"] for m in stub.calls[0]["messages"]] == ["system", "assistant", "tool", "user"]


# Translation of a response


def test_response_with_text_thinking_and_usage():
    stub = Stub(model_response("The change touches the cart.", reasoning="Look at app/cart.py.", usage=(900, 40)))
    response = provider(stub).complete(request())
    assert response.text == "The change touches the cart."
    assert response.tool_calls == ()
    assert response.finish_reason == "stop"
    assert response.thinking == "Look at app/cart.py."
    assert response.usage == Usage(input_tokens=900, output_tokens=40)


def test_response_with_tool_calls():
    calls = [("c1", "git__diff", '{"base": "v1.0", "candidate": "v1.1"}'), ("c2", "memory__get_suite", "")]
    stub = Stub(model_response(None, tool_calls=calls, finish_reason="tool_calls"))
    response = provider(stub).complete(request())
    assert response.text == ""
    assert response.finish_reason == "tool_calls"
    assert response.thinking is None
    assert response.tool_calls == (
        ToolCall("c1", "git__diff", {"base": "v1.0", "candidate": "v1.1"}),
        ToolCall("c2", "memory__get_suite", {}),
    )


def test_tool_calls_with_finish_reason_stop_are_reported_as_tool_calls():
    stub = Stub(model_response(None, tool_calls=[("c1", "memory__get_suite", "{}")], finish_reason="stop"))
    assert provider(stub).complete(request()).finish_reason == "tool_calls"


@pytest.mark.parametrize("arguments", ['{"base": "v1.', "[1, 2]", "not json"])
def test_invalid_tool_arguments_are_kept_raw(arguments):
    stub = Stub(model_response(None, tool_calls=[("c1", "git__diff", arguments)], finish_reason="tool_calls"))
    (call,) = provider(stub).complete(request()).tool_calls
    assert call == ToolCall("c1", "git__diff", {}, invalid_arguments=arguments)


def test_a_response_cut_by_length_keeps_its_reason():
    stub = Stub(model_response(None, tool_calls=[("c1", "git__diff", '{"base": "v1.')], finish_reason="length"))
    response = provider(stub).complete(request())
    assert response.finish_reason == "length"
    assert response.tool_calls[0].invalid_arguments == '{"base": "v1.'
    stub = Stub(model_response("Partial answer", finish_reason="length"))
    assert provider(stub).complete(request()).finish_reason == "length"


def test_usage_not_reported_is_null():
    assert provider(Stub(model_response(usage=None))).complete(request()).usage is None
    assert provider(Stub(model_response(usage=(0, 0)))).complete(request()).usage is None


def test_a_response_blocked_by_a_content_filter_is_an_invalid_request():
    stub = Stub(model_response(None, finish_reason="content_filter"))
    with pytest.raises(InvalidRequest, match="blocked"):
        provider(stub).complete(request())


def test_a_content_filter_with_text_is_a_normal_answer():
    stub = Stub(model_response("Partial.", finish_reason="content_filter"))
    assert provider(stub).complete(request()).finish_reason == "stop"


# Errors and retries


def run(*outcomes, **keys):
    """Complete one request; returns the stub, the waits seen in verbose mode, and the sleeps, and the result."""
    stub, clock, waits = Stub(*outcomes), Clock(), []
    try:
        result = provider(stub, clock, waits, **keys).complete(request())
    except Exception as raised:  # the test inspects it
        result = raised
    return stub, waits, clock.sleeps, result


def test_rate_limit_waits_the_time_of_the_retry_after_header():
    stub, waits, sleeps, result = run(rate_limit(headers={"retry-after": "7"}), model_response())
    assert result.text == "Done."
    assert sleeps == [7]
    assert waits == [Wait("rate_limit", 1, 7)]
    assert len(stub.calls) == 2


def test_rate_limit_waits_the_retry_delay_of_gemini():
    message = (
        'geminiException - {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [{"@type": '
        '"type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": '
        '"GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}, {"@type": '
        '"type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "27s"}]}}'
    )
    stub, waits, sleeps, result = run(rate_limit(message), model_response())
    assert sleeps == [27]
    assert len(stub.calls) == 2


def test_rate_limit_without_a_hint_waits_15_30_60_then_fails():
    stub, waits, sleeps, result = run(rate_limit(), rate_limit(), rate_limit(), rate_limit())
    assert isinstance(result, RateLimitExceeded)
    assert sleeps == [15, 30, 60]
    assert [w.attempt for w in waits] == [1, 2, 3]
    assert len(stub.calls) == 4


def test_a_daily_quota_is_not_retried_and_named():
    message = (
        '{"error": {"code": 429, "details": [{"violations": [{"quotaId": '
        '"GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}, {"retryDelay": "20s"}]}}'
    )
    stub, waits, sleeps, result = run(rate_limit(message))
    assert isinstance(result, QuotaExhausted)
    assert "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in str(result)
    assert sleeps == []
    assert len(stub.calls) == 1


@pytest.mark.parametrize(
    "outcome",
    [
        rate_limit(headers={"retry-after": "3600"}),
        rate_limit("You exceeded your current quota: insufficient_quota"),
        rate_limit("Limit of requests per day reached"),
        error(lite.exceptions.PaymentRequiredError, "credit balance too low"),
    ],
)
def test_limits_that_do_not_clear_within_minutes_are_an_exhausted_quota(outcome):
    stub, waits, sleeps, result = run(outcome)
    assert isinstance(result, QuotaExhausted)
    assert sleeps == []
    assert len(stub.calls) == 1


@pytest.mark.parametrize(
    "make",
    [
        lambda: error(lite.Timeout),
        lambda: error(lite.APIConnectionError),
        lambda: error(lite.InternalServerError),
        lambda: error(lite.ServiceUnavailableError),
        lambda: error(lite.BadGatewayError),
        lambda: error(lite.APIError, status_code=503),
    ],
)
def test_network_server_and_timeout_errors_wait_2_4_8_then_fail(make):
    stub, waits, sleeps, result = run(make(), make(), make(), make())
    assert isinstance(result, ProviderUnavailable)
    assert sleeps == [2, 4, 8]
    assert [w.reason for w in waits] == ["unavailable"] * 3
    assert len(stub.calls) == 4


def test_a_call_that_succeeds_after_a_retry_returns_its_response():
    stub, waits, sleeps, result = run(error(lite.APIConnectionError), model_response("Recovered."))
    assert result.text == "Recovered."
    assert sleeps == [2]


@pytest.mark.parametrize("cls", ["AuthenticationError", "PermissionDeniedError"])
def test_a_rejected_credential_names_the_variable_and_never_its_value(cls):
    response = httpx.Response(401, request=httpx.Request("POST", "https://example.invalid"))
    extra = {"response": response} if cls == "PermissionDeniedError" else {}
    rejected = error(getattr(lite, cls), f"Incorrect API key provided: {KEY_VALUE}", **extra)
    stub, waits, sleeps, result = run(rejected)
    assert isinstance(result, AuthenticationRejected)
    assert result.variable == KEY_VARIABLE
    assert KEY_VARIABLE in str(result)
    for text in (str(result), repr(result), repr(result.args), repr(vars(result))):
        assert KEY_VALUE not in text
    assert result.__cause__ is None and result.__context__ is None
    assert sleeps == []
    assert len(stub.calls) == 1


def test_context_window_exceeded_is_left_to_the_turn():
    stub, waits, sleeps, result = run(error(lite.ContextWindowExceededError, "prompt is too long"))
    assert isinstance(result, ContextWindowExceeded)
    assert sleeps == []
    assert len(stub.calls) == 1


@pytest.mark.parametrize("cls", ["BadRequestError", "NotFoundError"])
def test_invalid_request_keeps_the_provider_message(cls):
    stub, waits, sleeps, result = run(error(getattr(lite, cls), "model gemini-9 not found"))
    assert isinstance(result, InvalidRequest)
    assert "model gemini-9 not found" in str(result)
    assert sleeps == []
    assert len(stub.calls) == 1


def test_a_content_policy_error_is_an_invalid_request():
    stub, waits, sleeps, result = run(error(lite.ContentPolicyViolationError, "The response was blocked."))
    assert isinstance(result, InvalidRequest)
    assert "blocked" in str(result)


def test_provider_messages_never_carry_the_key():
    stub, waits, sleeps, result = run(error(lite.BadRequestError, f"bad request with key={KEY_VALUE}"))
    assert isinstance(result, InvalidRequest)
    assert KEY_VALUE not in str(result)
    assert result.__context__ is None


def test_errors_that_are_not_litellm_errors_are_not_classified():
    stub, waits, sleeps, result = run(ValueError("a bug"))
    assert isinstance(result, ValueError)
    assert len(stub.calls) == 1


# Pacing


def test_pacing_spaces_calls_to_stay_under_requests_per_minute():
    stub, clock, waits = Stub(*[model_response()] * 3), Clock(), []
    adapter = provider(stub, clock, waits, requests_per_minute=2)
    adapter.complete(request())
    clock.now += 10
    adapter.complete(request())
    adapter.complete(request())
    assert clock.sleeps == [50]
    assert waits == [Wait("pacing", 0, 50)]
    assert len(stub.calls) == 3


def test_retries_count_for_pacing():
    stub, clock = Stub(error(lite.APIConnectionError), model_response(), model_response()), Clock()
    adapter = provider(stub, clock, requests_per_minute=2)
    adapter.complete(request())  # sent at 1000, retried at 1002
    adapter.complete(request())  # the window holds 2 calls until 1060
    assert clock.sleeps == [2, 58]


def test_no_pacing_without_requests_per_minute():
    stub, clock = Stub(*[model_response()] * 20), Clock()
    adapter = provider(stub, clock)
    for _ in range(20):
        adapter.complete(request())
    assert clock.sleeps == []


# Credentials


@pytest.mark.parametrize("value", [None, ""])
def test_a_missing_credential_names_the_variable_and_sends_nothing(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(KEY_VARIABLE)
    else:
        monkeypatch.setenv(KEY_VARIABLE, value)
    stub = Stub(model_response())
    adapter = provider(stub)
    with pytest.raises(MissingCredential) as raised:
        adapter.complete(request())
    assert raised.value.variable == KEY_VARIABLE and KEY_VARIABLE in str(raised.value)
    with pytest.raises(MissingCredential):
        adapter.check_credential()
    assert stub.calls == []


def test_the_credential_is_read_at_each_call_and_never_kept(monkeypatch):
    stub = Stub(model_response(), model_response())
    adapter = provider(stub)
    adapter.check_credential()
    adapter.complete(request())
    monkeypatch.setenv(KEY_VARIABLE, "sk-rotated")
    adapter.complete(request())
    assert [call["api_key"] for call in stub.calls] == [KEY_VALUE, "sk-rotated"]
    assert KEY_VALUE not in repr(vars(adapter)) and "sk-rotated" not in repr(vars(adapter))


# Capabilities


def test_capabilities_from_the_bundled_model_list():
    assert provider(Stub()).capabilities() == Capabilities(tool_calling=True, context_window=1048576)


def test_the_context_window_of_the_profile_takes_precedence():
    assert provider(Stub(), context_window=32768).capabilities().context_window == 32768


def test_an_unknown_model_has_unknown_capabilities():
    assert provider(Stub(), name="no-such-model-zz").capabilities() == Capabilities(None, None)


def test_a_local_server_is_not_asked(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("capabilities of a local server must not reach the network")

    monkeypatch.setattr(lite, "get_model_info", refuse)
    assert provider(Stub(), **OLLAMA_PROFILE).capabilities() == Capabilities(None, 32768)


# Boundaries


def test_no_module_outside_llm_imports_litellm():
    pattern = re.compile(r"^\s*(import|from)\s+litellm\b", re.MULTILINE)
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if path.relative_to(SRC).parts[0] not in ("llm", "resources") and pattern.search(path.read_text("utf-8"))
    ]
    assert offenders == []


def test_importing_the_llm_package_does_not_load_litellm():
    code = "import sys, retroagent.llm; print('litellm' in sys.modules)"
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert output.strip() == "False"
