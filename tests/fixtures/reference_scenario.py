"""The records of the reference scenario of shop-api, cycle 1 (``ORACLE.md``, Reference scenario).

Loaded through the ``retroagent.memory`` API, as the test runner and the agent would store them. These are test
records: the results are the ones of ``ORACLE.md``, typed here, not parsed from a JUnit XML of this machine
(CLAUDE.md, ADR-0016). One record bypasses the API: the triage ``expected_change`` of TC-014 (see below).
"""

from dataclasses import dataclass

from retroagent.memory import db, design, execution, impact, interpretation, requirements, sessions

BASE_REF, BASE_COMMIT = "v1.0", "c7d45ada468e3746c498cb3417999e117154a942"
CANDIDATE_REF, CANDIDATE_COMMIT = "v1.1", "46a5ef0910ce409a767f7549ed0c557106409321"
MIN_PASS_RATE = 0.90  # exit_criteria.min_pass_rate of the project configuration of shop-api

REQUIREMENTS = {
    "REQ-001": "Product catalog",
    "REQ-002": "Adding products to the cart",
    "REQ-003": "Cart totals",
    "REQ-004": "Discount coupons",
    "REQ-005": "Shipping",
    "REQ-006": "Checkout",
    "REQ-007": "Tax",
    "REQ-008": "Order history",
}

# The tests of v1.0 in the order of the JUnit XML: TC-001 to TC-022.
V1_0_TESTS = [
    "tests.test_api::test_req_001_api_returns_product_by_id",
    "tests.test_api::test_req_003_api_cart_shows_totals",
    "tests.test_api::test_req_006_api_checkout_creates_order",
    "tests.test_cart::test_req_003_subtotal_is_sum_of_price_times_quantity",
    "tests.test_cart::test_req_003_total_adds_tax_and_shipping",
    "tests.test_cart::test_req_003_empty_cart_total_is_zero",
    "tests.test_cart::test_req_003_removing_item_updates_subtotal",
    "tests.test_catalog::test_req_001_products_are_listed_sorted_by_name",
    "tests.test_catalog::test_req_001_product_has_name_and_price",
    "tests.test_catalog::test_req_001_unknown_product_is_not_found",
    "tests.test_catalog::test_req_001_search_results_are_sorted_by_name",  # TC-011, S3
    "tests.test_discounts::test_req_004_coupon_reduces_subtotal_by_percentage",
    "tests.test_discounts::test_req_004_unknown_coupon_is_rejected",
    "tests.test_discounts::test_req_004_second_coupon_is_rejected",  # TC-014, S2
    "tests.test_discounts::test_req_004_discount_applies_before_tax",
    "tests.test_orders::test_req_006_checkout_decrements_stock_and_empties_cart",
    "tests.test_orders::test_req_006_empty_cart_cannot_be_checked_out",
    "tests.test_shipping::test_req_005_flat_rate_below_threshold",
    "tests.test_shipping::test_req_005_free_shipping_at_threshold",
    "tests.test_shipping::test_req_005_shipping_charged_when_discount_drops_below_threshold",  # TC-020, S1
    "tests.test_tax::test_req_007_tax_is_19_percent_of_discounted_subtotal",
    "tests.test_tax::test_req_007_tax_rounds_half_up",  # TC-022, S4
]

# Added in v1.1, in the order of the JUnit XML of RUN-0002: TC-023 to TC-026 (S6).
V1_1_NEW_TESTS = [
    "tests.test_api::test_req_008_api_returns_order_by_id",
    "tests.test_discounts::test_req_004_two_coupons_are_combined",
    "tests.test_discounts::test_req_004_third_coupon_is_rejected",
    "tests.test_orders::test_req_008_orders_are_listed_newest_first",
]

# The tests of v1.1 in the order of the JUnit XML of RUN-0002.
V1_1_TESTS = [
    *V1_0_TESTS[:3],
    V1_1_NEW_TESTS[0],
    *V1_0_TESTS[3:15],
    *V1_1_NEW_TESTS[1:3],
    *V1_0_TESTS[15:17],
    V1_1_NEW_TESTS[3],
    *V1_0_TESTS[17:],
]

GENERATED = "test_req_002_quantity_above_stock_is_rejected.py::test_req_002_quantity_above_stock_is_rejected"

S1, S2, S3, S4 = (
    "tests.test_shipping::test_req_005_shipping_charged_when_discount_drops_below_threshold",
    "tests.test_discounts::test_req_004_second_coupon_is_rejected",
    "tests.test_catalog::test_req_001_search_results_are_sorted_by_name",
    "tests.test_tax::test_req_007_tax_rounds_half_up",
)

# Attempts of the tests that did not pass, the same in every version where they appear (ORACLE.md, Raw results).
FAILING = {
    "v1.0": {S3: ("failed", "passed", "passed"), S4: ("failed", "failed", "failed")},
    "v1.1": {
        S3: ("failed", "passed", "passed"),
        S4: ("failed", "failed", "failed"),
        S1: ("failed", "failed", "failed"),
        S2: ("failed", "failed", "failed"),
    },
    "v1.2": {S3: ("failed", "passed", "passed"), S4: ("failed", "failed", "failed")},
}

MESSAGES = {
    S1: "AssertionError: shipping 0.00 for a discounted subtotal of 90.00, expected 5.00",
    S2: "AssertionError: second coupon accepted, expected status 409",
    S3: "AssertionError: search results are not sorted by name",
    S4: "AssertionError: tax 0.12 for 0.625, expected 0.13 (half up)",
}


@dataclass(frozen=True)
class ReferenceScenario:
    session_id: int
    analysis_id: int
    suite_id: int
    test_cases: dict[str, str]  # test id (or GENERATED) -> TC id
    tc_027: str
    tc_028: str
    full_base_run: str  # RUN-0001
    full_candidate_run: str  # RUN-0002
    baseline_run: str  # RUN-0003
    evaluated_run: str  # RUN-0004
    defect_id: str  # DEF-001

    def tc(self, test_id: str) -> str:
        return self.test_cases[test_id]


# The change set of v1.0..v1.1, as `git diff --numstat` gives it on the example.
CHANGE_SET = [
    {"path": path, "change": "modified", "lines_added": added, "lines_removed": removed}
    for path, added, removed in [
        ("README.md", 1, 1),
        ("RETRO.md", 2, 2),
        ("docs/requirements.md", 9, 1),
        ("pyproject.toml", 2, 2),
        ("src/shop/api.py", 6, 2),
        ("src/shop/cart.py", 3, 3),
        ("src/shop/discounts.py", 12, 6),
        ("src/shop/orders.py", 15, 2),
        ("src/shop/pricing.py", 9, 5),
        ("src/shop/store.py", 2, 1),
        ("tests/test_api.py", 11, 0),
        ("tests/test_discounts.py", 16, 0),
        ("tests/test_orders.py", 9, 1),
    ]
]


def _attempts(version: str, test_id: str) -> list[dict]:
    results = FAILING[version].get(test_id, ("passed",))
    return [
        {"result": r, "duration": 0.001, "failure_message": None if r == "passed" else MESSAGES[test_id]}
        for r in results
    ]


def _start(conn, session_id, *, role, scope, suite_id=None) -> str:
    ref, commit = (BASE_REF, BASE_COMMIT) if role == "base" else (CANDIDATE_REF, CANDIDATE_COMMIT)
    run_id = execution.start_run(
        conn,
        version_role=role,
        ref=ref,
        commit=commit,
        scope=scope,
        command="python -m pytest --junitxml={junit} {names}" if scope != "all" else "python -m pytest",
        session_id=session_id,
        suite_id=suite_id,
    )
    execution.set_junit_path(conn, run_id, f".retro/runs/{run_id}/junit.xml")
    return run_id


def _execute(conn, run_id, test_case_id, attempts, test_revision=None) -> int:
    return execution.record_test_execution(
        conn,
        run_id=run_id,
        test_case_id=test_case_id,
        status="executed",
        result=attempts[0]["result"],
        duration=attempts[0]["duration"],
        test_revision=test_revision,
        attempts=attempts,
    )


def _full_run(conn, session_id, *, role, version, tests, test_cases) -> str:
    """A full run (``/run all``) that discovers the tests it does not know yet."""
    run_id = _start(conn, session_id, role=role, scope="all")
    for test_id in tests:
        if test_id not in test_cases:
            implementation = test_id.replace(".", "/", 1).replace("::", ".py::", 1)
            test_cases[test_id] = design.add_project_suite_test_case(
                conn, test_id=test_id, implementation=implementation
            )
        _execute(conn, run_id, test_cases[test_id], _attempts(version, test_id))
    execution.finish_run(conn, run_id, status="completed", exit_code=1)
    return run_id


def load_reference_scenario(conn) -> ReferenceScenario:
    session_id = sessions.start_session(
        conn,
        model="none",
        interactive=False,
        result_char_limit=8000,
        base_ref=BASE_REF,
        base_commit=BASE_COMMIT,
        candidate_ref=CANDIDATE_REF,
        candidate_commit=CANDIDATE_COMMIT,
    )
    for requirement_id, title in REQUIREMENTS.items():
        requirements.add_requirement(
            conn,
            id=requirement_id,
            title=title,
            description=title,
            source_file="docs/requirements.md",
            since="v1.1" if requirement_id == "REQ-008" else None,
        )
    requirements.add_requirement_change(
        conn,
        requirement_id="REQ-004",
        version="v1.1",
        description="Two different coupons can be combined; before, only one coupon applied per order.",
    )

    test_cases: dict[str, str] = {}
    full_base = _full_run(conn, session_id, role="base", version="v1.0", tests=V1_0_TESTS, test_cases=test_cases)
    full_candidate = _full_run(
        conn, session_id, role="candidate", version="v1.1", tests=V1_1_TESTS, test_cases=test_cases
    )

    analysis_id = impact.add_analysis(
        conn,
        session_id=session_id,
        base_ref=BASE_REF,
        base_commit=BASE_COMMIT,
        candidate_ref=CANDIDATE_REF,
        candidate_commit=CANDIDATE_COMMIT,
        files=CHANGE_SET,
    )
    impact.record_impact(
        conn,
        analysis_id,
        modules=[
            {"module": "pricing", "files": ["src/shop/pricing.py"], "risk_level": "high", "reason": "Totals order"},
            {"module": "discounts", "files": ["src/shop/discounts.py"], "risk_level": "high", "reason": "Coupons"},
            {"module": "cart", "files": ["src/shop/cart.py"], "risk_level": "medium", "reason": "Stock check"},
            {
                "module": "orders",
                "files": ["src/shop/orders.py", "src/shop/store.py", "src/shop/api.py"],
                "risk_level": "low",
                "reason": "Order history",
            },
        ],
        requirements=[
            {"requirement_id": f"REQ-00{n}", "reason": f"{REQUIREMENTS[f'REQ-00{n}']} may change"} for n in range(2, 9)
        ],
    )
    for description, level, requirement_ids in [
        (
            "Totals are computed in a new order in `src/shop/pricing.py`; shipping and tax may be computed on the"
            " wrong amount.",
            "high",
            ["REQ-003", "REQ-005", "REQ-007"],
        ),
        (
            "Coupon rules changed in `src/shop/discounts.py`; combinations of coupons may give a wrong discount.",
            "high",
            ["REQ-004"],
        ),
        ("`src/shop/cart.py` changed and its stock check had no test before this cycle.", "medium", ["REQ-002"]),
        (
            "Orders are now kept in memory by `src/shop/store.py`; checkout has a new side effect.",
            "low",
            ["REQ-006", "REQ-008"],
        ),
    ]:
        impact.add_risk(
            conn, description=description, level=level, analysis_id=analysis_id, requirement_ids=requirement_ids
        )

    tc_027 = design.add_test_case(
        conn,
        title="A quantity above the stock is rejected",
        objective="Adding more units than in stock is refused and the cart does not change.",
        priority="high",
        designed_by="none",
        preconditions=["A product with stock 5"],
        input_data=[{"name": "quantity", "value": 6}],
        steps=["Add 6 units of the product to a new cart"],
        expected_result="The request is rejected and the cart stays empty.",
        requirement_ids=["REQ-002"],
    )
    design.mark_implemented(conn, tc_027, GENERATED)
    test_cases[GENERATED] = tc_027
    tc_028 = design.add_test_case(
        conn,
        title="An unknown product cannot be added",
        objective="Adding a product that is not in the catalog is refused.",
        priority="medium",
        designed_by="none",
        steps=["Add a product with an unknown identifier to a new cart"],
        expected_result="The request is rejected with not found.",
        requirement_ids=["REQ-002"],
    )
    for test_id in V1_1_TESTS:
        if any(f"test_req_00{n}_" in test_id for n in (2, 3, 4, 6)):
            design.update_test_case(conn, test_cases[test_id], {"priority": "high"})

    suite_id = design.add_suite(conn, analysis_id=analysis_id, session_id=session_id)
    ordered = [test_cases[t] for t in V1_0_TESTS + V1_1_NEW_TESTS] + [tc_027, tc_028]
    for position, test_case_id in enumerate(ordered, start=1):
        design.add_to_suite(conn, suite_id, test_case_id=test_case_id, position=position, selection_reason="all")

    # RUN-0003: the suite against v1.0. The tests added in v1.1 do not exist there: not reported, so blocked.
    baseline = _start(conn, session_id, role="base", scope="suite", suite_id=suite_id)
    for test_id in V1_0_TESTS:
        _execute(conn, baseline, test_cases[test_id], _attempts("v1.0", test_id))
    for test_id in V1_1_NEW_TESTS:
        execution.record_test_execution(
            conn, run_id=baseline, test_case_id=test_cases[test_id], status="blocked", reason="not_reported"
        )
    _execute(conn, baseline, tc_027, _attempts("v1.0", GENERATED), test_revision=1)
    execution.finish_run(conn, baseline, status="completed", exit_code=1)

    # RUN-0004: the suite against v1.1, the evaluated run.
    evaluated = _start(conn, session_id, role="candidate", scope="suite", suite_id=suite_id)
    executions = {}
    for test_id in V1_0_TESTS + V1_1_NEW_TESTS:
        executions[test_id] = _execute(conn, evaluated, test_cases[test_id], _attempts("v1.1", test_id))
    _execute(conn, evaluated, tc_027, _attempts("v1.1", GENERATED), test_revision=1)
    execution.finish_run(conn, evaluated, status="completed", exit_code=1)

    # Triage of RUN-0004 (ORACLE.md, Expected triage).
    interpretation.add_triage(
        conn,
        execution_id=executions[S3],
        classification="flaky",
        justification="Failed at the first attempt and passed in both reruns.",
        triaged_by="none",
    )
    # Stands in for the slice-4 evidence check of expected_change (INV-15, needs git): add_triage refuses it until
    # then. REQ-004 has "Changed: v1.1", which applies to v1.0..v1.1.
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO triage (execution_id, classification, justification, triaged_by, created_at)"
            " VALUES (?, 'expected_change', ?, 'none', ?)",
            (
                executions[S2],
                'REQ-004 has the entry "Changed: v1.1 - Two different coupons can be combined". The test still'
                " expects a second coupon to be rejected. The test must be updated.",
                db.utc_now(),
            ),
        )
    interpretation.add_triage(
        conn,
        execution_id=executions[S1],
        classification="regression",
        justification="REQ-005 requires shipping on the subtotal after discounts; no documented change.",
        triaged_by="none",
    )
    interpretation.add_triage(
        conn,
        execution_id=executions[S4],
        classification="pre_existing",
        justification="Failed against the baseline in RUN-0003.",
        triaged_by="none",
        base_commit=BASE_COMMIT,
    )
    defect_id = interpretation.add_defect(
        conn,
        title="Shipping is not charged when a coupon brings the subtotal under 100.00",
        severity="high",
        execution_ids=[executions[S1]],
    )

    return ReferenceScenario(
        session_id=session_id,
        analysis_id=analysis_id,
        suite_id=suite_id,
        test_cases=dict(test_cases),
        tc_027=tc_027,
        tc_028=tc_028,
        full_base_run=full_base,
        full_candidate_run=full_candidate,
        baseline_run=baseline,
        evaluated_run=evaluated,
        defect_id=defect_id,
    )


V1_2_COMMIT = "9936dccd1584a9226feabe90acf9dd8ab1c62e59"
V1_2_TESTS = [t for t in V1_1_TESTS if t != S2]  # v1.2 removes the obsolete coupon test


@dataclass(frozen=True)
class Cycle2:
    session_id: int
    suite_id: int
    baseline_run: str  # the suite against v1.1
    evaluated_run: str  # the suite against v1.2


def load_cycle_2(conn, scenario: ReferenceScenario) -> Cycle2:
    """Cycle 2 of ``ORACLE.md`` (v1.1 to v1.2) after ``load_reference_scenario``: the 25 tests of the project at
    v1.2, no generated test, and DEF-001 closed by the evaluated run. There is no full run in this cycle."""
    session_id = sessions.start_session(
        conn,
        model="none",
        interactive=False,
        result_char_limit=8000,
        base_ref=CANDIDATE_REF,
        base_commit=CANDIDATE_COMMIT,
        candidate_ref="v1.2",
        candidate_commit=V1_2_COMMIT,
    )
    analysis_id = impact.add_analysis(
        conn,
        session_id=session_id,
        base_ref=CANDIDATE_REF,
        base_commit=CANDIDATE_COMMIT,
        candidate_ref="v1.2",
        candidate_commit=V1_2_COMMIT,
        files=[
            {"path": "src/shop/pricing.py", "change": "modified", "lines_added": 3, "lines_removed": 2},
            {"path": "tests/test_discounts.py", "change": "modified", "lines_added": 0, "lines_removed": 8},
        ],
    )
    impact.record_impact(
        conn,
        analysis_id,
        modules=[{"module": "pricing", "files": ["src/shop/pricing.py"], "risk_level": "high", "reason": "Shipping"}],
        requirements=[{"requirement_id": "REQ-005", "reason": "Shipping is computed again on the discounted subtotal"}],
    )
    suite_id = design.add_suite(conn, analysis_id=analysis_id, session_id=session_id)
    for position, test_id in enumerate(V1_2_TESTS, start=1):
        design.add_to_suite(
            conn, suite_id, test_case_id=scenario.tc(test_id), position=position, selection_reason="all"
        )

    def suite_run(role, ref, commit, version):
        run_id = execution.start_run(
            conn,
            version_role=role,
            ref=ref,
            commit=commit,
            scope="suite",
            command="python -m pytest --junitxml={junit} {names}",
            session_id=session_id,
            suite_id=suite_id,
        )
        execution.set_junit_path(conn, run_id, f".retro/runs/{run_id}/junit.xml")
        executions = {t: _execute(conn, run_id, scenario.tc(t), _attempts(version, t)) for t in V1_2_TESTS}
        execution.finish_run(conn, run_id, status="completed", exit_code=1)
        return run_id, executions

    baseline, _ = suite_run("base", CANDIDATE_REF, CANDIDATE_COMMIT, "v1.1")
    evaluated, executions = suite_run("candidate", "v1.2", V1_2_COMMIT, "v1.2")
    interpretation.add_triage(
        conn,
        execution_id=executions[S3],
        classification="flaky",
        justification="Failed at the first attempt and passed in both reruns.",
        triaged_by="none",
    )
    interpretation.add_triage(
        conn,
        execution_id=executions[S4],
        classification="pre_existing",
        justification="Failed against the baseline in " + baseline + ".",
        triaged_by="none",
        base_commit=CANDIDATE_COMMIT,
    )
    interpretation.close_defect(
        conn,
        scenario.defect_id,
        closed_by="run",
        close_reason="The test case of the defect passed in " + evaluated + ".",
        closed_run_id=evaluated,
    )
    return Cycle2(session_id, suite_id, baseline, evaluated)
