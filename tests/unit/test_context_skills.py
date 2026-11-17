"""Skills: bundled skills, precedence of the levels, format, the index, and loading one skill."""

import pytest

from retroagent.context import skills
from retroagent.context.skills import BUNDLED, PROJECT, USER, Location

BUNDLED_NAMES = ["failure-triage", "impact-analysis", "test-design", "test-reporting", "test-selection"]


def write_skill(root, folder, description="Does a task.", name=None, body="# Task\n\nSteps."):
    directory = root / folder
    directory.mkdir(parents=True)
    text = f"---\nname: {name or folder}\ndescription: {description}\n---\n\n{body}\n"
    (directory / "SKILL.md").write_text(text, encoding="utf-8")
    return directory


def write_raw(root, folder, text):
    directory = root / folder
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(text, encoding="utf-8")


@pytest.fixture
def levels(tmp_path):
    roots = {level: tmp_path / level for level in (BUNDLED, USER, PROJECT)}
    for root in roots.values():
        root.mkdir()
    return roots


def discover(roots, *levels):
    return skills.discover([Location(level, roots[level]) for level in levels])


def test_every_bundled_skill_is_valid():
    found = skills.discover([skills.bundled_location()])
    assert found.problems == ()
    assert list(found.available) == BUNDLED_NAMES
    for skill in found.available.values():
        assert skill.level == BUNDLED
        assert 0 < len(skill.description) <= 300
        assert skill.body.startswith("# ")
        assert "---" not in skill.body.splitlines()[0]


def test_a_user_skill_replaces_a_bundled_skill(levels):
    write_skill(levels[BUNDLED], "triage", "Bundled triage.")
    write_skill(levels[USER], "triage", "User triage.")
    found = discover(levels, BUNDLED, USER)
    assert found.available["triage"].level == USER
    assert found.available["triage"].description == "User triage."
    assert found.problems == ()


def test_a_project_skill_cannot_replace_a_bundled_or_user_skill(levels):
    write_skill(levels[BUNDLED], "triage", "Bundled triage.")
    write_skill(levels[USER], "design", "User design.")
    write_skill(levels[PROJECT], "triage", "Project triage.")
    write_skill(levels[PROJECT], "design", "Project design.")
    write_skill(levels[PROJECT], "deploy-check", "Project only.")
    # The order of the locations given does not change the precedence.
    found = skills.discover([Location(level, levels[level]) for level in (PROJECT, USER, BUNDLED)])
    assert found.available["triage"].level == BUNDLED
    assert found.available["design"].level == USER
    assert found.available["deploy-check"].level == PROJECT
    assert {(p.level, p.folder) for p in found.problems} == {(PROJECT, "triage"), (PROJECT, "design")}
    assert all("skipped" in p.reason for p in found.problems)


def test_only_the_given_locations_are_read(levels):
    write_skill(levels[BUNDLED], "triage")
    write_skill(levels[PROJECT], "deploy-check")
    assert list(discover(levels, BUNDLED).available) == ["triage"]


def test_a_missing_location_has_no_skills(tmp_path):
    assert skills.discover([Location(USER, tmp_path / "absent")]).available == {}


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("# No frontmatter\n", "does not start with a frontmatter"),
        ("---\nname: broken\ndescription: x\n", "not closed"),
        ("---\nname: broken\ndescription: Prepare it: then render.\n---\nBody\n", "not valid YAML"),
        ("---\n- a list\n---\nBody\n", "not a mapping"),
        ("---\ndescription: x\n---\nBody\n", "name is required"),
        ("---\nname: Broken\ndescription: x\n---\nBody\n", "lowercase letters, digits and hyphens"),
        ("---\nname: other\ndescription: x\n---\nBody\n", "does not equal the folder name 'broken'"),
        ("---\nname: broken\n---\nBody\n", "description is required"),
        ("---\nname: broken\ndescription: " + "x" * 301 + "\n---\nBody\n", "301 characters; the limit is 300"),
    ],
)
def test_a_malformed_skill_is_skipped_with_the_reason(levels, text, reason):
    write_skill(levels[BUNDLED], "good")
    write_raw(levels[BUNDLED], "broken", text)
    found = discover(levels, BUNDLED)
    assert list(found.available) == ["good"]
    [problem] = found.problems
    assert (problem.level, problem.folder) == (BUNDLED, "broken")
    assert reason in problem.reason


def test_a_folder_without_skill_md_is_reported(levels):
    (levels[USER] / "empty").mkdir()
    [problem] = discover(levels, USER).problems
    assert problem.reason == "the folder has no SKILL.md"


def test_a_malformed_user_skill_leaves_the_bundled_one(levels):
    write_skill(levels[BUNDLED], "triage", "Bundled triage.")
    write_raw(levels[USER], "triage", "no frontmatter")
    found = discover(levels, BUNDLED, USER)
    assert found.available["triage"].level == BUNDLED
    assert [p.level for p in found.problems] == [USER]


def test_yaml_values_unknown_keys_and_folded_descriptions(levels):
    write_raw(
        levels[USER],
        "report",
        "---\nname: report\nversion: 2\ndescription: >\n  Prepare it: then\n  render it.\n---\n\n\n# Report\n",
    )
    skill = discover(levels, USER).available["report"]
    assert skill.description == "Prepare it: then render it."
    assert skill.body == "# Report"


def test_the_body_excludes_the_frontmatter(levels):
    write_skill(levels[BUNDLED], "triage", body="# Triage\n\n1. Read.\n2. Record.")
    assert discover(levels, BUNDLED).available["triage"].body == "# Triage\n\n1. Read.\n2. Record."


def test_the_index_lists_every_skill_sorted_by_name(levels):
    write_skill(levels[BUNDLED], "zeta", "Last one.")
    write_skill(levels[USER], "alpha", "First one.")
    assert skills.skills_index(discover(levels, BUNDLED, USER)) == "- alpha: First one.\n- zeta: Last one."


def test_loading_a_skill_returns_its_body():
    found = skills.discover([skills.bundled_location()])
    loaded = skills.load_skill(found, "test-design", loaded=None)
    assert loaded.content == found.available["test-design"].body
    assert loaded.unloaded is None


def test_loading_another_skill_unloads_the_previous_one():
    found = skills.discover([skills.bundled_location()])
    loaded = skills.load_skill(found, "failure-triage", loaded="test-design")
    assert loaded.content == found.available["failure-triage"].body
    assert loaded.unloaded == "test-design"
    assert skills.unloaded_note("test-design") == "[Skill test-design unloaded; load it again if needed.]"


def test_loading_the_loaded_skill_returns_a_short_note():
    found = skills.discover([skills.bundled_location()])
    loaded = skills.load_skill(found, "test-design", loaded="test-design")
    assert loaded.content == "Skill test-design is already loaded above."
    assert loaded.unloaded is None


def test_an_unknown_skill_names_the_available_ones():
    found = skills.discover([skills.bundled_location()])
    with pytest.raises(skills.UnknownSkill) as error:
        skills.load_skill(found, "deploy", loaded=None)
    assert error.value.name == "deploy"
    assert str(error.value) == "There is no skill named 'deploy'. Available skills: " + ", ".join(BUNDLED_NAMES) + "."
