"""A model profile for tests, and sessions whose model is a ``FakeProvider``.

Every session needs a model profile (runtime.md, Start step 7). The profile of these tests is a local ``ollama``
profile: it needs no credential, and nothing contacts the server unless a model call is made, which tests never do
with it. Sessions that call a model use a ``FakeProvider`` through ``provider_factory``.
"""

from pathlib import Path

from retroagent.llm import FakeProvider, Response, ToolCall

PROFILE = "local"
WINDOW = 32_768
USER_CONFIG = (
    f"model: {PROFILE}\n"
    "models:\n"
    f"  {PROFILE}:\n"
    "    provider: ollama\n"
    "    name: test-model\n"
    "    base_url: http://127.0.0.1:9\n"
    f"    context_window: {WINDOW}\n"
)


def write_user_config(home: Path, extra: str = "") -> None:
    """The user level of a test: the local profile, selected with ``model``, followed by ``extra``."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(USER_CONFIG + extra, encoding="utf-8")


def factory(provider=None):
    """A ``provider_factory`` of ``session.start`` that returns ``provider``, or an empty ``FakeProvider``."""
    chosen = provider if provider is not None else FakeProvider()
    return lambda profile, on_wait: chosen


# Scripts of FakeProvider and what a turn leaves in project memory.

_ids = iter(range(1, 1_000_000))


def call(name: str, arguments: dict | None = None, *, invalid: str | None = None) -> ToolCall:
    """A tool call of the model, with a new ID."""
    return ToolCall(id=f"call-{next(_ids)}", name=name, arguments=arguments or {}, invalid_arguments=invalid)


def calls(*tool_calls: ToolCall, finish_reason: str = "tool_calls") -> Response:
    """A model answer with these tool calls."""
    return Response(text="", tool_calls=tool_calls, finish_reason=finish_reason)


def answer(text: str = "Done.", finish_reason: str = "stop") -> Response:
    """A model answer without tool calls, which ends the turn."""
    return Response(text=text, finish_reason=finish_reason)


def tool_rows(conn, session_id: int) -> list[dict]:
    """The ``tool_call`` rows of a session, in the order they were written."""
    return [
        dict(row) for row in conn.execute("SELECT * FROM tool_call WHERE session_id = ? ORDER BY id", (session_id,))
    ]


def tool_results(conversation) -> dict[str, str]:
    """The content of each tool message of a conversation, by the ID of the call it answers."""
    return {m.tool_call_id: m.content for m in conversation.messages if m.role == "tool"}


class Scripted(FakeProvider):
    """A ``FakeProvider`` whose script may hold functions: ``step(request)`` returns the response, so a later answer
    can use a result the model read before, such as the analysis ID of ``git__analyze_changes``."""

    def complete(self, request):
        if self.remaining and callable(self._script[0]) and not isinstance(self._script[0], BaseException):
            step = self._script.pop(0)
            self._script.insert(0, step(request))
        return super().complete(request)


def result_in(request, call_id: str) -> dict:
    """The result of a tool call as the model received it in ``request``."""
    import json

    return json.loads(next(m.content for m in request.messages if m.role == "tool" and m.tool_call_id == call_id))


def analyze_script(text: str = "The impact is recorded.") -> list:
    """A model that follows the skill ``impact-analysis`` on shop-api: it loads the skill, synchronizes the
    requirements, computes the change set, reads one diff and the requirements, records the impact with every file of
    the change set, registers one risk and answers."""
    changes = call("git__analyze_changes")

    def save_impact(request) -> Response:
        result = result_in(request, changes.id)
        modules: dict[str, list[str]] = {}
        for changed in result["files"]:
            modules.setdefault(changed["path"].split("/")[0], []).append(changed["path"])
        return calls(
            call(
                "memory__save_impact",
                {
                    "analysis_id": result["analysis_id"],
                    "modules": [
                        {"module": name, "files": files, "risk_level": "high", "reason": "Changed in the diff."}
                        for name, files in sorted(modules.items())
                    ],
                    "requirements": [{"requirement_id": "REQ-004", "reason": "Documented change in v1.1."}],
                },
            )
        )

    return [
        calls(call("runtime__load_skill", {"name": "impact-analysis"})),
        calls(call("memory__sync_requirements")),
        calls(changes),
        calls(call("git__get_diff", {"path": "src/shop/pricing.py"})),
        calls(call("memory__get_requirements")),
        save_impact,
        calls(
            call(
                "memory__add_risk",
                {"description": "Two coupons give a wrong total.", "level": "high", "requirement_ids": ["REQ-004"]},
            )
        ),
        answer(text),
    ]
