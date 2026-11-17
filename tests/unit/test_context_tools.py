"""Tool definitions: names, tool sets, plan mode, user-only tools, order, and the tools that the bundled steering
and skills name."""

import re
from importlib.resources import files

import pytest
from fixtures.tool_definitions import DOCUMENTED, with_placeholders

from retroagent.context import tools
from retroagent.llm.provider import ToolDefinition

ALL = sorted(tools.normalize(name) for name in DOCUMENTED)

# The skill of each model step of /cycle (runtime.md, Cycle command).
STEP_SKILLS = {
    "analyze": "impact-analysis",
    "select": "test-selection",
    "design": "test-design",
    "implement": "test-design",
    "triage": "failure-triage",
    "report": "test-reporting",
}
TOOL_NAME = re.compile(r"\b[a-z_]+__[a-z_]+\b")


def servers() -> dict[str, list[ToolDefinition]]:
    """Every documented tool, as the servers report them: bare names, real definitions where the tool exists."""
    return with_placeholders()


def names(definitions) -> list[str]:
    return [d.name for d in definitions]


def test_names():
    assert tools.exposed_name("test_runner", "run_tests") == "test_runner__run_tests"
    assert tools.normalize("test_runner.run_tests") == "test_runner__run_tests"
    assert tools.normalize("memory__get_suite") == "memory__get_suite"
    assert tools.split("test_runner__run_tests") == ("test_runner", "run_tests")
    assert tools.split("git.get_diff") == ("git", "get_diff")
    with pytest.raises(ValueError):
        tools.split("load_skill")
    with pytest.raises(ValueError):
        tools.exposed_name("a__b", "c")


def test_a_free_message_exposes_every_tool_but_the_user_only_ones_sorted_by_name():
    definitions = tools.tool_definitions(servers(), mode="default")
    assert names(definitions) == [name for name in ALL if name != "memory__close_defect"]
    analyze_changes = next(d for d in servers()["git"] if d.name == "analyze_changes")
    assert definitions[0] == ToolDefinition(
        "git__analyze_changes", analyze_changes.description, analyze_changes.parameters
    )


def test_auto_mode_exposes_the_same_tools_as_default():
    assert tools.tool_definitions(servers(), mode="auto") == tools.tool_definitions(servers(), mode="default")


def test_plan_mode_leaves_out_the_tools_that_need_a_permission():
    exposed = names(tools.tool_definitions(servers(), mode="plan"))
    assert "test_runner__write_test" not in exposed
    assert "test_runner__run_tests" not in exposed
    assert "test_runner__get_evidence" in exposed
    assert len(exposed) == len(ALL) - 3


@pytest.mark.parametrize(
    ("tool_set", "extra"),
    [
        ("analyze", []),
        ("select", ["test_runner__run_tests"]),
        ("design", []),
        ("implement", ["test_runner__get_evidence", "test_runner__write_test"]),
        ("triage", ["test_runner__get_evidence"]),
    ],
)
def test_tool_sets_of_the_model_steps(tool_set, extra):
    exposed = names(tools.tool_definitions(servers(), mode="default", tool_set=tool_set))
    base = [n for n in ALL if n.split("__")[0] in ("runtime", "git", "memory") and n != "memory__close_defect"]
    assert exposed == sorted(base + extra)


def test_the_report_tool_set():
    exposed = names(tools.tool_definitions(servers(), mode="default", tool_set="report"))
    assert {n.split("__")[0] for n in exposed} == {"runtime", "memory", "reports"}
    assert "memory__close_defect" not in exposed
    assert len(exposed) == 2 + 19 + 4


def test_plan_mode_applies_inside_a_tool_set():
    exposed = names(tools.tool_definitions(servers(), mode="plan", tool_set="select"))
    assert "test_runner__run_tests" not in exposed


def test_a_tool_defined_twice_or_an_unknown_mode_is_an_error():
    definition = ToolDefinition("get_suite", "d", {})
    with pytest.raises(ValueError, match="defined twice"):
        tools.tool_definitions({"memory": [definition, definition]}, mode="default")
    with pytest.raises(ValueError, match="unknown mode"):
        tools.tool_definitions(servers(), mode="yolo")


def bundled_texts() -> dict[str, str]:
    resources = files("retroagent.resources")
    texts = {f"steering/{f.name}": f.read_text(encoding="utf-8") for f in (resources / "steering").iterdir()}
    for folder in (resources / "skills").iterdir():
        texts[folder.name] = (folder / "SKILL.md").read_text(encoding="utf-8")
    return texts


def test_every_tool_named_in_the_bundled_steering_and_skills_is_documented():
    for source, text in bundled_texts().items():
        for name in TOOL_NAME.findall(text):
            assert name in ALL, f"{source} names {name}"


def test_each_skill_names_only_tools_that_its_tool_set_exposes():
    texts = bundled_texts()
    for skill in sorted(set(STEP_SKILLS.values())):
        exposed = set()
        for step in (step for step, s in STEP_SKILLS.items() if s == skill):
            exposed |= set(names(tools.tool_definitions(servers(), mode="default", tool_set=step)))
        named = set(TOOL_NAME.findall(texts[skill]))
        assert named, skill
        assert named <= exposed, f"{skill} names {sorted(named - exposed)}"
