"""Start and End of a session on a small repository (runtime.md, Session lifecycle). No test is executed here."""

import subprocess

import pytest

from retroagent.memory import connect, sessions
from retroagent.runtime import lock, session
from retroagent.runtime.session import MODEL_PLACEHOLDER, Options, SessionError, Version


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
    for number in (1, 2):
        (path / "version.txt").write_text(f"{number}\n")
        git(path, "add", ".")
        git(path, "commit", "--quiet", "-m", str(number))
        git(path, "tag", f"v{number}")
    return path


def record(repo, session_id):
    conn = connect(repo)
    try:
        return dict(sessions.get_session(conn, session_id))
    finally:
        conn.close()


def test_start_creates_the_session_record_and_end_closes_it(repo):
    with session.start(Options(project=repo, interactive=False)) as started:
        assert started.project_dir == repo.resolve()
        assert (repo / ".retro" / "retro.lock").read_text().strip().isdigit()
        with pytest.raises(lock.LockHeld):
            lock.acquire(repo / ".retro" / "retro.lock")
    row = record(repo, started.id)
    assert (row["model"], row["interactive"], row["result_char_limit"]) == (MODEL_PLACEHOLDER, 0, 20000)
    assert row["ended_at"] is not None
    lock.acquire(repo / ".retro" / "retro.lock").release()  # released at End


def test_versions_come_from_the_flags_then_from_the_configuration(repo):
    (repo / ".retro").mkdir()
    (repo / ".retro" / "config.yaml").write_text("versions:\n  base: v1\n  candidate: v2\n")
    commits = {tag: git(repo, "rev-parse", tag) for tag in ("v1", "v2", "main")}

    with session.start(Options(project=repo, candidate="main")) as started:
        assert started.versions() == {
            "base": Version("v1", commits["v1"]),
            "candidate": Version("main", commits["main"]),
        }
    row = record(repo, started.id)
    assert (row["base_ref"], row["base_commit"]) == ("v1", commits["v1"])
    assert (row["candidate_ref"], row["candidate_commit"]) == ("main", commits["main"])


def test_a_short_commit_hash_is_a_ref(repo):
    short = git(repo, "rev-parse", "--short", "v1")
    with session.start(Options(project=repo, base=short)) as started:
        assert started.versions()["base"] == Version(short, git(repo, "rev-parse", "v1"))


def test_versions_may_stay_unset(repo):
    with session.start(Options(project=repo)) as started:
        assert started.versions() == {"base": None, "candidate": None}


def test_a_ref_that_does_not_resolve_ends_the_session_without_writing_versions(repo):
    with pytest.raises(SessionError, match="'v9' is not a tag, branch or commit"):
        session.start(Options(project=repo, base="v1", candidate="v9"))
    row = record(repo, 1)
    assert (row["base_ref"], row["base_commit"], row["candidate_ref"]) == (None, None, None)
    assert row["ended_at"] is not None
    lock.acquire(repo / ".retro" / "retro.lock").release()


@pytest.mark.parametrize("ref", ["", "--all", "v1^{tree}"])
def test_odd_refs_do_not_resolve(repo, ref):
    with pytest.raises(session.UnknownRef):
        session.resolve_commit(repo, ref)


def test_the_data_layer_writes_a_ref_only_with_its_commit(repo):
    with session.start(Options(project=repo)) as started:
        with pytest.raises(ValueError):
            sessions.set_versions(
                started.conn, started.id, base_ref="v1", base_commit=None, candidate_ref=None, candidate_commit=None
            )
