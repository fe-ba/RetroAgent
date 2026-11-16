"""Contract tests of LiteLLMProvider against real models (spec/llm-providers.md, Testing).

They call a real model, so they carry the marker ``model``, which ``pyproject.toml`` deselects: a plain ``pytest``
never runs them, also when a key is set. Run them on purpose, for example:

    pytest -m model tests/contract/test_llm_contract.py -k google

The profiles are those of build-plan.md, "Models for development". Each test makes 2 model calls: one that must
answer with a tool call, and one that sends the tool result and must answer with a message. A test is skipped when
its credential or its local server is missing.
"""

import os

import httpx
import pytest

from retroagent.config.schema import validate
from retroagent.llm import Message, ToolDefinition, request_from_profile
from retroagent.llm.litellm_provider import LiteLLMProvider

pytestmark = pytest.mark.model

PROFILES = validate(
    "user",
    {
        "models": {
            "google": {
                "provider": "google",
                "name": "gemini-3.1-flash-lite",
                "api_key_env": "GEMINI_API_KEY",
                "requests_per_minute": 12,
            },
            "ollama": {
                "provider": "ollama",
                "name": "qwen3.5:4b",
                "base_url": "http://localhost:11434",
                "thinking": "off",
                "context_window": 32768,
                "timeout": 600,  # a 4B model on CPU reads a new context slowly
            },
        }
    },
)[1]

TOOL = ToolDefinition(
    "memory__get_suite",
    "Return the regression suite with the given ID, with its number of test cases.",
    {"type": "object", "properties": {"suite_id": {"type": "string"}}, "required": ["suite_id"]},
)
SYSTEM = "You are a testing agent. You read regression suites only with the tool memory__get_suite."
ASK = "How many test cases does suite SUITE-001 have? Use the tool, then answer with the number."


def available(name: str) -> bool:
    profile = PROFILES[name]
    if profile["provider"] == "ollama":
        try:
            httpx.get(f"{profile['base_url']}/api/version", timeout=2).raise_for_status()
        except httpx.HTTPError:
            return False
        return True
    return bool(os.environ.get(profile["api_key_env"]))


@pytest.mark.parametrize("name", sorted(PROFILES))
def test_one_tool_call_and_one_message(name):
    if not available(name):
        pytest.skip(f"no credential or server for the {name} profile")
    profile = PROFILES[name]
    provider = LiteLLMProvider(profile, on_wait=lambda wait: print(f"waiting {wait.seconds:.0f} s: {wait.reason}"))
    assert provider.capabilities().context_window

    messages = [Message("system", SYSTEM), Message("user", ASK)]
    first = provider.complete(request_from_profile(profile, messages, [TOOL]))
    assert first.finish_reason == "tool_calls", first
    (call,) = first.tool_calls
    assert call.name == "memory__get_suite"
    assert call.invalid_arguments is None
    assert call.arguments == {"suite_id": "SUITE-001"}
    assert first.usage is not None and first.usage.input_tokens > 0

    messages += [
        Message("assistant", first.text, tool_calls=first.tool_calls),
        Message("tool", '{"suite_id": "SUITE-001", "test_cases": 7}', tool_call_id=call.id),
        Message("user", "The tool answered. Give the number now."),
    ]
    second = provider.complete(request_from_profile(profile, messages, [TOOL]))
    assert second.finish_reason == "stop", second
    assert second.tool_calls == ()
    assert "7" in second.text
    assert second.usage is not None and second.usage.input_tokens > first.usage.input_tokens
