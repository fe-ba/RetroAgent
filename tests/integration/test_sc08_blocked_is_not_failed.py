"""SC-08: blocked is not failed. A full run discovers the tests of v1.1; then a failing setup blocks every one of
them; the evaluation is refused and stores nothing."""

import pytest
import yaml
from fixtures.example_project import example_project, start

from retroagent.cli.main import main
from retroagent.memory import execution
from retroagent.metrics import EvaluationError, evaluate
from retroagent.runtime import commands

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def shop(tmp_path_factory, pip_cache):
    with example_project(tmp_path_factory, pip_cache) as path:
        with start(path, trust_commands=True, mode="auto") as session:
            discovery = commands.run(session, "all")
        config_path = path / ".retro" / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        config["tests"]["setup"] = "exit 3"
        config_path.write_text(yaml.safe_dump(config))
        exit_code = main(["-C", str(path), "--trust-commands", "--mode", "auto", "-p", "/run all"])
        yield path, discovery, exit_code


def test_the_full_run_discovers_26_tests(shop):
    _, discovery, _ = shop
    [run] = discovery.runs
    assert (run.run_id, run.version_role, run.status, run.counts["executed"]) == (
        "RUN-0001",
        "candidate",
        "completed",
        26,
    )


def test_a_failing_setup_gives_a_run_with_status_error_and_exit_code_1(shop):
    path, _, exit_code = shop
    assert exit_code == 1
    with start(path) as session:
        run = execution.get_run(session.conn, "RUN-0002")
        assert (run["status"], run["error"], run["junit_path"], run["exit_code"]) == (
            "error",
            "setup: exit code 3",
            None,
            None,
        )
        known = [r["id"] for r in session.conn.execute("SELECT id FROM test_case ORDER BY id")]
        executions = execution.list_executions(session.conn, "RUN-0002")
    assert len(known) == 26
    assert sorted(e["test_case_id"] for e in executions) == known
    assert {(e["status"], e["result"], e["reason"]) for e in executions} == {("blocked", None, "setup_failed")}


def test_status_shows_them_as_blocked_not_failed(shop):
    path, _, _ = shop
    with start(path) as session:
        latest = commands.status(session).latest_run
    assert (latest.run_id, latest.status) == ("RUN-0002", "error")
    assert latest.counts == {"executed": 0, "blocked": 26, "skipped": 0, "passed": 0, "failed": 0, "error": 0}


def test_the_evaluation_is_refused_and_stores_nothing(shop):
    path, _, _ = shop
    with start(path) as session:
        candidate = session.versions()["candidate"].commit
        for run_id in (None, "RUN-0001", "RUN-0002"):
            with pytest.raises(EvaluationError):
                evaluate(session.conn, candidate, run_id=run_id)
        assert session.conn.execute("SELECT COUNT(*) FROM evaluation").fetchone()[0] == 0
