"""``/analyze [base] [candidate]`` with a model that follows the skill ``impact-analysis`` (runtime.md, Model commands).

The model command empties the conversation, calls ``runtime.set_versions`` first when refs are given, sends its fixed
template and exposes only the tools of the step ``analyze``.
"""

import json

import pytest
from fixtures.agent_session import Scripted, analyze_script, tool_rows
from fixtures.tool_definitions import step_tool_names

from retroagent.cli.main import main
from retroagent.llm import FakeProvider, Message
from retroagent.runtime import commands
from retroagent.servers.errors import ToolError

ANSWER = "Analysis recorded: pricing and discounts are impacted."


def analyze_tools(session) -> list[str]:
    return step_tool_names(session.known_tools(), "analyze")


def first_user_message(request) -> str:
    return next(m.content for m in request.messages if m.role == "user")


def impact_of(conn, analysis_id: int) -> tuple[list[str], list[str], list[str]]:
    """The modules, the impacted requirements and the requirements judged not impacted of an analysis."""
    modules = [r["module"] for r in conn.execute("SELECT module FROM analysis_module WHERE analysis_id = ?",
                                                 (analysis_id,))]  # fmt: skip
    decided = [
        [r["requirement_id"] for r in conn.execute(f"SELECT requirement_id FROM {table} WHERE analysis_id = ?"
                                                   " ORDER BY requirement_id", (analysis_id,))]
        for table in ("analysis_requirement", "analysis_requirement_not_impacted")
    ]  # fmt: skip
    return modules, *decided


def test_analyze_with_refs_sets_the_versions_then_sends_the_template_with_the_tools_of_the_step(agent):
    provider = Scripted(analyze_script(ANSWER))
    agent.provider = provider
    agent.conversation.messages = [Message(role="user", content="An earlier message."), Message("assistant", "Yes.")]
    agent.conversation.loaded_skill = "test-design"

    result = commands.analyze(agent, ("v1.1", "v1.2"))

    assert result.text == ANSWER and provider.remaining == 0
    first = provider.requests[0]
    assert first_user_message(first) == commands.ANALYZE
    assert "An earlier message." not in json.dumps([m.content for m in first.messages])
    for request in provider.requests:
        assert sorted(tool.name for tool in request.tools) == analyze_tools(agent)
        assert not any(tool.name.startswith("test_runner__") for tool in request.tools)
    assert "v1.1" in first.messages[-1].content and "v1.2" in first.messages[-1].content  # the state message
    versions = agent.versions()
    assert (versions["base"].ref, versions["candidate"].ref) == ("v1.1", "v1.2")

    rows = tool_rows(agent.conn, agent.id)
    assert (rows[0]["server"], rows[0]["tool"], rows[0]["outcome"]) == ("runtime", "set_versions", "ok")
    assert json.loads(rows[0]["arguments"]) == {"base": "v1.1", "candidate": "v1.2"}
    assert [(r["server"], r["tool"]) for r in rows[1:]] == [
        ("runtime", "load_skill"),
        ("memory", "sync_requirements"),
        ("git", "analyze_changes"),
        ("git", "get_diff"),
        ("memory", "get_requirements"),
        ("memory", "save_impact"),
        ("memory", "add_risk"),
    ]
    assert all(r["outcome"] == "ok" for r in rows), [(r["tool"], r["error"]) for r in rows]
    sql = "SELECT * FROM analysis WHERE session_id = ? ORDER BY id DESC"
    analysis = agent.conn.execute(sql, (agent.id,)).fetchone()
    assert (analysis["base_ref"], analysis["candidate_ref"]) == ("v1.1", "v1.2")
    modules, impacted, not_impacted = impact_of(agent.conn, analysis["id"])
    assert modules and impacted == [f"REQ-00{n}" for n in range(2, 9)] and not_impacted == ["REQ-001"]
    assert agent.conversation.loaded_skill == "impact-analysis"


def test_analyze_without_refs_keeps_the_session_versions_and_calls_no_runtime_tool_first(agent):
    provider = Scripted(analyze_script())
    agent.provider = provider
    commands.analyze(agent)
    rows = tool_rows(agent.conn, agent.id)
    assert (rows[0]["server"], rows[0]["tool"]) == ("runtime", "load_skill")
    assert all(r["tool"] != "set_versions" for r in rows)
    versions = agent.versions()
    assert (versions["base"].ref, versions["candidate"].ref) == ("v1.0", "v1.1")
    analysis = agent.conn.execute("SELECT id FROM analysis WHERE session_id = ?", (agent.id,)).fetchone()
    assert impact_of(agent.conn, analysis["id"])[0]


def test_a_ref_that_does_not_resolve_calls_no_model(agent):
    provider = FakeProvider()
    agent.provider = provider
    with pytest.raises(ToolError) as error:
        commands.analyze(agent, ("v1.0", "v9.9"))
    assert error.value.code == "not_found"
    assert provider.requests == []
    row = tool_rows(agent.conn, agent.id)[-1]
    assert (row["tool"], row["outcome"]) == ("set_versions", "error")


def test_analyze_in_non_interactive_mode_exits_0(agent_project, fake_model, capsys):
    fake_model(Scripted(analyze_script(ANSWER)))
    assert main(["-C", str(agent_project), "-p", "/analyze v1.0 v1.1"]) == 0
    assert capsys.readouterr().out.strip() == ANSWER + "\n" + (
        "Recorded: 1 memory__sync_requirements, 1 git__analyze_changes, 1 memory__save_impact, 1 memory__add_risk."
    )


def test_analyze_with_a_ref_that_does_not_resolve_exits_2(agent_project, fake_model, capsys):
    provider = fake_model(FakeProvider())
    assert main(["-C", str(agent_project), "--output-format", "json", "-p", "/analyze v1.0 v9.9"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["exit_code"] == 2 and output["result"] is None and output["recorded"] is None
    assert provider.requests == []
