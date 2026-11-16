"""Detached worktrees of the versions under test, outside the project (ADR-0009, ADR-0024).

They live under ``~/.retro/worktrees/<project-id>/`` and are removed after each run, together with the
metadata git keeps in ``.git/worktrees/``.
"""

import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from retroagent.config import worktrees_dir


class WorktreeError(Exception):
    """git could not create the worktree."""


def create(project_dir: str | Path, commit: str) -> Path:
    root = worktrees_dir(project_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=f"{commit[:12]}-", dir=root))
    result = _git(project_dir, "worktree", "add", "--detach", str(path), commit)
    if result.returncode != 0:
        shutil.rmtree(path, ignore_errors=True)
        raise WorktreeError(f"git worktree add failed for {commit}: {result.stderr.strip()}")
    return path


def remove(project_dir: str | Path, path: str | Path) -> None:
    """Remove the worktree, its files and its metadata. Safe to call when part of it is already gone."""
    _git(project_dir, "worktree", "remove", "--force", "--force", str(path))
    shutil.rmtree(path, ignore_errors=True)
    _git(project_dir, "worktree", "prune")


def remove_leftovers(project_dir: str | Path) -> list[Path]:
    """Remove every worktree of this project under its folder, and git metadata whose directory is gone.

    Used when a session starts, after a session that ended before its run did, and when a session ends.
    """
    root = worktrees_dir(project_dir)
    removed = sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []
    for path in removed:
        remove(project_dir, path)
    _git(project_dir, "worktree", "prune")
    return removed


@contextmanager
def checkout(project_dir: str | Path, commit: str) -> Iterator[Path]:
    path = create(project_dir, commit)
    try:
        yield path
    finally:
        remove(project_dir, path)


def _git(project_dir: str | Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=project_dir, capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False
    )
