"""FakeProvider: scripted responses in order, recorded requests, scripted errors and usage."""

import pytest

from retroagent.llm import (
    Capabilities,
    ContextWindowExceeded,
    FakeProvider,
    Message,
    Request,
    Response,
    ToolCall,
    ToolDefinition,
    Usage,
)
from retroagent.llm.provider import request_characters


def request(text="hello", tools=()):
    return Request(
        messages=(Message("system", "rules"), Message("user", text)),
        tools=tuple(tools),
        temperature=0,
        max_output_tokens=100,
        context_window=None,
        thinking="default",
        timeout=10,
    )


def test_responses_come_in_order_and_every_request_is_recorded():
    call = ToolCall(id="c1", name="git__diff", arguments={"base": "v1.0"})
    fake = FakeProvider([Response("", (call,), "tool_calls"), Response("done")])
    first, second = request("one"), request("two")
    assert fake.complete(first).tool_calls == (call,)
    assert fake.complete(second).text == "done"
    assert fake.requests == [first, second]
    assert fake.remaining == 0


def test_an_exhausted_script_fails_the_test():
    fake = FakeProvider([Response("only")])
    fake.complete(request())
    with pytest.raises(AssertionError, match="call 2"):
        fake.complete(request())
    assert len(fake.requests) == 2


def test_scripted_errors_are_raised_in_their_place():
    fake = FakeProvider([ContextWindowExceeded("too long"), Response("after")])
    with pytest.raises(ContextWindowExceeded):
        fake.complete(request())
    assert fake.complete(request()).text == "after"
    assert len(fake.requests) == 2


def test_default_usage_is_the_characters_divided_by_4():
    tool = ToolDefinition("memory__get_suite", "Read the suite.", {"type": "object", "properties": {}})
    sent = request("x" * 400, tools=[tool])
    response = FakeProvider([Response("y" * 40)]).complete(sent)
    assert response.usage == Usage(input_tokens=request_characters(sent) // 4, output_tokens=10)
    assert request_characters(sent) == len("rules") + 400 + len("memory__get_suite") + len("Read the suite.") + len(
        '{"type": "object", "properties": {}}'
    )


def test_usage_of_a_scripted_response_wins():
    fake = FakeProvider([Response("a", usage=Usage(7, 3))])
    assert fake.complete(request()).usage == Usage(7, 3)


def test_usage_function_can_report_fewer_tokens_than_were_sent():
    def quarter(sent, response):
        return Usage(request_characters(sent) // 16, 1)

    sent = request("z" * 4000)
    fake = FakeProvider([Response("ok")], usage=quarter)
    assert fake.complete(sent).usage.input_tokens == request_characters(sent) // 16


def test_usage_function_can_report_nothing():
    fake = FakeProvider([Response("ok")], usage=lambda sent, response: None)
    assert fake.complete(request()).usage is None


def test_capabilities_are_scripted():
    assert FakeProvider().capabilities() == Capabilities(tool_calling=True, context_window=None)
    assert FakeProvider(capabilities=Capabilities(None, 8192)).capabilities().context_window == 8192
