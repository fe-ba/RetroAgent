"""Reads of the git repository of the target project, as plain functions.

Every function reads git objects of given commits, never the working copy, and none writes to the repository:
commands run with ``--no-optional-locks`` (no index refresh) and diffs without external diff or text conversion
drivers.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    """git failed for a reason other than a missing object."""


@dataclass(frozen=True)
class ChangedFile:
    path: str
    change: str  # added, modified, deleted or renamed
    lines_added: int
    lines_removed: int
    old_path: str | None = None

    def as_dict(self) -> dict:
        record = {
            "path": self.path,
            "change": self.change,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
        }
        if self.old_path is not None:
            record["old_path"] = self.old_path
        return record


def git(project_dir: str | Path, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "--no-optional-locks", *args],
        cwd=project_dir,
        capture_output=True,
        text=text,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def resolve(project_dir: str | Path, ref: str) -> str | None:
    """The full commit hash of a tag, a branch or a commit; None when it does not resolve."""
    if not ref or ref.startswith("-"):
        return None
    result = git(project_dir, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")
    return result.stdout.strip() if result.returncode == 0 else None


def ref_kind(project_dir: str | Path, ref: str) -> str:
    """``tag``, ``branch`` or ``commit``, for a ref that resolves (so it does not start with ``-``)."""
    full = git(project_dir, "rev-parse", "--symbolic-full-name", ref).stdout.strip()
    if full.startswith("refs/tags/"):
        return "tag"
    if full.startswith(("refs/heads/", "refs/remotes/")):
        return "branch"
    return "commit"


_CHANGES = {"A": "added", "M": "modified", "T": "modified", "D": "deleted", "R": "renamed"}


def change_set(project_dir: str | Path, base_commit: str, candidate_commit: str) -> list[ChangedFile]:
    """The files that differ between two commits, sorted by path. Binary files count 0 lines."""
    common = ("diff", "--no-ext-diff", "--no-textconv", "--find-renames", "-z", base_commit, candidate_commit)
    status = _checked(git(project_dir, *common, "--name-status"))
    numstat = _checked(git(project_dir, *common, "--numstat"))

    kinds: dict[str, tuple[str, str | None]] = {}
    fields = status.stdout.split("\0")
    index = 0
    while index < len(fields) - 1:
        code = fields[index]
        if code.startswith("R"):
            kinds[fields[index + 2]] = ("renamed", fields[index + 1])
            index += 3
        else:
            kinds[fields[index + 1]] = (_CHANGES.get(code[0], "modified"), None)
            index += 2

    counts: dict[str, tuple[int, int]] = {}
    fields = numstat.stdout.split("\0")
    index = 0
    while index < len(fields) - 1:
        added, removed, path = fields[index].split("\t", 2)
        if path == "":  # a rename: the old and the new path follow
            path = fields[index + 2]
            index += 3
        else:
            index += 1
        counts[path] = (int(added) if added != "-" else 0, int(removed) if removed != "-" else 0)

    files = []
    for path, (change, old_path) in kinds.items():
        added, removed = counts.get(path, (0, 0))
        files.append(ChangedFile(path, change, added, removed, old_path))
    return sorted(files, key=lambda f: f.path)


def diff(
    project_dir: str | Path, base_commit: str, candidate_commit: str, path: str, old_path: str | None = None
) -> str:
    """The unified diff of one file between two commits."""
    paths = [old_path, path] if old_path else [path]
    result = git(
        project_dir, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--find-renames",
        base_commit, candidate_commit, "--", *paths,
    )  # fmt: skip
    return _checked(result).stdout


def object_type(project_dir: str | Path, commit: str, path: str) -> str | None:
    """``blob``, ``tree`` or another git object type of ``path`` at ``commit``; None when it does not exist."""
    spec = f"{commit}:{path}" if path else f"{commit}^{{tree}}"
    result = git(project_dir, "cat-file", "-t", spec)
    return result.stdout.strip() if result.returncode == 0 else None


def show(project_dir: str | Path, commit: str, path: str) -> bytes:
    """The content of a file at a commit."""
    result = git(project_dir, "cat-file", "blob", f"{commit}:{path}", text=False)
    if result.returncode != 0:
        raise GitError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def list_dir(project_dir: str | Path, commit: str, path: str) -> list[str]:
    """The files and directories directly under ``path`` at a commit; directories end with ``/``."""
    tree = f"{commit}:{path}" if path else commit
    result = _checked(git(project_dir, "ls-tree", "-z", tree))
    entries = []
    for line in result.stdout.split("\0"):
        if line:
            meta, name = line.split("\t", 1)
            entries.append(name + "/" if meta.split()[1] == "tree" else name)
    return sorted(entries)


def files_at(project_dir: str | Path, commit: str) -> list[str]:
    """Every file of the tree of a commit."""
    result = _checked(git(project_dir, "ls-tree", "-r", "-z", "--name-only", commit))
    return [name for name in result.stdout.split("\0") if name]


def _checked(result: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    if result.returncode != 0:
        stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode(errors="replace")
        raise GitError(stderr.strip() or f"git exited with code {result.returncode}")
    return result
