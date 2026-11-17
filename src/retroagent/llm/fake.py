"""``FakeProvider``: scripted responses in order, every request recorded (spec/llm-providers.md, Implementations).

Each item of the script is a ``Response`` to return or an exception to raise. The usage it reports is the usage
of the scripted response when that is set, otherwise the result of the ``usage`` function; the default reports the
characters sent and received divided by 4, so the truncation guard sees an honest provider. A test that needs a
provider which drops context passes, for example, ``usage=lambda request, response:
Usage(request_characters(request) // 16, 1)``, a quarter of the estimate (SC-19).
"""

import dataclasses
import json
from collections.abc import Callable, Iterable

from retroagent.llm.provider import Capabilities, Request, Response, Usage, request_characters

UsageFunction = Callable[[Request, Response], Usage | None]
TOOL_CALLING = Capabilities(tool_calling=True, context_window=None)


def received_characters(response: Response) -> int:
    return len(response.text) + sum(len(call.name) + len(json.dumps(call.arguments)) for call in response.tool_calls)


def estimated_usage(request: Request, response: Response) -> Usage:
    return Usage(input_tokens=request_characters(request) // 4, output_tokens=received_characters(response) // 4)


class FakeProvider:
    def __init__(
        self,
        script: Iterable[Response | BaseException] = (),
        *,
        capabilities: Capabilities = TOOL_CALLING,
        usage: UsageFunction = estimated_usage,
    ):
        self._script = list(script)
        self._capabilities = capabilities
        self._usage = usage
        self.requests: list[Request] = []

    def complete(self, request: Request) -> Response:
        self.requests.append(request)
        if not self._script:
            raise AssertionError(f"FakeProvider: the script has no item for call {len(self.requests)}")
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if item.usage is not None:
            return item
        return dataclasses.replace(item, usage=self._usage(request, item))

    def capabilities(self) -> Capabilities:
        return self._capabilities

    @property
    def remaining(self) -> int:
        """Items of the script not used yet."""
        return len(self._script)
