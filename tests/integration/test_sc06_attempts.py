"""SC-06: attempts and flaky tests, inspected in RUN-0002 (v1.1) of a ``/run all --on both``."""

import pytest

from retroagent.memory import connect, execution

pytestmark = pytest.mark.network

SEARCH = "tests.test_catalog::test_req_001_search_results_are_sorted_by_name"
TAX = "tests.test_tax::test_req_007_tax_rounds_half_up"
SHIPPING = "tests.test_shipping::test_req_005_shipping_charged_when_discount_drops_below_threshold"
COUPON = "tests.test_discounts::test_req_004_second_coupon_is_rejected"


@pytest.fixture(scope="module")
def run_0002(shop_after_both_runs):
    assert [row.run_id for row in shop_after_both_runs.outcome.runs] == ["RUN-0001", "RUN-0002"]
    conn = connect(shop_after_both_runs.path)
    rows = conn.execute(
        "SELECT e.id, e.status, e.result, tc.test_id FROM test_execution AS e"
        " JOIN test_case AS tc ON tc.id = e.test_case_id WHERE e.run_id = 'RUN-0002'"
    ).fetchall()
    executions = {
        row["test_id"]: {
            "status": row["status"],
            "result": row["result"],
            "attempts": [a["result"] for a in execution.list_attempts(conn, row["id"])],
            "flaky": execution.is_flaky(conn, row["id"]),
        }
        for row in rows
    }
    conn.close()
    return executions


def test_the_search_test_is_failed_and_flaky(run_0002):
    assert run_0002[SEARCH] == {
        "status": "executed",
        "result": "failed",
        "attempts": ["failed", "passed", "passed"],
        "flaky": True,
    }


def test_the_three_other_failed_tests_fail_three_times(run_0002):
    for test_id in (TAX, SHIPPING, COUPON):
        assert run_0002[test_id] == {
            "status": "executed",
            "result": "failed",
            "attempts": ["failed", "failed", "failed"],
            "flaky": False,
        }


def test_passed_tests_have_one_attempt(run_0002):
    passed = {test_id: e for test_id, e in run_0002.items() if test_id not in (SEARCH, TAX, SHIPPING, COUPON)}
    assert len(passed) == 22
    for e in passed.values():
        assert e == {"status": "executed", "result": "passed", "attempts": ["passed"], "flaky": False}
