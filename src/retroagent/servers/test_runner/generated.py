"""Generated tests: where ``test_runner.write_test`` writes them, the form of their names, and, in a run, their copy
into the worktree, their binding to a JUnit entry and ``{names}``.

The implementation of a generated test is ``<file>::<test name>``, with ``file`` relative to ``.retro/tests/``
(mcp-tools.md, ``test_runner.write_test``).
"""

import os
import posixpath
import re
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from retroagent.servers.test_runner.junit import Entry

ROOT = (".retro", "tests")


class GeneratedError(ValueError):
    """A file or a test name that ``test_runner.write_test`` refuses: ``invalid_argument``."""


def normalize_file(file: str) -> str:
    """The path of a generated test relative to ``.retro/tests/``, normalized. Raises ``GeneratedError`` when it
    is empty, absolute, or leaves ``.retro/tests/``."""
    if not file or not file.strip() or "\\" in file or "\0" in file:
        raise GeneratedError(f"file {file!r} is not a relative path inside .retro/tests/")
    if file.startswith("/") or PurePosixPath(file).is_absolute():
        raise GeneratedError(f"file {file!r} is absolute; give a path relative to .retro/tests/")
    normalized = posixpath.normpath(file)
    if normalized in (".", "..") or normalized.startswith("../"):
        raise GeneratedError(f"file {file!r} leaves .retro/tests/")
    return normalized


def target(project_dir: str | Path, file: str) -> Path:
    """The path where a generated test is written: ``.retro/tests/<file>``, with ``file`` normalized.

    Neither ``.retro``, ``.retro/tests`` nor any part of ``file`` may be a symbolic link, even one that points inside:
    a link could make the file of one generated test the file of another (INV-17). A part that exists must be a
    directory, and the file itself a regular file. Raises ``GeneratedError``.
    """
    relative = normalize_file(file)
    path = Path(project_dir)
    parts = [*ROOT, *PurePosixPath(relative).parts]
    for index, part in enumerate(parts):
        path = path / part
        if path.is_symlink():
            shown = "/".join(parts[: index + 1])
            raise GeneratedError(f"{shown} is a symbolic link; generated tests are written only inside .retro/tests/")
        last = index == len(parts) - 1
        if path.exists() and not (path.is_file() if last else path.is_dir()):
            raise GeneratedError(f"{'/'.join(parts[: index + 1])} is not a {'file' if last else 'directory'}")
    return path


# test_req_<NNN>_<description> (mcp-tools.md, ``test_runner.write_test``; project-contract.md, Traceability).
_REQUIREMENT_FORM = re.compile(r"test_req_(\d{3,})_.+")
_FORBIDDEN = ("::", "[")


def check_test_name(name: str, requirement_ids: Iterable[str]) -> None:
    """Refuse a test name that would break the identity of the test (``<file>::<name>`` and ``{names}``), or that
    does not follow ``test_req_<NNN>_<description>`` with the number of a traced requirement. Raises
    ``GeneratedError``."""
    if not name or any(character.isspace() for character in name) or any(part in name for part in _FORBIDDEN):
        raise GeneratedError(f"test name {name!r} must be a function name without whitespace, '::' or '['")
    numbers = [requirement_id.removeprefix("REQ-") for requirement_id in requirement_ids]
    if not numbers:
        return
    match = _REQUIREMENT_FORM.fullmatch(name)
    if match is None or match.group(1) not in numbers:
        forms = ", ".join(f"test_req_{number}_<description>" for number in numbers)
        raise GeneratedError(f"test name {name!r} must follow {forms}: the test case traces a requirement")


def write(path: Path, code: str) -> None:
    """Write ``code`` to ``path``: its directories are created, and the file is replaced in one step."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".write-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as output:
            output.write(code)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def module_name(generated_dir: str, file: str) -> str:
    """The module path of a generated test in the worktree, as pytest names a file it cannot load:
    ``tests/retro`` and ``cart/test_a.py`` give ``tests.retro.cart.test_a``."""
    return ".".join((PurePosixPath(generated_dir) / file).with_suffix("").parts)


def load_error_file(name: str, files: Iterable[str], generated_dir: str) -> str | None:
    """The generated file that a load-error entry named ``name`` belongs to: its module path is ``name``, or ends
    with ``.<name>`` when the rootdir of the framework is deeper than the worktree. None when no file, or more than
    one, matches."""
    matches = [
        file for file in files if (module := module_name(generated_dir, file)) == name or module.endswith("." + name)
    ]
    return matches[0] if len(matches) == 1 else None


def remove_generated(worktree: str | Path, generated_dir: str, file: str) -> None:
    """Remove a generated test from the worktree, for the rest of the run."""
    (Path(worktree) / generated_dir / file).unlink(missing_ok=True)


def bind(entries: Iterable[Entry], implementation: str) -> Entry | None:
    """The entry of a generated test (project-contract.md, Test identity).

    Its ``name`` equals the function name, and its ``classname`` ends with the name of its file (without the
    extension, at a ``.`` boundary) or it is the only entry of the run with that name. None when no entry, or
    more than one, qualifies.
    """
    file, _, name = implementation.rpartition("::")
    stem = PurePosixPath(file).stem
    named = [entry for entry in entries if entry.name == name]
    by_file = [entry for entry in named if entry.classname == stem or entry.classname.endswith("." + stem)]
    if len(by_file) == 1:
        return by_file[0]
    if len(named) == 1:
        return named[0]
    return None


def select_name(name: str) -> str:
    """The name of a test without its parameter suffix: ``test_total[2-3]`` gives ``test_total``."""
    base, bracket, _ = name.partition("[")
    return base if bracket and name.endswith("]") else name


def names(test_names: Iterable[str], separator: str) -> str:
    """The value of ``{names}``: each name without its parameter suffix, once, in order, joined."""
    return separator.join(dict.fromkeys(select_name(name) for name in test_names))


def copy_generated(project_dir: str | Path, worktree: str | Path, generated_dir: str, implementations: Iterable[str]):
    """Copy the files of the given generated tests from ``.retro/tests/`` to ``generated_dir`` in the worktree.

    Returns the files that do not exist in ``.retro/tests/``; their test cases will not be reported.
    """
    source_root = (Path(project_dir) / ".retro" / "tests").resolve()
    target_root = Path(worktree) / generated_dir
    missing = []
    for implementation in implementations:
        file = implementation.rpartition("::")[0]
        source = (source_root / file).resolve()
        if not source.is_relative_to(source_root):
            raise ValueError(f"{file} is not inside .retro/tests/")
        if not source.is_file():
            missing.append(file)
            continue
        target = target_root / file
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return missing
