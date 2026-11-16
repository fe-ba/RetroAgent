"""What LiteLLM really posts to Ollama for an ollama profile, caught at the HTTP layer: no server, no network.

``drop_params=True`` drops what a provider does not accept without an error, and a context size that never reaches
Ollama truncates the context without an error either. So this test lets LiteLLM build the body and reads it.
"""

import functools
import json

import httpx
import pytest

from retroagent.config.schema import validate
from retroagent.llm import Message, ToolDefinition, Usage, request_from_profile
from retroagent.llm.litellm_provider import LiteLLMProvider, _litellm

lite = _litellm()
from litellm.llms.custom_httpx.http_handler import HTTPHandler  # noqa: E402 - after the adapter set LiteLLM offline

PROFILE = validate(
    "user",
    {
        "models": {
            "local": {
                "provider": "ollama",
                "name": "qwen3.5:4b",
                "base_url": "http://localhost:11434",
                "context_window": 32768,
                "thinking": "off",
            }
        }
    },
)[1]["local"]

TOOL = ToolDefinition(
    "memory__get_suite",
    "Read the regression suite.",
    {"type": "object", "properties": {"suite_id": {"type": "string"}}, "required": ["suite_id"]},
)

OLLAMA_ANSWER = {
    "model": "qwen3.5:4b",
    "created_at": "2026-11-16T12:00:00Z",
    "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "memory__get_suite", "arguments": {"suite_id": "SUITE-001"}}}],
    },
    "done": True,
    "done_reason": "stop",
    "prompt_eval_count": 812,
    "eval_count": 21,
}


FOREIGN_KEY = "foreign-key-7f3a9c1e5b2d"  # a key LiteLLM could pick by itself; it must never be sent


def assert_no_foreign_key(requests: list[httpx.Request]) -> None:
    for request in requests:
        assert FOREIGN_KEY not in str(request.url)
        assert FOREIGN_KEY.encode() not in b"".join(name + b": " + value for name, value in request.headers.raw)
        assert FOREIGN_KEY.encode() not in request.content


@pytest.fixture
def posted(monkeypatch):
    """Every HTTP request LiteLLM makes during the test, answered with ``OLLAMA_ANSWER``.

    ``OLLAMA_API_KEY`` and ``litellm.api_key`` hold a recognizable key: LiteLLM reads them for ollama when it is not
    given a key, and the adapter always gives one.
    """
    monkeypatch.setenv("OLLAMA_API_KEY", FOREIGN_KEY)
    monkeypatch.setattr(lite, "api_key", FOREIGN_KEY)
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=OLLAMA_ANSWER)

    client = HTTPHandler(client=httpx.Client(transport=httpx.MockTransport(answer)))
    completion = functools.partial(lite.completion, client=client)
    return requests, LiteLLMProvider(PROFILE, completion=completion)


def test_the_body_posted_to_ollama_has_the_context_size_thinking_off_and_the_tools(posted):
    requests, provider = posted
    messages = [Message("system", "Steering."), Message("user", "Analyze."), Message("user", "State.")]
    response = provider.complete(request_from_profile(PROFILE, messages, [TOOL]))

    (sent,) = requests
    assert sent.method == "POST"
    assert str(sent.url) == "http://localhost:11434/api/chat"
    assert_no_foreign_key(requests)
    body = json.loads(sent.content)
    assert body["model"] == "qwen3.5:4b"
    assert body["options"]["num_ctx"] == 32768
    assert body["options"]["num_predict"] == 4096
    assert body["options"]["temperature"] == 0
    assert body["think"] is False
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "memory__get_suite",
                "description": "Read the regression suite.",
                "parameters": TOOL.parameters,
            },
        }
    ]
    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("system", "Steering."),
        ("user", "Analyze.\n\nState."),
    ]

    (call,) = response.tool_calls
    assert (call.name, dict(call.arguments)) == ("memory__get_suite", {"suite_id": "SUITE-001"})
    assert call.id
    assert response.finish_reason == "tool_calls"
    assert response.usage == Usage(input_tokens=812, output_tokens=21)


def test_a_tool_result_goes_back_to_ollama_with_the_call(posted):
    requests, provider = posted
    first = provider.complete(request_from_profile(PROFILE, [Message("system", "S."), Message("user", "Go.")], [TOOL]))
    (call,) = first.tool_calls
    history = [
        Message("system", "S."),
        Message("user", "Go."),
        Message("assistant", first.text, tool_calls=first.tool_calls),
        Message("tool", '{"suite": "SUITE-001"}', tool_call_id=call.id),
        Message("user", "State."),
    ]
    provider.complete(request_from_profile(PROFILE, history, [TOOL]))
    assert_no_foreign_key(requests)
    body = json.loads(requests[1].content)
    assistant, tool = body["messages"][2], body["messages"][3]
    assert assistant["tool_calls"][0]["function"] == {
        "name": "memory__get_suite",
        "arguments": {"suite_id": "SUITE-001"},
    }
    assert tool["role"] == "tool" and tool["content"] == '{"suite": "SUITE-001"}'
    assert body["options"]["num_ctx"] == 32768
