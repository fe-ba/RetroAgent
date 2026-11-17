"""A run against the candidate closes the defects whose linked test cases all passed in it (INV-14, mcp-tools.md
``test_runner.run_tests``, Closing defects), through the runtime, the real server and real runs of shop-api: v1.2
fixes the shipping test (S1, TC-020) and not the tax rounding test (S4, TC-022)."""

import pytest
from fixtures.example_project import project_copy, start

from retroagent.memory import connect, interpretation
from retroagent.runtime import commands, turn

pytestmark = pytest.mark.network

SHIPPING, TAX = "TC-020", "TC-022"


def failed_in(conn, run_id: str, test_case_id: str) -> int:
    row = conn.execute(
        "SELECT id, result FROM test_execution WHERE run_id = ? AND test_case_id = ?", (run_id, test_case_id)
    ).fetchone()
    assert row["result"] == "failed"
    return row["id"]


def test_a_candidate_run_closes_a_defect_whose_test_cases_passed_and_keeps_the_other_open(
    tmp_path_factory, pip_cache, shop_after_both_runs
):
    with project_copy(tmp_path_factory, shop_after_both_runs.path, pip_cache) as path:
        conn = connect(path)
        try:  # as memory.register_defect stores them, from the failures of RUN-0002 against v1.1
            shipping = failed_in(conn, "RUN-0002", SHIPPING)
            tax = failed_in(conn, "RUN-0002", TAX)
            fixed = interpretation.add_defect(conn, title="Shipping", severity="high", execution_ids=[shipping])
            not_fixed = interpretation.add_defect(conn, title="Totals", severity="high", execution_ids=[shipping, tax])
        finally:
            conn.close()
        assert (fixed, not_fixed) == ("DEF-001", "DEF-002")

        with start(path, trust_commands=True, mode="auto", base="v1.1", candidate="v1.2") as session:
            arguments = {"version": "candidate", "scope": "selected", "test_case_ids": [SHIPPING, TAX]}
            result = turn.call_tool(session, "test_runner__run_tests", arguments, ask=None)
            assert (result["run_id"], result["status"]) == ("RUN-0003", "completed")
            assert result["counts"]["passed"] == 1 and result["counts"]["failed"] == 1
            assert result["closed_defects"] == [fixed]
            [row] = commands.history(session, 1)
            assert row.closed_defects == (fixed,)
            assert [d.defect_id for d in commands.defects(session)] == [not_fixed]

        conn = connect(path)
        try:
            closed = interpretation.get_defect(conn, fixed)
            assert (closed["status"], closed["closed_by"], closed["closed_run_id"]) == ("closed", "run", "RUN-0003")
            assert closed["close_reason"] == "Every linked test case passed in RUN-0003: TC-020."
            assert interpretation.get_defect(conn, not_fixed)["status"] == "open"  # TC-022 failed against v1.2
        finally:
            conn.close()
