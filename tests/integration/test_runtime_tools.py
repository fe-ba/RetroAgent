"""The runtime tools through the turn: ``runtime.load_skill`` and ``runtime.set_versions`` (mcp-tools.md, Runtime
tools; context-loading.md, Skills)."""

import json

from fixtures.agent_session import answer, call, calls, tool_results, tool_rows
from fixtures.mcp_project import dump

from retroagent.context import skills
from retroagent.llm import FakeProvider
from retroagent.runtime.session import resolve_commit
from retroagent.runtime.turn import run_turn


def run(session, script):
    provider = FakeProvider(script)
    run_turn(session, "Go.", provider=provider, client=session.client, ask=None)
    return provider


def body(name):
    return skills.discover([skills.bundled_location()]).available[name].body


def test_load_skill_returns_the_body_without_its_frontmatter(agent):
    load = call("runtime__load_skill", {"name": "impact-analysis"})
    run(agent, [calls(load), answer()])
    content = tool_results(agent.conversation)[load.id]
    assert content == body("impact-analysis") and not content.startswith("---")
    assert (agent.conversation.loaded_skill, agent.conversation.loaded_skill_call) == ("impact-analysis", load.id)
    (row,) = tool_rows(agent.conn, agent.id)
    assert (row["server"], row["tool"], row["outcome"]) == ("runtime", "load_skill", "ok")


def test_loading_another_skill_replaces_the_body_of_the_previous_one_with_a_note(agent):
    first = call("runtime__load_skill", {"name": "impact-analysis"})
    second = call("runtime__load_skill", {"name": "test-selection"})
    provider = run(agent, [calls(first), calls(second), answer()])
    results = tool_results(agent.conversation)
    assert results[first.id] == skills.unloaded_note("impact-analysis")
    assert results[second.id] == body("test-selection")
    assert agent.conversation.loaded_skill == "test-selection"
    # The model read the first body before it was replaced, and the note after.
    assert body("impact-analysis") in [m.content for m in provider.requests[1].messages]
    assert skills.unloaded_note("impact-analysis") in [m.content for m in provider.requests[2].messages]


def test_a_skill_that_was_unloaded_can_be_loaded_again(agent):
    script = [
        calls(call("runtime__load_skill", {"name": "impact-analysis"})),
        calls(call("runtime__load_skill", {"name": "test-selection"})),
        calls(again := call("runtime__load_skill", {"name": "impact-analysis"})),
        answer(),
    ]
    run(agent, script)
    assert tool_results(agent.conversation)[again.id] == body("impact-analysis")


def test_loading_the_skill_that_is_already_loaded_returns_a_short_note(agent):
    first = call("runtime__load_skill", {"name": "failure-triage"})
    again = call("runtime__load_skill", {"name": "failure-triage"})
    run(agent, [calls(first), answer()])
    run(agent, [calls(again), answer()])  # a later turn: Repeated calls does not apply
    results = tool_results(agent.conversation)
    assert results[again.id] == skills.already_loaded_note("failure-triage")
    assert results[first.id] == body("failure-triage")  # the body stays where it is
    assert agent.conversation.loaded_skill_call == first.id


def test_loading_the_loaded_skill_again_after_a_write_in_the_same_turn_returns_the_short_note(agent):
    first = call("runtime__load_skill", {"name": "failure-triage"})
    write = call("runtime__set_versions", {"base": "v1.0", "candidate": "v1.1"})
    again = call("runtime__load_skill", {"name": "failure-triage"})
    run(agent, [calls(first), calls(write), calls(again), answer()])
    assert [row["outcome"] for row in tool_rows(agent.conn, agent.id)] == ["ok", "ok", "ok"]
    assert tool_results(agent.conversation)[again.id] == skills.already_loaded_note("failure-triage")


def test_an_unknown_skill_is_not_found_and_names_the_available_ones(agent):
    unknown = call("runtime__load_skill", {"name": "nothing"})
    run(agent, [calls(unknown), answer()])
    error = json.loads(tool_results(agent.conversation)[unknown.id])["error"]
    assert error["code"] == "not_found"
    assert "impact-analysis" in error["message"] and "test-reporting" in error["message"]
    assert agent.conversation.loaded_skill is None
    (row,) = tool_rows(agent.conn, agent.id)
    assert row["outcome"] == "error" and row["error"].startswith("not_found: ")


def test_set_versions_writes_each_ref_with_its_commit_and_the_next_state_message_shows_them(agent):
    project = agent.project_dir
    commits = {ref: resolve_commit(project, ref) for ref in ("v1.1", "v1.2")}
    setting = call("runtime__set_versions", {"base": "v1.1", "candidate": "v1.2"})
    provider = run(agent, [calls(setting), answer()])
    assert json.loads(tool_results(agent.conversation)[setting.id]) == {
        "base": {"ref": "v1.1", "commit": commits["v1.1"]},
        "candidate": {"ref": "v1.2", "commit": commits["v1.2"]},
    }
    row = agent.conn.execute(
        "SELECT base_ref, base_commit, candidate_ref, candidate_commit FROM session WHERE id = ?", (agent.id,)
    ).fetchone()
    assert tuple(row) == ("v1.1", commits["v1.1"], "v1.2", commits["v1.2"])
    before, after = provider.requests[0].messages[-1].content, provider.requests[1].messages[-1].content
    assert "Versions: base v1.0 (c7d45ad), candidate v1.1 (46a5ef0)" in before
    assert "Versions: base v1.1 (46a5ef0), candidate v1.2 (9936dcc)" in after


def test_set_versions_with_an_unknown_ref_is_not_found_and_writes_nothing(agent):
    before = dump(agent.project_dir)
    versions = agent.versions()
    setting = call("runtime__set_versions", {"base": "v1.1", "candidate": "v9.9"})
    run(agent, [calls(setting), answer()])
    error = json.loads(tool_results(agent.conversation)[setting.id])["error"]
    assert error == {"code": "not_found", "message": "'v9.9' is not a tag, branch or commit of the project"}
    assert agent.versions() == versions
    changed = [line for line in dump(agent.project_dir) if line not in before]
    assert all(line.startswith('INSERT INTO "tool_call"') for line in changed)  # only the audit row


def test_set_versions_needs_both_refs(agent):
    setting = call("runtime__set_versions", {"base": "v1.1"})
    run(agent, [calls(setting), answer()])
    error = json.loads(tool_results(agent.conversation)[setting.id])["error"]
    assert error["code"] == "invalid_argument" and "candidate" in error["message"]
