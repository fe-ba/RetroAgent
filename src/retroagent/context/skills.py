"""Skills: locations and precedence, format, the index, and loading one skill (spec/context-loading.md, Skills).

The caller passes the locations it may read: the bundled one always, user and project ones only once approved
(ADR-0021). Nothing here reads a location it was not given.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

import yaml

BUNDLED, USER, PROJECT = "bundled", "user", "project"
LEVELS = (BUNDLED, USER, PROJECT)
NAME = re.compile(r"^[a-z0-9-]+$")
MAX_DESCRIPTION = 300
FRONTMATTER = "---"


@dataclass(frozen=True)
class Location:
    level: str  # one of LEVELS
    directory: Traversable | Path  # holds <name>/SKILL.md


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    level: str
    body: str  # SKILL.md without its frontmatter


@dataclass(frozen=True)
class SkillProblem:
    """A skill that was skipped, as ``/skills`` reports it."""

    level: str
    folder: str
    reason: str


@dataclass(frozen=True)
class Skills:
    available: Mapping[str, Skill]  # by name, sorted by name
    problems: tuple[SkillProblem, ...]


class SkillFormatError(Exception):
    pass


class UnknownSkill(Exception):
    """``runtime.load_skill`` was asked for a skill that is not available: the runtime answers ``not_found``."""

    def __init__(self, name: str, available: Sequence[str]):
        names = ", ".join(available) or "none"
        super().__init__(f"There is no skill named {name!r}. Available skills: {names}.")
        self.name = name


def bundled_location() -> Location:
    return Location(BUNDLED, files("retroagent.resources") / "skills")


def parse_skill(text: str, folder: str, level: str) -> Skill:
    """A skill from the content of its ``SKILL.md``. Raises ``SkillFormatError`` with the reason."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER:
        raise SkillFormatError("SKILL.md does not start with a frontmatter (---)")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == FRONTMATTER)
    except StopIteration:
        raise SkillFormatError("the frontmatter is not closed (---)") from None
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as error:
        problem = str(error).splitlines()[0]
        raise SkillFormatError(f"the frontmatter is not valid YAML: {problem}") from None
    if not isinstance(data, dict):
        raise SkillFormatError("the frontmatter is not a mapping of keys and values")

    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise SkillFormatError("name is required")
    if not NAME.match(name):
        raise SkillFormatError(f"name {name!r} may only use lowercase letters, digits and hyphens")
    if name != folder:
        raise SkillFormatError(f"name {name!r} does not equal the folder name {folder!r}")
    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise SkillFormatError("description is required")
    description = " ".join(description.split())
    if len(description) > MAX_DESCRIPTION:
        raise SkillFormatError(f"description has {len(description)} characters; the limit is {MAX_DESCRIPTION}")
    body = "\n".join(lines[end + 1 :]).strip()
    return Skill(name=name, description=description, level=level, body=body)


def discover(locations: Sequence[Location]) -> Skills:
    """Every available skill, with the precedence of the levels: a user skill replaces a bundled one with the same
    name; a project skill never replaces one and is skipped with a warning."""
    available: dict[str, Skill] = {}
    problems: list[SkillProblem] = []
    for location in sorted(locations, key=lambda loc: LEVELS.index(loc.level)):
        if not location.directory.is_dir():
            continue
        for folder in sorted(location.directory.iterdir(), key=lambda entry: entry.name):
            if not folder.is_dir():
                continue
            skill_file = folder / "SKILL.md"
            if not skill_file.is_file():
                problems.append(SkillProblem(location.level, folder.name, "the folder has no SKILL.md"))
                continue
            try:
                skill = parse_skill(skill_file.read_text(encoding="utf-8"), folder.name, location.level)
            except SkillFormatError as error:
                problems.append(SkillProblem(location.level, folder.name, str(error)))
                continue
            existing = available.get(skill.name)
            if existing is not None and not (skill.level == USER and existing.level == BUNDLED):
                reason = f"skipped: a {existing.level} skill has the same name and cannot be replaced"
                problems.append(SkillProblem(location.level, folder.name, reason))
                continue
            available[skill.name] = skill
    return Skills(available=dict(sorted(available.items())), problems=tuple(problems))


def skills_index(skills: Skills) -> str:
    """One line per available skill, ``- <name>: <description>``, sorted by name."""
    return "\n".join(f"- {s.name}: {s.description}" for s in skills.available.values())


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    content: str  # the result of runtime.load_skill
    unloaded: str | None  # the skill whose body the runtime replaces with unloaded_note(), if any


def load_skill(skills: Skills, name: str, loaded: str | None) -> LoadedSkill:
    """The result of ``runtime.load_skill``. ``loaded`` is the skill whose body is in the conversation, if any.

    One skill is loaded at a time: loading another one unloads the previous one. Loading the skill that is already
    loaded returns a short note instead of the body again.
    """
    skill = skills.available.get(name)
    if skill is None:
        raise UnknownSkill(name, list(skills.available))
    if name == loaded:
        return LoadedSkill(name, already_loaded_note(name), None)
    return LoadedSkill(name, skill.body, loaded)


def already_loaded_note(name: str) -> str:
    return f"Skill {name} is already loaded above."


def unloaded_note(name: str) -> str:
    return f"[Skill {name} unloaded; load it again if needed.]"
