"""``retro init`` and ``/init``: detect the type of the project and create ``RETRO.md``, ``.retro/config.yaml`` and
``.retro/.gitignore`` (project-contract.md, Detection by ``retro init``). An existing file is never overwritten.

``propose`` reads the working copy and git; ``write`` creates the files that do not exist. Nothing else of the
working copy is touched: no project memory, no lock.
"""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from retroagent.servers.memory import requirements as requirement_documents

RETRO_MD = "RETRO.md"
CONFIG = ".retro/config.yaml"
GITIGNORE = ".retro/.gitignore"
FILES = (RETRO_MD, CONFIG, GITIGNORE)

GITIGNORE_TEXT = "retro.db\nretro.db-*\nretro.lock\nruns/\n"


@dataclass(frozen=True)
class Framework:
    marker: str  # the file that was found
    test_command: str
    junit: str


@dataclass(frozen=True)
class Proposal:
    project_name: str
    framework: Framework | None
    requirements: tuple[str, ...]  # paths relative to the project
    base: str | None
    candidate: str | None


# The table of project-contract.md, in order: the first row whose marker is found wins.
PYTEST = ("pytest --junitxml={junit}", "{junit}")
VITEST = ("npx vitest run --reporter=junit --outputFile={junit}", "{junit}")
MAVEN = ("mvn -q test", "target/surefire-reports/*.xml")
GRADLE = ("./gradlew test", "build/test-results/test/*.xml")
GO = ("gotestsum --junitfile {junit}", "{junit}")


def detect_framework(project_dir: Path) -> Framework | None:
    def text(name: str) -> str | None:
        path = project_dir / name
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None

    pyproject = text("pyproject.toml")
    if pyproject is not None and "pytest" in pyproject:
        return Framework("pyproject.toml", *PYTEST)
    if (project_dir / "pytest.ini").is_file():
        return Framework("pytest.ini", *PYTEST)
    setup_cfg = text("setup.cfg")
    if setup_cfg is not None and "[tool:pytest]" in setup_cfg:
        return Framework("setup.cfg", *PYTEST)
    package = text("package.json")
    if package is not None and _uses_vitest(package):
        return Framework("package.json", *VITEST)
    if (project_dir / "pom.xml").is_file():
        return Framework("pom.xml", *MAVEN)
    for name in ("build.gradle", "build.gradle.kts"):
        if (project_dir / name).is_file():
            return Framework(name, *GRADLE)
    if (project_dir / "go.mod").is_file():
        return Framework("go.mod", *GO)
    return None


def _uses_vitest(package_json: str) -> bool:
    try:
        package = json.loads(package_json)
    except json.JSONDecodeError:
        return "vitest" in package_json
    if not isinstance(package, dict):
        return False
    sections = ("dependencies", "devDependencies", "scripts")
    return any(isinstance(package.get(s), dict) and "vitest" in json.dumps(package[s]) for s in sections)


_REQUIREMENTS_NAME = re.compile(r"^requirements.*\.md$", re.IGNORECASE)


def detect_requirements(project_dir: Path) -> tuple[str, ...]:
    """Markdown files named ``requirements*.md`` at the root or under ``docs/`` that contain requirement IDs."""
    candidates = [p for p in project_dir.glob("*.md") if p.is_file()]
    docs = project_dir / "docs"
    if docs.is_dir():
        candidates += [p for p in docs.rglob("*.md") if p.is_file()]
    found = []
    for path in sorted(set(candidates)):
        if not _REQUIREMENTS_NAME.match(path.name):
            continue
        relative = path.relative_to(project_dir).as_posix()
        parsed, problems = requirement_documents.parse(path.read_text(encoding="utf-8", errors="replace"), relative)
        if parsed or problems:  # a heading that starts with a requirement ID, valid or not
            found.append(relative)
    return tuple(found)


def detect_versions(project_dir: Path) -> tuple[str | None, str | None]:
    """The two most recent tags, by the committer date of the tagged commit (ties: version order of the name). The
    newest is the candidate. Fewer than two tags: none."""
    result = subprocess.run(
        ["git", "for-each-ref", "--format=%(*committerdate:unix) %(committerdate:unix) %(refname:short)", "refs/tags"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    tags = []
    for line in result.stdout.splitlines():
        parts = line.split(" ")
        if len(parts) == 3:  # an annotated tag has the date of its commit first; a lightweight tag only the second
            peeled, own, name = parts
            date = peeled or own
        elif len(parts) == 2:
            date, name = parts
        else:
            continue
        tags.append((int(date or 0), _version_key(name), name))
    tags.sort(reverse=True)
    if len(tags) < 2:
        return None, None
    return tags[1][2], tags[0][2]


def _version_key(name: str) -> tuple:
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in re.split(r"(\d+)", name) if part)


def propose(project_dir: Path) -> Proposal:
    base, candidate = detect_versions(project_dir)
    return Proposal(
        project_name=project_dir.name,
        framework=detect_framework(project_dir),
        requirements=detect_requirements(project_dir),
        base=base,
        candidate=candidate,
    )


def _yaml_string(value: str) -> str:
    return json.dumps(value)  # a JSON string is a valid YAML scalar


def config_text(proposal: Proposal) -> str:
    lines = [
        "# Proposed by retro init. Review every value: see docs/reference/configuration.md.",
        "",
        "project:",
        f"  name: {_yaml_string(proposal.project_name)}",
    ]
    if proposal.requirements:
        lines.append(f"  requirements: [{', '.join(_yaml_string(path) for path in proposal.requirements)}]")
    else:
        lines.append("  # requirements: [docs/requirements.md]   # no requirements*.md with requirement IDs was found")
    lines.append("")
    if proposal.base and proposal.candidate:
        lines += [
            "versions:",
            f"  base: {_yaml_string(proposal.base)}",
            f"  candidate: {_yaml_string(proposal.candidate)}",
        ]
    else:
        lines += ["# versions:   # fewer than two tags were found", "#   base: <ref>", "#   candidate: <ref>"]
    lines.append("")
    if proposal.framework:
        lines += [
            f"# Detected from {proposal.framework.marker}. Add tests.setup if the tests need dependencies installed.",
            "tests:",
            f"  command: {_yaml_string(proposal.framework.test_command)}",
            f"  junit: {_yaml_string(proposal.framework.junit)}",
        ]
    else:
        lines += [
            "# No test framework was detected. Set the command that runs the tests and writes JUnit XML:",
            "# tests:",
            "#   command: <command> --junitxml={junit}",
        ]
    return "\n".join(lines) + "\n"


def retro_md_text(proposal: Proposal) -> str:
    running = (
        f"- Tests: `{proposal.framework.test_command}` (detected from `{proposal.framework.marker}`)."
        if proposal.framework
        else "To be written: how to install, start and test the project."
    )
    return "\n".join(
        [
            f"# {proposal.project_name}",
            "",
            "## Overview",
            "",
            "To be written: what the project does and who uses it.",
            "",
            "## Modules",
            "",
            "To be written: main components and where they live.",
            "",
            "## Running",
            "",
            running,
            "",
            "## Test conventions",
            "",
            "To be written: frameworks, naming, fixtures, test data.",
            "",
            "## Known issues",
            "",
            "To be written: known flaky tests, unstable areas, accepted limitations.",
            "",
        ]
    )


def contents(proposal: Proposal) -> dict[str, str]:
    return {RETRO_MD: retro_md_text(proposal), CONFIG: config_text(proposal), GITIGNORE: GITIGNORE_TEXT}


def write(project_dir: Path, proposal: Proposal) -> tuple[list[str], list[str]]:
    """Create the files that do not exist. Returns the files created and the files kept."""
    created, kept = [], []
    for name, text in contents(proposal).items():
        path = project_dir / name
        if path.exists():
            kept.append(name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:  # never overwrite, even if the file appeared meanwhile
            handle.write(text)
        created.append(name)
    return created, kept


def describe(proposal: Proposal) -> list[str]:
    """What was detected, one line each, for the confirmation."""
    framework = proposal.framework
    return [
        "Tests: "
        + (
            f"{framework.test_command} (from {framework.marker}), JUnit XML at {framework.junit}"
            if framework
            else "no test framework detected"
        ),
        "Requirements: " + (", ".join(proposal.requirements) or "none found"),
        "Versions: "
        + (f"base {proposal.base}, candidate {proposal.candidate}" if proposal.base else "fewer than two tags"),
    ]
