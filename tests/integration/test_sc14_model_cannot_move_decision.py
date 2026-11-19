"""SC-14, the model cannot move the decision, and ``/defects`` of the user (INV-14, ADR-0022, cli.md).

The model cannot close a defect: ``memory.close_defect`` is user only, so its call is refused with ``denied`` and
the defect stays open. The severity the model gives to the defect does not change the decision either: EC-01 and
EC-09 do not depend on it. Only the user closes a defect, with ``/defects close``.
"""

import io

from fixtures.agent_session import call, calls, tool_rows, triage_script
from fixtures.example_project import start
from fixtures.reference_scenario import S1, decision_of
from rich.console import Console

from retroagent.cli.interactive import Shell
from retroagent.memory import connect, interpretation
from retroagent.runtime import commands


def test_sc14_the_model_cannot_close_a_defect(reference_project):
    close = call("memory__close_defect", {"defect_id": "DEF-001", "reason": "The fix looks done."})
    script = triage_script(extra=[calls(close)])
    with start(reference_project.path, script) as session:
        commands.triage(session)
        assert script.remaining == 0
        [row] = [row for row in tool_rows(session.conn, session.id) if row["tool"] == "close_defect"]
        assert (row["server"], row["outcome"]) == ("memory", "denied")
        assert row["error"] == "denied: memory__close_defect is called only by the user, with a direct command"
        assert interpretation.get_defect(session.conn, "DEF-001")["status"] == "open"
        assert session.permission_refusals == 0  # a user-only tool does not count for exit code 4 (cli.md)
    _, decision = decision_of(reference_project.path)
    assert decision.outcome == "do_not_release"


def test_sc14_with_severity_low_the_decision_is_still_do_not_release_for_ec_01_and_ec_09(reference_project):
    script = triage_script(severity="low")
    with start(reference_project.path, script) as session:
        commands.triage(session)
        assert interpretation.get_defect(session.conn, "DEF-001")["severity"] == "low"
    criteria, decision = decision_of(reference_project.path)
    assert (criteria["EC-05"].state, criteria["EC-08"].state) == ("met", "met")
    assert decision.outcome == "do_not_release"
    assert [(r.id, r.state) for r in decision.reasons] == [("EC-01", "not_met"), ("EC-09", "not_met")]


def console() -> Console:
    return Console(file=io.StringIO(), record=True, width=200, color_system=None)


def test_the_user_lists_and_closes_defects_with_slash_defects(reference_project):
    conn = connect(reference_project.path)
    try:  # as memory.save_triage and memory.register_defect store them
        execution_id = reference_project.scenario.executions[S1]
        interpretation.add_triage(
            conn, execution_id=execution_id, classification="regression", justification="x", triaged_by="none"
        )
        interpretation.add_defect(conn, title="Shipping is not charged", severity="high", execution_ids=[execution_id])
    finally:
        conn.close()
    with start(reference_project.path) as session:
        out, err = console(), console()
        shell = Shell(session, out, err)

        assert not shell.handle("/defects").usage_error
        listed = out.export_text()
        assert "Open defects" in listed and "DEF-001" in listed and "TC-020" in listed

        outcome = shell.handle("/defects close DEF-001 fixed outside the tested scope")
        assert not outcome.usage_error and not outcome.runtime_error
        assert "DEF-001 is closed by the user: fixed outside the tested scope" in out.export_text()
        defect = interpretation.get_defect(session.conn, "DEF-001")
        assert (defect["status"], defect["closed_by"], defect["close_reason"]) == (
            "closed",
            "user",
            "fixed outside the tested scope",
        )
        [row] = tool_rows(session.conn, session.id)
        assert (row["server"], row["tool"], row["outcome"]) == ("memory", "close_defect", "ok")

        shell.handle("/defects")
        assert "No open defects." in out.export_text()
        shell.handle("/defects --all")
        text = out.export_text()
        assert "Closed by" in text and "fixed outside the tested scope" in text

        assert shell.handle("/defects close DEF-001 again").usage_error
        assert shell.handle("/defects close DEF-999 never existed").usage_error
        errors = err.export_text()
        assert "invalid_state: DEF-001 is already closed" in errors
        assert "not_found: INV-13: defect 'DEF-999' does not exist" in errors
        assert interpretation.get_defect(session.conn, "DEF-001")["close_reason"] == "fixed outside the tested scope"
