"""Generated tests in a run: copy them into the worktree, bind them to their JUnit entry, and ``{names}``.

The implementation of a generated test is ``<file>::<test name>``, with ``file`` relative to ``.retro/tests/``
(mcp-tools.md, ``test_runner.write_test``).
"""

import shutil
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from retroagent.servers.test_runner.junit import Entry


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
