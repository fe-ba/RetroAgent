"""SC-05: run both versions, with refs given as tags and again as commit hashes; then /status and /history."""

import subprocess
from dataclasses import dataclass

import pytest
from fixtures.example_project import example_project, start
from rich.console import Console

from retroagent.cli import tables
from retroagent.cli.main import main
from retroagent.config import worktrees_dir
from retroagent.memory import connect, execution
from retroagent.runtime import commands

pytestmark = pytest.mark.network

# The commits of the fixture (acceptance-scenarios.md, Fixture), given as refs in the second session.
V10, V11 = "c7d45ad", "46a5ef0"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def render(*renderables) -> str:
    console = Console(record=True, width=220, color_system=None)
    for item in renderables:
        console.print(item)
    return console.export_text()


def cells(text: str, run_id: str) -> list[str]:
    line = next(line for line in text.splitlines() if f" {run_id} " in line)
    return [cell.strip() for cell in line.split("│")[1:-1]]


@dataclass
class Shop:
    path: object
    by_tags: commands.RunOutcome
    by_hashes: commands.RunOutcome
    status: commands.Status
    history: list
    commits: dict


@pytest.fixture(scope="module")
def shop(tmp_path_factory, pip_cache):
    with example_project(tmp_path_factory, pip_cache) as path:
        with start(path, trust_commands=True, mode="auto", base="v1.0", candidate="v1.1") as first:
            by_tags = commands.run(first, "all", "both")
        with start(path, trust_commands=True, mode="auto", base=V10, candidate=V11) as second:
            by_hashes = commands.run(second, "all", "both")
            status, history = commands.status(second), commands.history(second)
        commits = {tag: git(path, "rev-parse", f"{tag}^{{commit}}").strip() for tag in ("v1.0", "v1.1")}
        yield Shop(path, by_tags, by_hashes, status, history, commits)


def summary(row):
    """Run, role, ref, scope, status, executions, passed, failed."""
    total = row.counts["executed"] + row.counts["blocked"] + row.counts["skipped"]
    failed = row.counts["failed"] + row.counts["error"]
    return (row.run_id, row.version_role, row.ref, row.scope, row.status, total, row.counts["passed"], failed)


def test_refs_given_as_tags(shop):
    assert (shop.by_tags.error, shop.by_tags.not_run, shop.by_tags.interrupted) == (None, None, False)
    assert [summary(row) for row in shop.by_tags.runs] == [
        ("RUN-0001", "base", "v1.0", "all", "completed", 22, 20, 2),
        ("RUN-0002", "candidate", "v1.1", "all", "completed", 26, 22, 4),
    ]
    assert [row.commit for row in shop.by_tags.runs] == [shop.commits["v1.0"], shop.commits["v1.1"]]


def test_refs_given_as_commit_hashes(shop):
    assert [summary(row) for row in shop.by_hashes.runs] == [
        ("RUN-0003", "base", V10, "all", "completed", 22, 20, 2),
        ("RUN-0004", "candidate", V11, "all", "completed", 26, 22, 4),
    ]
    assert [row.commit for row in shop.by_hashes.runs] == [shop.commits["v1.0"], shop.commits["v1.1"]]


def test_each_run_records_its_evidence(shop):
    conn = connect(shop.path)
    try:
        for run_id in ("RUN-0001", "RUN-0002", "RUN-0003", "RUN-0004"):
            run = execution.get_run(conn, run_id)
            evidence = shop.path / run["evidence_dir"]
            assert run["commit"] in shop.commits.values()
            assert run["command"].endswith(f"--junitxml={evidence}/junit-1.xml")
            assert run["started_at"] < run["ended_at"]
            assert run["exit_code"] == 1  # pytest: some tests failed
            assert (shop.path / run["junit_path"]).is_file()
            assert "exit code" in (evidence / "run.log").read_text()
        calls = conn.execute("SELECT server, tool, outcome FROM tool_call ORDER BY id").fetchall()
        assert [tuple(call) for call in calls] == [("test_runner", "run_tests", "ok")] * 4
    finally:
        conn.close()


def test_status_shows_the_session_and_the_latest_run(shop):
    assert shop.status.base.ref == V10 and shop.status.base.commit == shop.commits["v1.0"]
    assert shop.status.candidate.ref == V11 and shop.status.candidate.commit == shop.commits["v1.1"]
    assert shop.status.test_cases == {"designed": 0, "implemented": 26}
    assert shop.status.current_suite_size is None
    assert summary(shop.status.latest_run) == ("RUN-0004", "candidate", V11, "all", "completed", 26, 22, 4)
    text = render(*tables.status_tables(shop.status))
    assert cells(text, "RUN-0004")[5:12] == ["completed", "26", "26", "22", "4", "0", "0"]
    assert next(line for line in text.splitlines() if "Model calls" in line).split()[-2] == "0"
    assert "0 input, 0 output" in text


def test_history_shows_the_counts_of_every_run(shop):
    assert [row.run_id for row in shop.history] == ["RUN-0004", "RUN-0003", "RUN-0002", "RUN-0001"]
    text = render(tables.history_table(shop.history))
    for run_id, counts in (
        ("RUN-0001", ["22", "22", "20", "2", "0", "0", "0"]),
        ("RUN-0002", ["26", "26", "22", "4", "0", "0", "0"]),
        ("RUN-0003", ["22", "22", "20", "2", "0", "0", "0"]),
        ("RUN-0004", ["26", "26", "22", "4", "0", "0", "0"]),
    ):
        assert cells(text, run_id)[6:13] == counts


def test_non_interactive_direct_commands(shop, capsys):
    assert main(["-C", str(shop.path), "-p", "/history 2"]) == 0
    out = capsys.readouterr().out
    assert "RUN-0004" in out and "RUN-0003" in out and "RUN-0002" not in out

    assert main(["-C", str(shop.path), "-p", "/run all"]) == 4  # the project commands are not approved
    assert "denied" in capsys.readouterr().err
    conn = connect(shop.path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM run").fetchone()[0] == 4
    finally:
        conn.close()


def test_the_working_copy_is_unchanged_and_no_worktree_is_left(shop):
    root = worktrees_dir(shop.path)
    assert not root.exists() or not any(root.iterdir())
    assert git(shop.path, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert not (shop.path / ".git" / "worktrees").exists() or not any((shop.path / ".git" / "worktrees").iterdir())
    changes = [line[3:] for line in git(shop.path, "status", "--porcelain", "--untracked-files=all").splitlines()]
    assert [path for path in changes if not path.startswith(".retro/")] == []
