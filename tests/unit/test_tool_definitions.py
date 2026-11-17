"""The definitions of the bundled tools: description sizes (mcp-tools.md, Descriptions), strict schemas and no input
for an execution status or result (INV-03)."""

import jsonschema
import pytest

from retroagent.servers.git.server import TOOLS as GIT
from retroagent.servers.memory.server import TOOLS as MEMORY
from retroagent.servers.test_runner.server import TOOLS as TEST_RUNNER

TOOLS = {"git": GIT, "memory": MEMORY, "test_runner": TEST_RUNNER}
ALL = [(server, tool) for server, tools in TOOLS.items() for tool in tools]
IDS = [f"{server}.{tool.name}" for server, tool in ALL]

TOOL_LIMIT, PARAMETER_LIMIT = 300, 150
RESULT_WORDS = {"status", "result", "results", "outcome", "verdict", "passed", "failed", "attempts", "flaky"}


def schemas(schema: dict, path: str = ""):
    """Every object schema inside ``schema``, with its path."""
    if schema.get("type") == "object":
        yield path or "/", schema
        for name, child in schema.get("properties", {}).items():
            yield from schemas(child, f"{path}/{name}")
    if "items" in schema:
        yield from schemas(schema["items"], f"{path}[]")


def parameters(schema: dict, path: str = ""):
    """Every parameter: each property, at any depth, with its path."""
    for name, child in schema.get("properties", {}).items():
        yield f"{path}/{name}", child
        yield from parameters(child, f"{path}/{name}")
    if "items" in schema:
        yield from parameters(schema["items"], f"{path}[]")


def test_the_bundled_tools_of_slice_3():
    assert {server: [t.name for t in tools] for server, tools in TOOLS.items()} == {
        "git": ["resolve_ref", "analyze_changes", "get_diff", "read_file", "list_files"],
        "memory": [
            "sync_requirements", "get_requirements", "get_analysis", "save_impact", "add_risk", "get_risks",
        ],
        "test_runner": ["run_tests"],
    }  # fmt: skip


@pytest.mark.parametrize(("server", "tool"), ALL, ids=IDS)
def test_descriptions_fit_their_limits(server, tool):
    assert tool.description and len(tool.description) <= TOOL_LIMIT, f"{len(tool.description)} characters"
    for path, parameter in parameters(tool.parameters):
        description = parameter.get("description")
        if not path.endswith("[]"):
            assert description, f"{path} has no description"
        if description:
            assert len(description) <= PARAMETER_LIMIT, f"{path}: {len(description)} characters"


@pytest.mark.parametrize(("server", "tool"), ALL, ids=IDS)
def test_schemas_are_valid_and_accept_no_other_property(server, tool):
    jsonschema.Draft202012Validator.check_schema(tool.parameters)
    for path, schema in schemas(tool.parameters):
        assert schema.get("additionalProperties") is False, path


@pytest.mark.parametrize(("server", "tool"), ALL, ids=IDS)
def test_no_input_is_an_execution_status_or_result(server, tool):
    names = {path.rsplit("/", 1)[-1].removesuffix("[]") for path, _ in parameters(tool.parameters)}
    assert not names & RESULT_WORDS


def test_the_limit_checks_fail_over_300_and_150_characters():
    # The checks above are only as good as their failure: a description one character too long fails them.
    from retroagent.servers.serving import Tool, schema

    too_long = Tool("t", "x" * 301, schema({"p": {"type": "string", "description": "y" * 151}}), lambda c: {})
    with pytest.raises(AssertionError):
        test_descriptions_fit_their_limits("s", too_long)
    long_parameter = Tool("t", "x" * 300, schema({"p": {"type": "string", "description": "y" * 151}}), lambda c: {})
    with pytest.raises(AssertionError):
        test_descriptions_fit_their_limits("s", long_parameter)
    test_descriptions_fit_their_limits("s", Tool("t", "x" * 300, schema({"p": {"description": "y" * 150}}), None))
