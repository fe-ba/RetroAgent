"""Verbose output of a scripted turn (runtime.md, Display): each tool call with its arguments, outcome and duration,
each model call with its token usage, each retry and each wait.

Durations, characters and tokens depend on the machine and on the path of the project; they are masked before the
text is compared.
"""

import io
import re

from fixtures.agent_session import answer, call, calls
from rich.console import Console

from retroagent.cli.interactive import Shell
from retroagent.llm import ContextWindowExceeded, FakeProvider, Wait

EXPECTED = """\
retry: the provider refused the context as too long; freeing context and calling again
wait 4.0 s: rate limited by the provider, retry 1
model call 2: <n> characters sent, <n> input and <n> output tokens, <s>, finish tool_calls
tool memory__get_risks {}: ok, <s>
tool git__read_file {"path": "nowhere.py"}: error invalid_argument, <s>
model call 3: <n> characters sent, <n> input and <n> output tokens, <s>, finish stop
Done.
"""

QUIET = """\
memory__get_risks: ok
git__read_file: error invalid_argument
Done.
"""


class Waiting(FakeProvider):
    """Reports a wait of the adapter before its second call, as LiteLLMProvider does before a retry."""

    def __init__(self, session, script):
        super().__init__(script)
        self.session = session

    def complete(self, request):
        if len(self.requests) == 1:
            self.session.on_wait(Wait("rate_limit", 1, 4.0))
        return super().complete(request)


def script():
    return [
        ContextWindowExceeded("too long"),
        calls(call("memory__get_risks"), call("git__read_file", {"path": "nowhere.py"})),
        answer("Done."),
    ]


def mask(text: str) -> str:
    text = re.sub(r", \d+\.\d s", ", <s>", text)
    return re.sub(r"[\d,]+ (characters sent|input and|output tokens)", r"<n> \1", text)


def run(agent, verbose: bool) -> str:
    out = Console(file=io.StringIO(), record=True, width=300, color_system=None)
    agent.provider = Waiting(agent, script())
    Shell(agent, out, out, verbose=verbose, render_markdown=False).handle("Read the risks and nowhere.py.")
    return out.export_text()


def test_verbose_output_of_a_scripted_turn(agent):
    assert mask(run(agent, verbose=True)) == EXPECTED


def test_without_verbose_only_the_tool_calls_and_the_answer(agent):
    assert run(agent, verbose=False) == QUIET
