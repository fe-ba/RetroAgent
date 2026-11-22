"""Triage and defects through the real ``memory`` server and the real client, on the records of the reference
scenario (cycle 1) in a copy of the example project with its git repository: each classification accepted with its
evidence and refused without it (INV-15), the history of triage, the defect tools and each of their error codes
(mcp-tools.md, SC-13), and EC-08 and the decision after the triage of the oracle."""

import pytest
from fixtures.mcp_project import dump, error_of, set_versions
from fixtures.reference_scenario import BASE_COMMIT, S1, S2, S3, S4, V1_0_TESTS, _execute, _start, decision_of

from retroagent.mcp_client import Client
from retroagent.memory import connect, execution, requirements


@pytest.fixture
def shop(reference_project):
    """The reference project and a client of its session: versions v1.0 and v1.1, model ``none``."""
    with Client(reference_project.path, reference_project.scenario.session_id) as client:
        yield reference_project, client


def triage(client, execution_id, classification, justification="Cites the evidence.", **options):
    arguments = {"execution_id": execution_id, "classification": classification, "justification": justification}
    return client.call("memory", "save_triage", {**arguments, **options})


def refused(shop, call) -> str:
    """The message of an ``invalid_state`` refusal that wrote nothing."""
    project, _ = shop
    before = dump(project.path)
    error = error_of(call)
    assert error.code == "invalid_state", error
    assert dump(project.path) == before
    return error.message


def execution_of(project, run_id: str, test_id: str) -> int:
    conn = connect(project.path)
    try:
        return conn.execute(
            "SELECT id FROM test_execution WHERE run_id = ? AND test_case_id = ?",
            (run_id, project.scenario.tc(test_id)),
        ).fetchone()[0]
    finally:
        conn.close()


# Each classification, refused without its evidence and accepted with it (SC-13)


def test_expected_change_of_s1_is_refused_because_req_005_has_no_documented_change(shop):
    project, client = shop
    message = refused(shop, lambda: triage(client, project.scenario.executions[S1], "expected_change"))
    assert message == (
        "INV-15: expected_change needs a requirement traced to TC-020 with a Changed or Removed entry that applies to"
        " the change between the session versions: TC-020 traces REQ-005, and it has no Changed or Removed entry"
    )


def test_expected_change_of_s2_is_accepted_because_the_change_of_req_004_applies_in_git(shop):
    project, client = shop
    saved = triage(client, project.scenario.executions[S2], "expected_change", "REQ-004 has Changed: v1.1.")
    assert saved == {
        "triage_id": saved["triage_id"],
        "execution_id": project.scenario.executions[S2],
        "test_case_id": "TC-014",
        "classification": "expected_change",
    }


def test_expected_change_is_refused_when_the_entries_do_not_apply_in_git(shop):
    """A ``Changed`` entry of v1.0 is reachable from the baseline, and one of v9.9 is not a git ref: neither applies to
    v1.0..v1.1 (project-contract.md). These entries are test records added to REQ-005."""
    project, client = shop
    conn = connect(project.path)
    try:
        for version in ("v1.0", "v9.9"):
            requirements.add_requirement_change(conn, requirement_id="REQ-005", version=version, description="x")
    finally:
        conn.close()
    message = refused(shop, lambda: triage(client, project.scenario.executions[S1], "expected_change"))
    assert message.endswith("TC-020 traces REQ-005, and its entries (REQ-005 v1.0, REQ-005 v9.9) do not apply to the"
                            " change between the session versions")  # fmt: skip


def test_expected_change_and_pre_existing_need_the_session_versions_and_a_run_against_the_candidate(shop):
    project, client = shop
    session_id = project.scenario.session_id
    set_versions(project.path, session_id, "v1.1", "v1.2")  # RUN-0004 is on v1.1, not on the candidate v1.2
    for classification, test_id in (("expected_change", S2), ("pre_existing", S4)):
        message = refused(shop, lambda: triage(client, project.scenario.executions[test_id], classification))  # noqa: B023
        assert "needs an execution of a run against the candidate: RUN-0004 is on commit" in message
    set_versions(project.path, session_id, None, None)
    for classification, test_id in (("expected_change", S2), ("pre_existing", S4)):
        message = refused(shop, lambda: triage(client, project.scenario.executions[test_id], classification))  # noqa: B023
        assert message == f"INV-15: {classification} needs the session versions, and they are not set"


def test_pre_existing_of_s1_is_refused_because_it_passed_against_the_baseline(shop):
    project, client = shop
    message = refused(shop, lambda: triage(client, project.scenario.executions[S1], "pre_existing"))
    assert message == (
        "INV-15: pre_existing needs TC-020 to fail against the baseline: it passed in RUN-0003, the latest completed"
        " run on the baseline commit that executed it"
    )


def test_pre_existing_of_s4_is_accepted_because_it_failed_against_the_baseline(shop):
    project, client = shop
    assert triage(client, project.scenario.executions[S4], "pre_existing")["test_case_id"] == "TC-022"


def test_flaky_of_s4_is_refused_because_its_attempts_agree(shop):
    project, client = shop
    execution_id = project.scenario.executions[S4]
    message = refused(shop, lambda: triage(client, execution_id, "flaky"))
    assert f"no rerun of execution {execution_id} passed (attempts: failed, failed, failed)" in message
    assert "no earlier execution of TC-022 on commit 46a5ef0910ce passed" in message


def test_flaky_of_s3_is_accepted_because_a_rerun_passed(shop):
    project, client = shop
    assert triage(client, project.scenario.executions[S3], "flaky")["test_case_id"] == "TC-011"


def test_regression_of_s4_is_refused_because_it_failed_against_the_baseline(shop):
    project, client = shop
    message = refused(shop, lambda: triage(client, project.scenario.executions[S4], "regression"))
    assert message == (
        "INV-15: regression needs TC-022 not to fail against the baseline, and its result was failed in RUN-0003, the"
        f" latest completed run on the baseline commit {BASE_COMMIT[:12]} that executed it: a failure"
        " that the baseline already had is pre_existing"
    )


def test_regression_of_s1_is_accepted_because_it_passed_against_the_baseline(shop):
    project, client = shop
    assert triage(client, project.scenario.executions[S1], "regression")["test_case_id"] == "TC-020"


def test_regression_of_s4_is_accepted_without_session_versions(shop):
    project, client = shop
    set_versions(project.path, project.scenario.session_id, None, None)
    assert triage(client, project.scenario.executions[S4], "regression")["test_case_id"] == "TC-022"


def test_judgments_of_the_model_need_no_evidence(shop):
    project, client = shop
    execution_id = project.scenario.executions[S1]
    for classification in ("environment", "test_defect"):
        replace = classification == "test_defect"
        assert triage(client, execution_id, classification, replace=replace)["classification"] == classification


# Soft checks: refused with the evidence, kept with confirm (mcp-tools.md, memory.save_triage)


def confirmed(project, triage_id: int) -> int:
    conn = connect(project.path)
    try:
        return conn.execute("SELECT confirmed FROM triage WHERE id = ?", (triage_id,)).fetchone()[0]
    finally:
        conn.close()


def generated_failure(project) -> int:
    """TC-027, the generated test, failed in a new baseline run and in a new candidate run: the execution of the
    candidate. Typed records, as the reference scenario loads them; no result of this machine."""
    conn = connect(project.path)
    try:
        attempts = [{"result": "failed", "duration": 0.001, "failure_message": "AssertionError: status 422, not 409"}]
        failures = []
        for role in ("base", "candidate"):
            run_id = _start(conn, project.scenario.session_id, role=role, scope="selected")
            failures.append(_execute(conn, run_id, project.scenario.tc_027, attempts, test_revision=1))
            execution.finish_run(conn, run_id, status="completed", exit_code=1)
        return failures[1]
    finally:
        conn.close()


def test_regression_of_s2_is_refused_with_the_documented_change_and_kept_with_confirm(shop):
    project, client = shop
    execution_id = project.scenario.executions[S2]
    message = refused(shop, lambda: triage(client, execution_id, "regression"))
    assert message == (
        'TC-014 traces REQ-004 "Changed: v1.1 - Two different coupons can be combined; before, only one coupon applied'
        ' per order.", which applies to the change between the session versions: a failure in a documented change is'
        " most likely an expected_change. Classify it as expected_change, or call again with confirm true if the"
        " evidence shows a regression"
    )
    saved = triage(client, execution_id, "regression", confirm=True)
    assert saved["classification"] == "regression" and confirmed(project, saved["triage_id"]) == 1


def test_pre_existing_of_a_generated_test_is_refused_with_its_evidence_and_kept_with_confirm(shop):
    project, client = shop
    execution_id = generated_failure(project)
    message = refused(shop, lambda: triage(client, execution_id, "pre_existing"))
    assert message == (
        "TC-027 is a generated test: a generated test that fails against the baseline most likely does not match the"
        " code. Read its evidence with test_runner__get_evidence and consider test_defect; call again with confirm"
        " true only if the evidence shows that the product fails"
    )
    saved = triage(client, execution_id, "pre_existing", confirm=True)
    assert saved["classification"] == "pre_existing" and confirmed(project, saved["triage_id"]) == 1
    # test_defect, the likely classification, needs no confirmation
    replaced = triage(client, execution_id, "test_defect", replace=True)
    assert confirmed(project, replaced["triage_id"]) == 0


def test_the_soft_checks_do_not_touch_a_regression_without_documented_change_or_a_project_test(shop):
    project, client = shop
    regression = triage(client, project.scenario.executions[S1], "regression")  # REQ-005 has no Changed entry
    pre_existing = triage(client, project.scenario.executions[S4], "pre_existing")  # TC-022 is a project test
    assert [confirmed(project, t["triage_id"]) for t in (regression, pre_existing)] == [0, 0]


def test_confirm_on_a_classification_that_no_soft_check_refuses_is_stored_as_not_confirmed(shop):
    project, client = shop
    saved = [
        triage(client, project.scenario.executions[S1], "regression", confirm=True),
        triage(client, project.scenario.executions[S4], "pre_existing", confirm=True),
        triage(client, project.scenario.executions[S2], "expected_change", confirm=True),
    ]
    assert [confirmed(project, t["triage_id"]) for t in saved] == [0, 0, 0]


def test_confirm_never_replaces_the_evidence_of_inv_15(shop):
    project, client = shop
    message = refused(shop, lambda: triage(client, project.scenario.executions[S4], "regression", confirm=True))
    assert message.startswith("INV-15: regression needs TC-022 not to fail against the baseline")


# Errors and history of save_triage


def test_save_triage_errors(shop):
    project, client = shop
    passed = execution_of(project, project.scenario.evaluated_run, V1_0_TESTS[0])
    message = refused(shop, lambda: triage(client, passed, "regression"))
    assert message == f"INV-08: execution {passed} of TC-001 is passed, not failed or error"
    assert error_of(lambda: triage(client, 99_999, "regression")).code == "not_found"
    assert error_of(lambda: triage(client, passed, "noise")).code == "invalid_argument"
    triage(client, project.scenario.executions[S1], "regression")
    message = refused(shop, lambda: triage(client, project.scenario.executions[S1], "environment"))
    assert message == (
        f"execution {project.scenario.executions[S1]} of TC-020 is already triaged as regression; set replace to true"
        " to triage it again"
    )


def test_a_second_triage_is_kept_as_history_and_becomes_the_current_one(shop):
    project, client = shop
    execution_id = project.scenario.executions[S1]
    first = triage(client, execution_id, "environment", "The service did not answer.")
    second = triage(client, execution_id, "regression", "Was environment; the service answered.", replace=True)
    assert second["previous"] == "environment" and second["triage_id"] > first["triage_id"]
    executions = client.call("memory", "get_executions", {"run_id": "RUN-0004", "result": "failed"})["executions"]
    current = next(e for e in executions if e["execution_id"] == execution_id)
    assert current["triage"]["classification"] == "regression" and current["triage_count"] == 2
    assert current["triage"]["triaged_by"] == "none"
    conn = connect(project.path)
    try:
        rows = conn.execute("SELECT classification FROM triage WHERE execution_id = ? ORDER BY id", (execution_id,))
        assert [row[0] for row in rows] == ["environment", "regression"]
    finally:
        conn.close()


# Defects


def product_faults(shop) -> tuple[int, int]:
    """S1 triaged ``regression`` and S4 ``pre_existing``, as the oracle classifies them: a defect needs a product
    fault (mcp-tools.md, ``memory.register_defect``)."""
    project, client = shop
    s1, s4 = project.scenario.executions[S1], project.scenario.executions[S4]
    triage(client, s1, "regression")
    triage(client, s4, "pre_existing")
    return s1, s4


def not_a_product_fault(*named: str) -> str:
    return (
        "a defect describes a fault of the product, so every execution needs a current triage regression or"
        f" pre_existing: {', '.join(named)}; triage each one first"
    )


def test_register_defect_needs_a_triage_regression_or_pre_existing_of_every_execution(shop):
    project, client = shop
    s1, s2, s3, s4 = (project.scenario.executions[s] for s in (S1, S2, S3, S4))

    def register(*execution_ids):
        arguments = {"title": "t", "severity": "high", "execution_ids": list(execution_ids), "steps": []}
        return lambda: client.call("memory", "register_defect", arguments)

    assert refused(shop, register(s1)) == not_a_product_fault(f"execution {s1} of TC-020 (not triaged)")
    triage(client, s3, "test_defect")
    assert refused(shop, register(s3)) == not_a_product_fault(f"execution {s3} of TC-011 (test_defect)")
    triage(client, s2, "expected_change", "REQ-004 has Changed: v1.1.")
    assert refused(shop, register(s2)) == not_a_product_fault(f"execution {s2} of TC-014 (expected_change)")
    triage(client, s1, "regression")
    assert refused(shop, register(s1, s2, s3)) == not_a_product_fault(
        f"execution {s2} of TC-014 (expected_change)", f"execution {s3} of TC-011 (test_defect)"
    )
    assert register(s1)() == {"defect_id": "DEF-001"}
    triage(client, s4, "pre_existing")
    assert register(s4)() == {"defect_id": "DEF-002"}


def test_link_defect_needs_a_triage_regression_or_pre_existing_of_every_execution(shop):
    project, client = shop
    s1, _ = product_faults(shop)
    client.call("memory", "register_defect", {"title": "t", "severity": "high", "execution_ids": [s1], "steps": []})
    run = project.scenario.full_candidate_run  # RUN-0002, against v1.1
    shipping, coupon, tax = (execution_of(project, run, s) for s in (S1, S2, S4))

    def link(*execution_ids):
        arguments = {"defect_id": "DEF-001", "execution_ids": list(execution_ids)}
        return lambda: client.call("memory", "link_defect", arguments)

    assert refused(shop, link(shipping)) == not_a_product_fault(f"execution {shipping} of TC-020 (not triaged)")
    triage(client, shipping, "test_defect")
    assert refused(shop, link(shipping)) == not_a_product_fault(f"execution {shipping} of TC-020 (test_defect)")
    triage(client, coupon, "expected_change", "REQ-004 has Changed: v1.1.")
    assert refused(shop, link(coupon)) == not_a_product_fault(f"execution {coupon} of TC-014 (expected_change)")
    triage(client, shipping, "regression", "Previously test_defect; it passed against the baseline.", replace=True)
    assert link(shipping)() == {"defect_id": "DEF-001", "execution_ids": [shipping, s1]}
    triage(client, tax, "pre_existing")
    assert link(tax)() == {"defect_id": "DEF-001", "execution_ids": [shipping, tax, s1]}


def test_register_defect_takes_expected_and_actual_from_the_first_execution(shop):
    _, client = shop
    s1, s4 = product_faults(shop)
    arguments = {"title": "Shipping is not charged", "severity": "high", "execution_ids": [s1, s4],
                 "steps": ["Add products for 100.00", "Apply a 10% coupon", "Read the total"]}  # fmt: skip
    assert client.call("memory", "register_defect", arguments) == {"defect_id": "DEF-001"}
    [defect] = client.call("memory", "get_defects")["defects"]
    assert {
        key: defect[key] for key in ("id", "title", "severity", "status", "detected_run_id", "actual", "steps")
    } == {
        "id": "DEF-001",
        "title": "Shipping is not charged",
        "severity": "high",
        "status": "open",
        "detected_run_id": "RUN-0004",
        "actual": "AssertionError: shipping 0.00 for a discounted subtotal of 90.00, expected 5.00",
        "steps": ["Add products for 100.00", "Apply a 10% coupon", "Read the total"],
    }
    assert "expected" not in defect  # a discovered test case has no expected result
    assert defect["executions"] == [
        {"execution_id": s1, "run_id": "RUN-0004", "test_case_id": "TC-020", "result": "failed"},
        {"execution_id": s4, "run_id": "RUN-0004", "test_case_id": "TC-022", "result": "failed"},
    ]


def test_register_defect_errors(shop):
    project, client = shop
    s1 = project.scenario.executions[S1]
    passed = execution_of(project, project.scenario.evaluated_run, V1_0_TESTS[0])

    def register(**changes):
        arguments = {"title": "t", "severity": "high", "execution_ids": [s1], "steps": []} | changes
        return lambda: client.call("memory", "register_defect", arguments)

    before = dump(project.path)
    assert error_of(register(execution_ids=[s1, passed])).code == "invalid_state"
    assert error_of(register(execution_ids=[s1, 99_999])).code == "not_found"
    for invalid in ({"execution_ids": []}, {"execution_ids": [s1, s1]}, {"severity": "blocker"}, {"title": ""}):
        assert error_of(register(**invalid)).code == "invalid_argument", invalid
    assert dump(project.path) == before


def test_register_defect_refuses_a_test_case_with_an_open_defect_and_link_defect_takes_it(shop):
    project, client = shop
    s1, _ = product_faults(shop)
    earlier = execution_of(project, project.scenario.full_candidate_run, S1)  # RUN-0002, the same failure of TC-020
    triage(client, earlier, "regression")
    client.call("memory", "register_defect", {"title": "t", "severity": "high", "execution_ids": [s1], "steps": []})
    arguments = {"title": "Again", "severity": "high", "execution_ids": [earlier], "steps": []}
    message = refused(shop, lambda: client.call("memory", "register_defect", arguments))
    assert message == (
        f"a test case with an open defect gets no second one: execution {earlier} of TC-020 (DEF-001); link each one"
        " to its defect instead"
    )
    linked = client.call("memory", "link_defect", {"defect_id": "DEF-001", "execution_ids": [earlier]})
    assert linked == {"defect_id": "DEF-001", "execution_ids": [earlier, s1]}


def test_link_defect_adds_executions_of_a_later_failure(shop):
    project, client = shop
    s1, s4 = product_faults(shop)
    earlier = execution_of(project, project.scenario.full_candidate_run, S1)  # RUN-0002, the same failure
    triage(client, earlier, "regression")
    client.call("memory", "register_defect", {"title": "t", "severity": "high", "execution_ids": [s1], "steps": []})
    linked = client.call("memory", "link_defect", {"defect_id": "DEF-001", "execution_ids": [earlier]})
    assert linked == {"defect_id": "DEF-001", "execution_ids": [earlier, s1]}
    message = refused(
        shop, lambda: client.call("memory", "link_defect", {"defect_id": "DEF-001", "execution_ids": [s1]})
    )
    assert message == f"execution {s1} is already linked to DEF-001"
    passed = execution_of(project, project.scenario.evaluated_run, V1_0_TESTS[0])
    for arguments, code in (
        ({"defect_id": "DEF-001", "execution_ids": [passed]}, "invalid_state"),
        ({"defect_id": "DEF-999", "execution_ids": [s1]}, "not_found"),
        ({"defect_id": "DEF-001", "execution_ids": [99_999]}, "not_found"),
        ({"defect_id": "DEF-001", "execution_ids": []}, "invalid_argument"),
    ):
        assert error_of(lambda: client.call("memory", "link_defect", arguments)).code == code, arguments  # noqa: B023
    client.call("memory", "close_defect", {"defect_id": "DEF-001", "reason": "obsolete"})
    message = refused(
        shop, lambda: client.call("memory", "link_defect", {"defect_id": "DEF-001", "execution_ids": [s4]})
    )
    assert message == "DEF-001 is already closed"


def test_close_defect_records_the_user_and_the_reason(shop):
    _, client = shop
    s1, _ = product_faults(shop)
    client.call("memory", "register_defect", {"title": "t", "severity": "high", "execution_ids": [s1], "steps": []})
    closed = client.call("memory", "close_defect", {"defect_id": "DEF-001", "reason": "fixed outside the scope"})
    assert closed == {"defect_id": "DEF-001", "status": "closed", "closed_by": "user"}
    [defect] = client.call("memory", "get_defects", {"status": "closed"})["defects"]
    assert (defect["closed_by"], defect["close_reason"], "closed_run_id" in defect) == (
        "user",
        "fixed outside the scope",
        False,
    )
    message = refused(shop, lambda: client.call("memory", "close_defect", {"defect_id": "DEF-001", "reason": "x"}))
    assert message == "DEF-001 is already closed"
    error = error_of(lambda: client.call("memory", "close_defect", {"defect_id": "DEF-999", "reason": "x"}))
    assert error.code == "not_found"


def test_get_defects_filters_by_status(shop):
    _, client = shop
    s1, s4 = product_faults(shop)
    for execution_id in (s1, s4):
        arguments = {"title": "t", "severity": "low", "execution_ids": [execution_id], "steps": []}
        client.call("memory", "register_defect", arguments)
    client.call("memory", "close_defect", {"defect_id": "DEF-002", "reason": "not wanted"})

    def ids(**arguments):
        return [d["id"] for d in client.call("memory", "get_defects", arguments)["defects"]]

    assert (ids(), ids(status="open"), ids(status="closed")) == (["DEF-001", "DEF-002"], ["DEF-001"], ["DEF-002"])
    assert error_of(lambda: client.call("memory", "get_defects", {"status": "fixed"})).code == "invalid_argument"


# EC-08 and the decision


def test_the_triage_of_the_oracle_through_the_server_meets_ec_08_and_keeps_the_decision(shop):
    project, client = shop
    executions = project.scenario.executions
    criteria, _ = decision_of(project.path)
    assert criteria["EC-08"].state == "not_met"  # four failures without triage
    triage(client, executions[S3], "flaky")
    triage(client, executions[S2], "expected_change")
    triage(client, executions[S1], "regression")
    triage(client, executions[S4], "pre_existing")
    criteria, _ = decision_of(project.path)
    assert criteria["EC-08"].state == "not_met"  # the regression has no defect yet
    defect = {"title": "Shipping", "severity": "high", "execution_ids": [executions[S1]], "steps": []}
    client.call("memory", "register_defect", defect)
    criteria, decision = decision_of(project.path)
    assert criteria["EC-08"].state == "met"
    assert criteria["EC-08"].value == {
        "failures": 4,
        "triaged_failures": 4,
        "regressions": 1,
        "regressions_with_defect": 1,
    }
    assert decision.outcome == "do_not_release"
    assert [(r.id, r.state) for r in decision.reasons] == [
        ("EC-01", "not_met"),
        ("EC-05", "not_met"),
        ("EC-09", "not_met"),
    ]
