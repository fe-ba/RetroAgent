"""Worktrees outside the project, removed with their git metadata (ADR-0009, ADR-0024)."""

import subprocess

import pytest

from retroagent.config import worktrees_dir
from retroagent.servers.test_runner import worktree


def git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("RETRO_HOME", str(tmp_path / "home"))
    path = tmp_path / "project"
    path.mkdir()
    git(path, "init", "--quiet", "--initial-branch=main")
    (path / "version.txt").write_text("one\n")
    git(path, "add", ".")
    git(path, "commit", "--quiet", "-m", "one")
    git(path, "tag", "v1")
    (path / "version.txt").write_text("two\n")
    git(path, "commit", "--quiet", "-am", "two")
    return path


def worktree_count(repo):
    return git(repo, "worktree", "list", "--porcelain").count("worktree ")


def test_a_detached_worktree_of_a_commit_outside_the_project(repo):
    commit = git(repo, "rev-parse", "v1^{commit}")
    path = worktree.create(repo, commit)
    try:
        assert path.parent == worktrees_dir(repo)
        assert not path.is_relative_to(repo)
        assert (path / "version.txt").read_text() == "one\n"
        assert git(path, "rev-parse", "HEAD") == commit
        assert git(path, "branch", "--show-current") == ""  # detached
        assert worktree_count(repo) == 2
    finally:
        worktree.remove(repo, path)


def test_remove_deletes_the_files_and_the_git_metadata(repo):
    path = worktree.create(repo, git(repo, "rev-parse", "v1^{commit}"))
    (path / ".venv").mkdir()  # untracked files, as a setup leaves them
    (path / ".venv" / "marker").write_text("x")
    (path / "version.txt").write_text("changed\n")  # and a modified tracked file

    worktree.remove(repo, path)

    assert not path.exists()
    assert worktree_count(repo) == 1
    metadata = repo / ".git" / "worktrees"
    assert not metadata.exists() or not any(metadata.iterdir())
    assert list(worktrees_dir(repo).iterdir()) == []
    assert git(repo, "status", "--porcelain") == ""
    assert (repo / "version.txt").read_text() == "two\n"


def test_remove_works_when_the_files_are_already_gone(repo):
    path = worktree.create(repo, "HEAD")
    subprocess.run(["rm", "-rf", str(path)], check=True)
    worktree.remove(repo, path)
    assert worktree_count(repo) == 1


def test_checkout_removes_the_worktree_when_the_block_raises(repo):
    with pytest.raises(RuntimeError), worktree.checkout(repo, "HEAD") as path:
        assert path.exists()
        raise RuntimeError("the run failed")
    assert not path.exists()
    assert worktree_count(repo) == 1


def test_two_worktrees_of_the_same_commit_do_not_collide(repo):
    with worktree.checkout(repo, "HEAD") as first, worktree.checkout(repo, "HEAD") as second:
        assert first != second
        assert worktree_count(repo) == 3
    assert worktree_count(repo) == 1


def test_an_unknown_commit_is_an_error_and_leaves_nothing(repo):
    with pytest.raises(worktree.WorktreeError, match="no-such-ref"):
        worktree.create(repo, "no-such-ref")
    assert list(worktrees_dir(repo).iterdir()) == []
    assert worktree_count(repo) == 1
