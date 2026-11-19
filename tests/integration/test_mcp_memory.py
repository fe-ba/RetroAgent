"""The ``memory`` server of slice 3 through a real server process and the real client, on shop-api: requirement
synchronization, and the tools of impact analysis with each error code they can return."""

import subprocess
from types import SimpleNamespace

import pytest
from fixtures.example_project import example_project
from fixtures.mcp_project import RESULT_CHAR_LIMIT, dump, error_of, open_session, set_versions
from fixtures.reference_scenario import CHANGE_SET

from retroagent.mcp_client import Client
from retroagent.memory import connect, design
from retroagent.memory import requirements as stored_requirements

REQ_004_CHANGE = {
    "version": "v1.1",
    "description": "Two different coupons can be combined; before, only one coupon applied per order.",
}


def counts(result: dict) -> tuple[int, int, int]:
    return result["read"], result["added"], result["changed"]


# sync_requirements ---------------------------------------------------------------------------------------------------


def test_sync_reads_the_candidate_and_a_second_sync_changes_nothing(tmp_path_factory, pip_cache):
    with example_project(tmp_path_factory, pip_cache) as path:
        conn = connect(path)
        project_test = design.add_project_suite_test_case(
            conn, test_id="tests.test_cart::test_req_002_add_one", implementation="tests/test_cart.py::x"
        )
        conn.close()
        session_id = open_session(path, "v1.0", "v1.0")
        with Client(path, session_id) as client:
            first = client.call("memory", "sync_requirements")
            assert counts(first) == (7, 7, 0)
            assert first["name_links_added"] == 1  # the project test that names REQ-002
            assert first["unparsed"] == [] and first["unresolved_versions"] == []

            set_versions(path, session_id, "v1.0", "v1.1")
            second = client.call("memory", "sync_requirements")
            assert counts(second) == (8, 1, 1)  # REQ-008 is new, REQ-004 changed
            found = client.call("memory", "get_requirements", {"ids": ["REQ-004", "REQ-008"]})["requirements"]
            req_004, req_008 = found
            assert req_004["changes"] == [REQ_004_CHANGE]
            assert "Up to two different coupons can be combined" in req_004["description"]
            assert (req_008["id"], req_008["since"], req_008["priority"], req_008["changes"]) == (
                "REQ-008", "v1.1", "low", [],
            )  # fmt: skip

            before = client.call("memory", "get_requirements")["requirements"]
            rows_before = [line for line in dump(path) if not line.startswith('INSERT INTO "requirement" ')]
            third = client.call("memory", "sync_requirements")
            assert counts(third) == (8, 0, 0) and third["name_links_added"] == 0
            after = client.call("memory", "get_requirements")["requirements"]
            assert [_without_sync_time(r) for r in after] == [_without_sync_time(r) for r in before]
            assert [line for line in dump(path) if not line.startswith('INSERT INTO "requirement" ')] == rows_before
        conn = connect(path)
        links = conn.execute("SELECT requirement_id FROM test_case_requirement WHERE test_case_id = ?", (project_test,))
        assert [row[0] for row in links] == ["REQ-002"]
        conn.close()


def _without_sync_time(requirement: dict) -> dict:
    return {key: value for key, value in requirement.items() if key != "synced_at"}


BROKEN = """
## REQ-009: Gift cards

- Priority: urgent

## REQ-010: Returns

A delivered order can be returned within 30 days.

- Priority: low
- Changed: v9.9 - Returns within 60 days.
"""


def test_what_cannot_be_parsed_is_reported_not_dropped(tmp_path_factory, pip_cache):
    with example_project(tmp_path_factory, pip_cache) as path:
        document = path / "docs" / "requirements.md"
        document.write_text(document.read_text(encoding="utf-8") + BROKEN, encoding="utf-8")
        git = lambda *args: subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)  # noqa: E731
        git("-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-am", "broken requirements")
        git("tag", "broken")
        config = path / ".retro" / "config.yaml"
        original = config.read_text(encoding="utf-8")
        config.write_text(
            original.replace("requirements: [docs/requirements.md]",
                             "requirements: [docs/requirements.md, docs/missing.md, 'notes/*.md']"),
            encoding="utf-8",
        )  # fmt: skip
        session_id = open_session(path, "v1.1", "broken")
        with Client(path, session_id) as client:
            result = client.call("memory", "sync_requirements")
            assert counts(result) == (9, 9, 0)  # REQ-001 to REQ-008 and REQ-010
            assert result["unparsed"] == [
                {"file": "docs/missing.md", "requirement": None,
                 "reason": "is not a file of the candidate version broken"},
                {"file": "notes/*.md", "requirement": None,
                 "reason": "matches no file in the candidate version broken"},
                {"file": "docs/requirements.md", "requirement": "REQ-009",
                 "reason": "REQ-009: Priority must be high, medium or low, not 'urgent'"},
            ]  # fmt: skip
            assert result["unresolved_versions"] == [
                {"requirement_id": "REQ-010", "field": "Changed", "version": "v9.9"}
            ]
            assert error_of(lambda: client.call("memory", "get_requirements", {"ids": ["REQ-009"]})).code == "not_found"

            config.write_text(original.replace("  requirements: [docs/requirements.md]\n", ""), encoding="utf-8")
            assert error_of(lambda: client.call("memory", "sync_requirements")).code == "invalid_state"
            config.write_text(original, encoding="utf-8")
            set_versions(path, session_id, "v1.0", None)
            assert error_of(lambda: client.call("memory", "sync_requirements")).code == "invalid_state"
            assert error_of(lambda: client.call("memory", "sync_requirements", {"force": True})).code == (
                "invalid_argument"
            )


# The tools of impact analysis ----------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shop(tmp_path_factory, pip_cache):
    """shop-api with its requirements synchronized, and one client per kind of session."""
    with example_project(tmp_path_factory, pip_cache) as path:
        clients: dict[tuple, Client] = {}

        def client(base="v1.0", candidate="v1.1") -> Client:
            if (base, candidate) not in clients:
                clients[base, candidate] = Client(path, open_session(path, base, candidate, RESULT_CHAR_LIMIT))
                clients[base, candidate].start()
            return clients[base, candidate]

        client().call("memory", "sync_requirements")
        yield SimpleNamespace(path=path, client=client)
        for started in clients.values():
            started.stop()


def call(shop, server, tool, arguments=None, **session):
    return shop.client(**session).call(server, tool, arguments or {})


def code(shop, tool, arguments=None, **session) -> str:
    return error_of(lambda: call(shop, "memory", tool, arguments, **session)).code


def new_analysis(shop) -> int:
    return call(shop, "git", "analyze_changes")["analysis_id"]


PRICING = {"module": "pricing", "files": ["src/shop/pricing.py"], "risk_level": "high", "reason": "Shipping order."}
COUPONS = {"requirement_id": "REQ-004", "reason": "Documented change in v1.1."}
EVERY_REQUIREMENT = [f"REQ-00{n}" for n in range(1, 9)]  # in effect at v1.1


def not_impacted(*requirement_ids: str) -> list[dict]:
    return [{"requirement_id": r, "reason": "No changed file takes part in it."} for r in requirement_ids]


OTHERS = not_impacted(*(r for r in EVERY_REQUIREMENT if r != "REQ-004"))  # every requirement but REQ-004


def test_get_requirements(shop):
    every = call(shop, "memory", "get_requirements")["requirements"]
    assert [r["id"] for r in every] == [f"REQ-00{n}" for n in range(1, 9)]
    (req_004,) = call(shop, "memory", "get_requirements", {"ids": ["REQ-004"]})["requirements"]
    assert req_004["priority"] == "high" and req_004["changes"] == [REQ_004_CHANGE]
    assert req_004["source_file"] == "docs/requirements.md"


def test_get_requirements_with_empty_ids_filters_nothing(shop):
    # mcp-tools.md, Empty filters: an empty list has the same effect as an absent one.
    every = call(shop, "memory", "get_requirements")["requirements"]
    assert len(every) == 8 and call(shop, "memory", "get_requirements", {"ids": []})["requirements"] == every


def test_get_requirements_errors(shop):
    assert code(shop, "get_requirements", {"ids": ["REQ-004", "REQ-099"]}) == "not_found"
    assert code(shop, "get_requirements", {"ids": "REQ-004"}) == "invalid_argument"


def test_get_analysis_returns_the_change_set_and_the_impact(shop):
    analysis_id = new_analysis(shop)
    empty = call(shop, "memory", "get_analysis")
    assert empty["analysis_id"] == analysis_id
    assert empty["files"] == CHANGE_SET
    assert empty["modules"] == [] and empty["requirements"] == []
    assert empty["base"] == {"ref": "v1.0", "commit": "c7d45ada468e3746c498cb3417999e117154a942"}
    assert empty["not_impacted"] == []
    arguments = {"analysis_id": analysis_id, "modules": [PRICING], "requirements": [COUPONS], "not_impacted": OTHERS}
    call(shop, "memory", "save_impact", arguments)
    stored = call(shop, "memory", "get_analysis", {"analysis_id": analysis_id})
    assert stored["modules"] == [PRICING]
    assert stored["requirements"] == [COUPONS]
    assert stored["not_impacted"] == OTHERS


def test_get_analysis_errors(shop):
    assert code(shop, "get_analysis", {"analysis_id": 999}) == "not_found"
    assert code(shop, "get_analysis", base="v1.1", candidate="v1.2") == "not_found"  # no analysis of that pair
    assert code(shop, "get_analysis", base=None) == "invalid_state"
    assert code(shop, "get_analysis", {"analysis_id": "latest"}) == "invalid_argument"


def test_save_impact_records_the_impact_once(shop):
    analysis_id = new_analysis(shop)
    cart = {"module": "cart", "files": ["src/shop/cart.py"], "risk_level": "medium", "reason": "Stock check."}
    arguments = {
        "analysis_id": analysis_id,
        "modules": [PRICING, cart],
        "requirements": [COUPONS],
        "not_impacted": OTHERS,
    }
    assert call(shop, "memory", "save_impact", arguments) == {
        "analysis_id": analysis_id,
        "modules": 2,
        "requirements": 1,
        "not_impacted": 7,
    }
    assert code(shop, "save_impact", arguments) == "invalid_state"


def test_save_impact_errors(shop):
    analysis_id = new_analysis(shop)

    def impact(modules=(PRICING,), requirements=(COUPONS,), target=analysis_id, others=OTHERS) -> dict:
        return {"analysis_id": target, "modules": list(modules), "requirements": list(requirements),
                "not_impacted": list(others)}  # fmt: skip

    unknown_file = {**PRICING, "files": ["src/shop/money.py"]}
    assert code(shop, "save_impact", impact(modules=[unknown_file])) == "not_found"
    assert code(shop, "save_impact", impact(requirements=[{"requirement_id": "REQ-099", "reason": "x"}])) == "not_found"
    assert code(shop, "save_impact", impact(others=[*OTHERS, *not_impacted("REQ-099")])) == "not_found"
    assert code(shop, "save_impact", impact(target=999)) == "not_found"
    assert code(shop, "save_impact", impact(modules=[{**PRICING, "risk_level": "severe"}])) == "invalid_argument"
    assert code(shop, "save_impact", impact(modules=[])) == "invalid_argument"
    assert code(shop, "save_impact", impact(modules=[PRICING, PRICING])) == "invalid_argument"
    assert code(shop, "save_impact", {"analysis_id": analysis_id, "modules": [PRICING]}) == "invalid_argument"
    assert code(shop, "save_impact", {"analysis_id": analysis_id, "modules": [PRICING], "requirements": []}) == (
        "invalid_argument"
    )  # not_impacted is required, even when empty
    # Nothing of the refused calls was written: the impact can still be recorded.
    assert call(shop, "memory", "save_impact", impact())["modules"] == 1


def message(shop, tool, arguments, **session) -> tuple[str, str]:
    error = error_of(lambda: call(shop, "memory", tool, arguments, **session))
    return error.code, error.message


def test_save_impact_refuses_one_missing_requirement_and_names_it(shop):
    analysis_id = new_analysis(shop)
    others = [entry for entry in OTHERS if entry["requirement_id"] != "REQ-001"]
    arguments = {"analysis_id": analysis_id, "modules": [PRICING], "requirements": [COUPONS], "not_impacted": others}
    error_code, text = message(shop, "save_impact", arguments)
    assert error_code == "invalid_argument"
    assert "missing: REQ-001" in text and "v1.1" in text
    assert call(shop, "memory", "get_analysis")["modules"] == []  # nothing was written
    arguments["not_impacted"] = OTHERS  # the model decides it and calls again
    assert call(shop, "memory", "save_impact", arguments)["not_impacted"] == 7


def test_save_impact_names_every_missing_requirement_in_one_message(shop):
    analysis_id = new_analysis(shop)
    arguments = {"analysis_id": analysis_id, "modules": [PRICING], "requirements": [COUPONS], "not_impacted": []}
    error_code, text = message(shop, "save_impact", arguments)
    assert error_code == "invalid_argument"
    assert "missing: REQ-001, REQ-002, REQ-003, REQ-005, REQ-006, REQ-007, REQ-008" in text


def test_save_impact_refuses_a_requirement_decided_twice(shop):
    analysis_id = new_analysis(shop)
    twice = {
        "analysis_id": analysis_id,
        "modules": [PRICING],
        "requirements": [COUPONS, COUPONS],
        "not_impacted": OTHERS,
    }
    error_code, text = message(shop, "save_impact", twice)
    assert error_code == "invalid_argument" and "repeated: REQ-004" in text
    in_both = {"analysis_id": analysis_id, "modules": [PRICING], "requirements": [COUPONS],
               "not_impacted": [*OTHERS, *not_impacted("REQ-004")]}  # fmt: skip
    error_code, text = message(shop, "save_impact", in_both)
    assert error_code == "invalid_argument" and "repeated: REQ-004" in text and "missing" not in text
    one_missing_one_repeated = {**twice, "not_impacted": OTHERS[1:]}
    error_code, text = message(shop, "save_impact", one_missing_one_repeated)
    assert "missing: REQ-001" in text and "repeated: REQ-004" in text  # every problem in one message


def test_add_risk_and_get_risks(shop):
    analysis_id = new_analysis(shop)
    first = call(shop, "memory", "add_risk", {"description": "Shipping charged wrongly.", "level": "high",
                                             "requirement_ids": ["REQ-005", "REQ-003", "REQ-005"]})  # fmt: skip
    second = call(shop, "memory", "add_risk", {"description": "No test for the stock check.", "level": "medium"})
    assert first["analysis_id"] == second["analysis_id"] == analysis_id
    risks = {risk["id"]: risk for risk in call(shop, "memory", "get_risks")["risks"]}
    assert risks[first["risk_id"]]["requirement_ids"] == ["REQ-003", "REQ-005"]
    assert risks[first["risk_id"]]["level"] == "high"
    assert risks[second["risk_id"]]["requirement_ids"] == []
    assert risks[second["risk_id"]]["analysis_id"] == analysis_id


def test_add_risk_errors(shop):
    new_analysis(shop)
    risk = {"description": "A risk.", "level": "low"}
    assert code(shop, "add_risk", {**risk, "requirement_ids": ["REQ-099"]}) == "not_found"
    assert code(shop, "add_risk", {**risk, "level": "critical"}) == "invalid_argument"
    assert code(shop, "add_risk", {"level": "low"}) == "invalid_argument"
    assert code(shop, "add_risk", risk, base="v1.1", candidate="v1.2") == "invalid_state"  # no analysis yet
    assert code(shop, "get_risks", {"level": "high"}) == "invalid_argument"


# Requirements in effect: a removal applies to the change when its ref is reachable from the candidate and not from
# the baseline (mcp-tools.md, save_impact; project-contract.md).


@pytest.fixture(scope="module")
def removals(tmp_path_factory, pip_cache):
    """shop-api whose memory holds only three requirements, removed in v1.0, v1.1 and v1.2 (stored directly)."""
    with example_project(tmp_path_factory, pip_cache) as path:
        conn = connect(path)
        for requirement_id, removed in (("REQ-901", "v1.1"), ("REQ-902", "v1.0"), ("REQ-903", "v1.2")):
            stored_requirements.add_requirement(
                conn, id=requirement_id, title="Old", description="Old.", source_file="docs/requirements.md",
                removed=removed,
            )  # fmt: skip
        conn.close()
        yield path


def missing_requirements(path, base: str, candidate: str) -> tuple[str, Client, dict]:
    """The refusal of an impact that decides no requirement, for an analysis of ``base..candidate``."""
    client = Client(path, open_session(path, base, candidate))
    client.start()
    analysis = client.call("git", "analyze_changes")
    module = {"module": "shop", "files": [analysis["files"][0]["path"]], "risk_level": "low", "reason": "r"}
    arguments = {"analysis_id": analysis["analysis_id"], "modules": [module], "requirements": [], "not_impacted": []}
    error = error_of(lambda: client.call("memory", "save_impact", arguments))
    assert error.code == "invalid_argument"
    return error.message.partition("missing: ")[2], client, arguments


def test_a_requirement_removed_in_the_candidate_is_decided_and_one_removed_earlier_or_later_is_not(removals):
    missing, client, arguments = missing_requirements(removals, "v1.0", "v1.1")
    try:
        assert missing == "REQ-901"  # removed in v1.1; REQ-902 was removed in v1.0, REQ-903 is removed in v1.2
        arguments["requirements"] = [{"requirement_id": "REQ-901", "reason": "Removed in v1.1."}]
        arguments["not_impacted"] = not_impacted("REQ-902")  # out of effect, but it exists: accepted
        assert client.call("memory", "save_impact", arguments)["requirements"] == 1
    finally:
        client.stop()


def test_versions_given_as_commit_hashes_use_the_same_rule(removals):
    missing, client, _ = missing_requirements(removals, "c7d45ad", "46a5ef0")  # v1.0 and v1.1
    client.stop()
    assert missing == "REQ-901"


def test_a_removal_in_a_skipped_version_must_be_decided(removals):
    missing, client, _ = missing_requirements(removals, "v1.0", "v1.2")
    client.stop()
    assert missing == "REQ-901, REQ-903"


def test_a_project_without_requirements_sends_two_empty_lists(tmp_path_factory, pip_cache):
    with example_project(tmp_path_factory, pip_cache) as path:
        with Client(path, open_session(path)) as client:
            analysis_id = client.call("git", "analyze_changes")["analysis_id"]
            arguments = {"analysis_id": analysis_id, "modules": [PRICING], "requirements": [], "not_impacted": []}
            assert client.call("memory", "save_impact", arguments)["not_impacted"] == 0
            stored = client.call("memory", "get_analysis")
            assert stored["requirements"] == [] and stored["not_impacted"] == []
