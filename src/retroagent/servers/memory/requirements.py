"""Parsing of requirement documents (project-contract.md, Requirements), as pure functions.

A requirement is a Markdown heading that starts with its ID, ``## REQ-004: Discount coupons``, followed by its
description and optional fields written as bullets: ``Priority``, ``Since``, ``Changed`` (repeatable,
``<version> - <description>``) and ``Removed``. Other bullets are part of the description. A requirement that
cannot be parsed is reported as a ``Problem`` and not returned; the others of the same document are.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

PRIORITIES = ("high", "medium", "low")

_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
_REQUIREMENT_HEADING = re.compile(r"^(REQ-[^\s:]*)(.*)$")
_ID = re.compile(r"^REQ-\d{3,}$")
_FIELD = re.compile(r"^\s*[-*+]\s+(priority|since|changed|removed)\s*:\s*(.*?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Change:
    version: str
    description: str


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    description: str
    source_file: str
    priority: str | None = None
    since: str | None = None
    removed: str | None = None
    changes: tuple[Change, ...] = ()


@dataclass(frozen=True)
class Problem:
    file: str
    requirement: str | None  # None when the whole file could not be read
    reason: str


class _Invalid(Exception):
    pass


def parse_documents(documents: Iterable[tuple[str, str]]) -> tuple[list[Requirement], list[Problem]]:
    """Parse ``(source file, text)`` pairs in order. An ID defined twice is reported; the first one is kept."""
    requirements: dict[str, Requirement] = {}
    problems: list[Problem] = []
    for source_file, text in documents:
        found, found_problems = parse(text, source_file)
        problems.extend(found_problems)
        for requirement in found:
            first = requirements.get(requirement.id)
            if first is not None:
                problems.append(
                    Problem(source_file, requirement.id, f"{requirement.id} is already defined in {first.source_file}")
                )
            else:
                requirements[requirement.id] = requirement
    return list(requirements.values()), problems


def parse(text: str, source_file: str) -> tuple[list[Requirement], list[Problem]]:
    requirements, problems = [], []
    for heading, body in _sections(text):
        match = _REQUIREMENT_HEADING.match(heading)
        if match is None:
            continue
        identifier = match.group(1)
        try:
            requirements.append(_requirement(identifier, match.group(2), body, source_file))
        except _Invalid as error:
            problems.append(Problem(source_file, identifier, str(error)))
    return requirements, problems


def _sections(text: str) -> list[tuple[str, list[str]]]:
    """Each heading with the lines up to the next heading."""
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            sections.append((heading.group(1), []))
        elif sections:
            sections[-1][1].append(line)
    return sections


def _requirement(identifier: str, rest: str, body: list[str], source_file: str) -> Requirement:
    if not _ID.match(identifier):
        raise _Invalid(f"{identifier!r} is not an ID of the form REQ-NNN")
    title = rest.strip().lstrip(":-–—").strip()
    if not title:
        raise _Invalid(f"{identifier} has no title after its ID")
    fields: dict[str, str] = {}
    changes: list[Change] = []
    description: list[str] = []
    for line in body:
        field = _FIELD.match(line)
        if field is None:
            description.append(line.rstrip())
            continue
        name, value = field.group(1).capitalize(), field.group(2)
        if name == "Changed":
            version, separator, what = value.partition(" - ")
            if not separator or not version.strip() or not what.strip() or " " in version.strip():
                raise _Invalid(f"{identifier}: Changed must be '<version> - <description>', not {value!r}")
            changes.append(Change(version.strip(), what.strip()))
            continue
        if name in fields:
            raise _Invalid(f"{identifier}: {name} is given more than once")
        if not value or " " in value:
            raise _Invalid(f"{identifier}: {name} must be one value, not {value!r}")
        if name == "Priority":
            value = value.lower()
            if value not in PRIORITIES:
                raise _Invalid(f"{identifier}: Priority must be high, medium or low, not {field.group(2)!r}")
        fields[name] = value
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(description)).strip()
    if not text:
        raise _Invalid(f"{identifier} has no description")
    return Requirement(
        id=identifier,
        title=title,
        description=text,
        source_file=source_file,
        priority=fields.get("Priority"),
        since=fields.get("Since"),
        removed=fields.get("Removed"),
        changes=tuple(changes),
    )
