"""INV-13 and INV-03 for every tool registered by the bundled servers, through real server processes: an unknown
identifier, path or ref fails with ``not_found`` and writes nothing, and no tool accepts an execution status or
result."""

import pytest
from fixtures.example_project import example_project
from fixtures.mcp_project import dump, error_of, open_session

from retroagent.mcp_client import Client

PRICING = {"module": "pricing", "files": ["src/shop/pricing.py"], "risk_level": "high", "reason": "r"}
DESIGN = {"title": "t", "objective": "o", "priority": "high", "preconditions": [], "input_data": [], "steps": ["s"],
          "expected_result": "e", "requirement_ids": ["REQ-002"], "selection_reason": "r"}  # fmt: skip

# Every reference input of every tool, with a value that does not exist.
UNKNOWN_REFERENCES = [
    ("git", "resolve_ref", {"ref": "v9.9"}),
    ("git", "get_diff", {"path": "src/shop/nothing.py"}),
    ("git", "get_diff", {"path": "src/shop/pricing.py", "analysis_id": 999}),
    ("git", "read_file", {"path": "src/shop/nothing.py", "version": "base"}),
    ("git", "list_files", {"version": "base", "path": "nowhere"}),
    ("memory", "get_requirements", {"ids": ["REQ-001", "REQ-099"]}),
    ("memory", "get_analysis", {"analysis_id": 999}),
    ("memory", "save_impact", {"analysis_id": 999, "modules": [PRICING], "requirements": [], "not_impacted": []}),
    ("memory", "save_impact",
     {"analysis_id": 1, "modules": [{**PRICING, "files": ["nothing.py"]}], "requirements": [], "not_impacted": []}),
    ("memory", "save_impact",
     {"analysis_id": 1, "modules": [PRICING], "requirements": [{"requirement_id": "REQ-099", "reason": "r"}],
      "not_impacted": []}),
    ("memory", "save_impact",
     {"analysis_id": 1, "modules": [PRICING], "requirements": [],
      "not_impacted": [{"requirement_id": "REQ-099", "reason": "r"}]}),
    ("memory", "add_risk", {"description": "d", "level": "low", "requirement_ids": ["REQ-001", "REQ-099"]}),
    ("memory", "save_suite", {"analysis_id": 999, "items": []}),
    ("memory", "save_suite",
     {"analysis_id": 1, "items": [{"test_case_id": "TC-999", "position": 1, "selection_reason": "r"}]}),
    ("memory", "get_suite", {"suite_id": 999}),
    ("memory", "design_test_case", {**DESIGN, "requirement_ids": ["REQ-002", "REQ-099"]}),
    ("memory", "update_test_case", {"test_case_id": "TC-999", "fields": {"title": "x"}}),
    ("memory", "update_test_case", {"test_case_id": "TC-001", "fields": {"requirement_ids": ["REQ-099"]}}),
    ("memory", "retire_test_case", {"test_case_id": "TC-999", "reason": "r"}),
    ("memory", "get_test_cases", {"ids": ["TC-001", "TC-999"]}),
    ("memory", "get_test_cases", {"requirement_id": "REQ-099"}),
    ("memory", "get_executions", {"run_id": "RUN-9999"}),
    ("memory", "get_test_case_history", {"test_case_id": "TC-999"}),
    ("test_runner", "run_tests", {"version": "base", "scope": "selected", "test_case_ids": ["TC-999"]}),
]  # fmt: skip
WITHOUT_REFERENCES = {"git.analyze_changes", "memory.sync_requirements", "memory.get_risks", "memory.get_runs"}


@pytest.fixture(scope="module")
def shop(tmp_path_factory, pip_cache):
    """shop-api with its requirements, analysis 1 of v1.0..v1.1 without an impact, and its suite with TC-001."""
    with example_project(tmp_path_factory, pip_cache) as path:
        with Client(path, open_session(path)) as client:
            client.call("memory", "sync_requirements")
            assert client.call("git", "analyze_changes")["analysis_id"] == 1
            client.call("memory", "save_suite", {"analysis_id": 1, "items": []})
            assert client.call("memory", "design_test_case", DESIGN)["test_case_id"] == "TC-001"
            yield path, client


def test_every_reference_input_is_covered(shop):
    _, client = shop
    registered = {f"{server}.{tool.name}" for server, tools in client.tools().items() for tool in tools}
    covered = {f"{server}.{tool}" for server, tool, _ in UNKNOWN_REFERENCES}
    assert covered | WITHOUT_REFERENCES == registered


@pytest.mark.parametrize(("server", "tool", "arguments"), UNKNOWN_REFERENCES, ids=lambda v: str(v)[:60])
def test_an_unknown_reference_fails_with_not_found_and_writes_nothing(shop, server, tool, arguments):
    path, client = shop
    before = dump(path)
    assert error_of(lambda: client.call(server, tool, arguments)).code == "not_found"
    assert dump(path) == before


def test_a_status_inside_the_fields_of_a_test_case_is_refused(shop):
    path, client = shop
    before = dump(path)
    for fields in ({"status": "implemented"}, {"title": "x", "result": "passed"}):
        arguments = {"test_case_id": "TC-001", "fields": fields}
        assert error_of(lambda: client.call("memory", "update_test_case", arguments)).code == "invalid_argument"  # noqa: B023
    assert dump(path) == before


def test_no_tool_accepts_an_execution_status_or_result(shop):
    path, client = shop
    for server, tools in client.tools().items():
        for tool in tools:
            for extra in ({"result": "passed"}, {"status": "executed"}, {"outcome": "passed"}):
                before = dump(path)
                error = error_of(lambda: client.call(server, tool.name, extra))  # noqa: B023
                assert error.code == "invalid_argument", f"{server}.{tool.name}: {error}"
                assert dump(path) == before
