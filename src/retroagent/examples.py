"""Bundled example projects: list them and create one in a directory (FR-33).

Resources are read through the package (ADR-0025). Every materialization of an example produces the
same commits: author, dates and messages come from its manifest (example.toml), and file content is
committed without line-ending conversion.
"""

import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path


class ExampleError(Exception):
    """Base class for errors the user can fix."""


class UnknownExample(ExampleError):
    pass


class TargetNotEmpty(ExampleError):
    pass


class GitFailed(Exception):
    """A git command of the materialization failed."""


@dataclass(frozen=True)
class Example:
    name: str
    description: str
    tags: tuple[str, ...]


def _examples_root():
    return files("retroagent.resources") / "examples"


def _load_manifest(name: str) -> dict:
    manifest = _examples_root() / name / "example.toml"
    if not manifest.is_file():
        raise UnknownExample(f"unknown example: {name}")
    return tomllib.loads(manifest.read_text(encoding="utf-8"))


def list_examples() -> list[Example]:
    examples = []
    for entry in sorted(_examples_root().iterdir(), key=lambda item: item.name):
        if (entry / "example.toml").is_file():
            manifest = _load_manifest(entry.name)
            tags = tuple(version["tag"] for version in manifest["versions"])
            examples.append(Example(manifest["name"], manifest["description"], tags))
    return examples


def _git(target: Path, *args: str, env: dict | None = None) -> None:
    command = [
        "git",
        "-c", "core.autocrlf=false",
        "-c", "core.safecrlf=false",
        "-c", "commit.gpgsign=false",
        "-c", "tag.gpgsign=false",
        "-c", "core.hooksPath=",
        "-c", "advice.detachedHead=false",
        *args,
    ]  # fmt: skip
    try:
        subprocess.run(command, cwd=target, check=True, env=env, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise GitFailed("git is not installed or not on PATH") from error
    except subprocess.CalledProcessError as error:
        raise GitFailed(f"git {args[0]} failed: {error.stderr.strip()}") from error


def _clear_working_copy(target: Path) -> None:
    for entry in target.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def materialize(name: str, target: Path) -> tuple[str, ...]:
    """Create example `name` in `target` with its git history and tags. Return the tags in order."""
    manifest = _load_manifest(name)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise TargetNotEmpty(f"{target} must not exist or must be empty")
    target.mkdir(parents=True, exist_ok=True)

    _git(target, "init", "--quiet", f"--initial-branch={manifest['branch']}")
    # Keep line endings exactly as stored, whatever the configuration of the machine.
    (target / ".git" / "info" / "attributes").write_text("* -text\n", encoding="utf-8")

    for version in manifest["versions"]:
        _clear_working_copy(target)
        with as_file(_examples_root() / name / "versions" / version["dir"]) as snapshot:
            shutil.copytree(snapshot, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        env = dict(os.environ)
        env.update(
            GIT_AUTHOR_NAME=manifest["author_name"],
            GIT_AUTHOR_EMAIL=manifest["author_email"],
            GIT_AUTHOR_DATE=version["date"],
            GIT_COMMITTER_NAME=manifest["author_name"],
            GIT_COMMITTER_EMAIL=manifest["author_email"],
            GIT_COMMITTER_DATE=version["date"],
        )
        _git(target, "add", "--all")
        _git(target, "commit", "--quiet", "--message", version["message"], env=env)
        _git(target, "tag", version["tag"])

    return tuple(version["tag"] for version in manifest["versions"])
