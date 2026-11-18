"""Tool definitions: names, tool sets, plan mode, user-only tools, order, and the tools that the bundled steering
and skills name."""

import re
from importlib.resources import files
from pathlib import Path

import pytest
from fixtures.tool_definitions import DOCUMENTED, STEP_OWN_TOOLS, STEP_READ_TOOLS, with_placeholders

from retroagent.context import tools
from retroagent.llm.provider import ToolDefinition

ALL = sorted(tools.normalize(name) for name in DOCUMENTED)
REPOSITORY = Path(__file__).resolve().parents[2]

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


def documented_access() -> dict[str, str]:
    """The access column of the Summary of docs/reference/mcp-tools.md, by exposed name."""
    text = (REPOSITORY / "docs" / "reference" / "mcp-tools.md").read_text(encoding="utf-8")
    summary = text.split("## Summary", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(r"^\| `([a-z_]+\.[a-z_]+)` \| ([^|]+) \|", summary, re.MULTILINE)
    return {tools.normalize(name): access.strip() for name, access in rows}


def test_read_and_write_tools_follow_the_access_column_of_the_reference():
    access = documented_access()
    assert sorted(access) == ALL
    assert tools.WRITE_TOOLS == {name for name, value in access.items() if value.startswith("write")}
    read_of_git_and_memory = [
        name for name, value in access.items() if value == "read" and name.split("__")[0] in ("git", "memory")
    ]
    assert tools.READ_TOOLS == ("runtime", *read_of_git_and_memory)


@pytest.mark.parametrize("tool_set", sorted(STEP_OWN_TOOLS))
def test_each_step_exposes_the_read_tools_and_only_its_own_tools(tool_set):
    exposed = names(tools.tool_definitions(servers(), mode="default", tool_set=tool_set))
    assert exposed == sorted([*STEP_READ_TOOLS, *STEP_OWN_TOOLS[tool_set]])


@pytest.mark.parametrize(
    ("tool_set", "writes"),
    [
        ("analyze", {"git__analyze_changes", "memory__add_risk", "memory__save_impact", "memory__sync_requirements"}),
        ("select", {"memory__save_suite", "test_runner__run_tests"}),
        ("design", {"memory__design_test_case", "memory__retire_test_case", "memory__update_test_case"}),
        ("implement", {"memory__retire_test_case", "memory__update_test_case", "test_runner__write_test"}),
        ("triage", {"memory__link_defect", "memory__register_defect", "memory__save_triage"}),
        ("report", {"reports__evaluate", "reports__prepare_report", "reports__render_report"}),
    ],
)  # fmt: skip
def test_the_exact_write_tools_of_each_step(tool_set, writes):
    exposed = set(names(tools.tool_definitions(servers(), mode="default", tool_set=tool_set)))
    # runtime__set_versions is a write tool of runtime, whose tools are read tools of every step
    assert exposed & tools.WRITE_TOOLS == writes | {"runtime__set_versions"}


def test_triage_cannot_create_an_analysis_or_sync_the_requirements():
    exposed = names(tools.tool_definitions(servers(), mode="default", tool_set="triage"))
    assert "git__analyze_changes" not in exposed and "memory__sync_requirements" not in exposed


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
