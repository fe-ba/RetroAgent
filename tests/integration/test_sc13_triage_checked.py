"""SC-13, triage is checked by code, and ``/triage [run_id]`` with a model that follows the skill ``failure-triage``
on the reference scenario (runtime.md, Model commands; ORACLE.md, Expected triage).

The script tries the classifications that code must refuse before the right ones: ``expected_change`` for TC-020
(REQ-005 has no documented change), ``pre_existing`` for TC-020 (it passed against the baseline) and ``flaky`` for
TC-022 (its attempts agree). The four classifications of the oracle are accepted, one defect is registered for the
shipping test, and EC-08 and the decision are those of the reference scenario.
"""

import json

import pytest
from fixtures.agent_session import Scripted, answer, call, calls, tool_results, tool_rows, triage_script
from fixtures.example_project import project_copy, start
from fixtures.reference_scenario import S1, S2, S3, S4, decision_of
from fixtures.tool_definitions import step_tool_names

from retroagent.memory import interpretation
from retroagent.runtime import commands
from retroagent.runtime.commands import CommandError


def first_user_message(request) -> str:
    return next(m.content for m in request.messages if m.role == "user")


def test_sc13_triage_refuses_the_classifications_without_evidence_and_accepts_the_oracle(reference_project):
    project, scenario = reference_project.path, reference_project.scenario
    script = triage_script()
    with start(project, script) as session:
        result = commands.triage(session)

        assert script.remaining == 0 and "DEF-001 registered for TC-020" in result.text
        # three refused save_triage are not counted (runtime.md, Display)
        assert result.recorded == (("memory__save_triage", 4), ("memory__register_defect", 1))
        assert first_user_message(script.requests[0]) == (
            "Load the skill `failure-triage` and triage the failed executions of run `RUN-0004`."
        )
        expected_tools = step_tool_names(session.known_tools(), "triage")
        assert "git__analyze_changes" not in expected_tools and "memory__save_triage" in expected_tools
        for request in script.requests:
            assert sorted(t.name for t in request.tools) == expected_tools
        assert session.conversation.loaded_skill == "failure-triage"

        saves = [row for row in tool_rows(session.conn, session.id) if row["tool"] == "save_triage"]
        assert [row["outcome"] for row in saves] == ["error", "error", "ok", "ok", "ok", "error", "ok"]
        refusals = [row["error"] for row in saves if row["outcome"] == "error"]
        assert refusals[0].startswith("invalid_state: INV-15: expected_change needs a requirement traced to TC-020")
        assert refusals[0].endswith("TC-020 traces REQ-005, and it has no Changed or Removed entry")
        assert refusals[1] == (
            "invalid_state: INV-15: pre_existing needs TC-020 to fail against the baseline: it passed in RUN-0003, the"
            " latest completed run on the baseline commit that executed it"
        )
        assert refusals[2].startswith("invalid_state: INV-15: flaky needs a rerun that passed")
        assert "(attempts: failed, failed, failed)" in refusals[2]
        others = [row for row in tool_rows(session.conn, session.id) if row["tool"] != "save_triage"]
        assert all(row["outcome"] == "ok" for row in others)

        executions = scenario.executions
        current = {
            test_id: interpretation.current_triage(session.conn, executions[test_id])["classification"]
            for test_id in (S1, S2, S3, S4)
        }
        assert current == {S1: "regression", S2: "expected_change", S3: "flaky", S4: "pre_existing"}
        assert session.conn.execute("SELECT COUNT(*) FROM triage").fetchone()[0] == 4
        assert {row["triaged_by"] for row in session.conn.execute("SELECT triaged_by FROM triage")} == {
            session.conn.execute("SELECT model FROM session WHERE id = ?", (session.id,)).fetchone()[0]
        }
        [defect] = interpretation.list_defects(session.conn)
        assert (defect["id"], defect["severity"], defect["status"]) == ("DEF-001", "high", "open")
        assert interpretation.linked_test_cases(session.conn, "DEF-001") == ["TC-020"]

    criteria, decision = decision_of(project)
    assert criteria["EC-08"].state == "met"
    assert decision.outcome == "do_not_release"
    assert [(r.id, r.state) for r in decision.reasons] == [
        ("EC-01", "not_met"),
        ("EC-05", "not_met"),
        ("EC-09", "not_met"),
    ]


def test_triage_names_the_run_given_and_refuses_an_unknown_one_before_the_model(reference_project):
    script = Scripted([answer("Nothing to triage.")])
    with start(reference_project.path, script) as session:
        with pytest.raises(CommandError, match="run RUN-9999 does not exist"):
            commands.triage(session, "RUN-9999")
        assert script.requests == []
        commands.triage(session, "RUN-0003")
    assert first_user_message(script.requests[0]) == (
        "Load the skill `failure-triage` and triage the failed executions of run `RUN-0003`."
    )


def test_triage_without_any_run_is_refused_before_the_model(tmp_path_factory, pristine_example):
    script = Scripted([])
    with project_copy(tmp_path_factory, pristine_example) as path, start(path, script) as session:
        with pytest.raises(CommandError, match="there is no run to triage"):
            commands.triage(session)
    assert script.requests == []


def test_in_triage_a_blocked_call_names_the_write_tools_of_the_step(reference_project):
    # A model command has the tool set of its step, as a cycle step does (runtime.md, Repeated calls).
    arguments = {"run_id": "RUN-0004", "untriaged": True}
    first, second = call("memory__get_executions", arguments), call("memory__get_executions", arguments)
    script = Scripted([calls(first), calls(second), answer("Nothing triaged.")])
    with start(reference_project.path, script) as session:
        commands.triage(session, "RUN-0004")
        blocked = json.loads(tool_results(session.conversation)[second.id])["error"]
    assert blocked["code"] == "invalid_argument" and f"call {first.id}" in blocked["message"]
    assert blocked["message"].endswith(
        " The next call of this step is one of its write tools: memory__link_defect, memory__register_defect,"
        " memory__save_triage."
    )
