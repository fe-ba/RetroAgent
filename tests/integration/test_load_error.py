"""A test file that pytest cannot load, with real runs on shop-api (project-contract.md, Generated tests).

Two generated tests are written with ``write_test``: the oracle's, which passes, and one that imports a name that
does not exist. In a full run, the project tests and the good generated test keep their real results and the broken
one has result ``error`` with the ImportError, in one attempt. A selected run of only the broken one completes. A test
file of the project that cannot be loaded is named in the ``error`` of the run.
"""

import subprocess
from types import SimpleNamespace

import pytest
from fixtures.agent_session import GENERATED_FILE, GENERATED_NAME, generated_code
from fixtures.example_project import project_copy, start

from retroagent.memory import design, execution
from retroagent.runtime import commands, turn

pytestmark = pytest.mark.network

BROKEN_FILE, BROKEN_NAME = "test_req_002_broken_import.py", "test_req_002_broken_import"
BROKEN_CODE = (
    '"""Imports a name that does not exist in shop.cart."""\n\n'
    "from shop.cart import OutOfStock\n\n\n"
    f"def {BROKEN_NAME}():\n"
    "    assert OutOfStock\n"
)
PROJECT_BROKEN = "from shop.cart import NoSuchThing\n\n\ndef test_never_runs():\n    assert NoSuchThing\n"


def git(path, *args):
    command = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args]
    return subprocess.run(command, cwd=path, check=True, capture_output=True, text=True).stdout


def write(session, test_case_id, file, name, code):
    arguments = {"test_case_id": test_case_id, "file": file, "test_name": name, "code": code}
    return turn.call_tool(session, "test_runner__write_test", arguments, ask=None)


def by_case(conn, run_id) -> dict:
    return {row["test_case_id"]: row for row in execution.list_executions(conn, run_id)}


def attempts(conn, execution_id) -> list:
    return [(a["number"], a["result"], a["failure_message"]) for a in execution.list_attempts(conn, execution_id)]


def project_tests(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM test_case WHERE origin = 'project_suite'").fetchone()[0]


@pytest.fixture(scope="module")
def shop(tmp_path_factory, pip_cache, shop_after_design):
    """The good and the broken generated test, then three runs: all on v1.0, the broken one alone on v1.0, and all on
    a branch of v1.1 whose project tests include a file that cannot be loaded."""
    with project_copy(tmp_path_factory, shop_after_design, pip_cache) as path:
        side = tmp_path_factory.mktemp("side") / "broken"
        git(path, "worktree", "add", "--quiet", "-b", "broken-tests", str(side), "v1.1")
        (side / "tests" / "test_broken.py").write_text(PROJECT_BROKEN, encoding="utf-8")
        git(side, "add", "tests/test_broken.py")
        git(side, "commit", "--quiet", "-m", "a test file that cannot be loaded")
        git(path, "worktree", "remove", str(side))
        with start(path, trust_commands=True, mode="auto") as session:
            conn = session.conn
            (good,) = [row["id"] for row in design.list_test_cases(conn, status="designed")]
            broken = design.add_test_case(
                conn, title="Broken", priority="high", designed_by="fake/model", requirement_ids=["REQ-002"]
            )
            write(session, good, GENERATED_FILE, GENERATED_NAME, generated_code())
            write(session, broken, BROKEN_FILE, BROKEN_NAME, BROKEN_CODE)
            known = project_tests(conn)
            full = commands.run(session, "all", "base").runs[0]
            alone = commands.run(session, [broken], "base").runs[0]
            turn.call_tool(session, "runtime__set_versions", {"base": "v1.0", "candidate": "broken-tests"}, ask=None)
            project_file = commands.run(session, "all", "candidate").runs[0]
            yield SimpleNamespace(
                path=path, conn=conn, good=good, broken=broken, known=known, full=full, alone=alone,
                project_file=project_file, after=project_tests(conn),
            )  # fmt: skip


def test_the_project_tests_and_the_good_generated_test_keep_their_real_results(shop):
    assert shop.full.status == "completed"
    assert shop.full.counts == {"executed": 24, "blocked": 0, "skipped": 0, "passed": 21, "failed": 2, "error": 1}
    executions = by_case(shop.conn, shop.full.run_id)
    assert (executions[shop.good]["result"], executions[shop.good]["test_revision"]) == ("passed", 1)
    failed = [row for row in executions.values() if row["result"] == "failed"]
    assert len(failed) == 2 and all(len(attempts(shop.conn, row["id"])) == 3 for row in failed)
    run = execution.get_run(shop.conn, shop.full.run_id)
    assert run["error"] is None and run["exit_code"] == 1  # the command run again, whose XML gives the results


def test_the_broken_generated_test_has_one_error_attempt_with_the_import_error(shop):
    row = by_case(shop.conn, shop.full.run_id)[shop.broken]
    assert (row["status"], row["result"], row["test_revision"]) == ("executed", "error", 1)
    ((number, result, message),) = attempts(shop.conn, row["id"])
    assert (number, result) == (1, "error")
    assert "ImportError" in message and "OutOfStock" in message
    assert design.get_test_case(shop.conn, shop.broken)["test_id"] is None
    assert shop.after == shop.known  # the error of the file was not registered as a test of the project


def test_the_first_junit_xml_of_round_1_is_kept_and_reruns_do_not_apply_the_rule(shop):
    run_dir = shop.path / ".retro" / "runs" / shop.full.run_id
    assert sorted(p.name for p in run_dir.glob("junit-*")) == [
        "junit-1.load-error-1.xml",
        "junit-1.xml",
        "junit-2.xml",
        "junit-3.xml",
    ]
    kept = (run_dir / "junit-1.load-error-1.xml").read_text(encoding="utf-8")
    assert 'classname="" name="tests.retro.test_req_002_broken_import"' in kept
    for later in ("junit-1.xml", "junit-2.xml", "junit-3.xml"):
        assert BROKEN_NAME not in (run_dir / later).read_text(encoding="utf-8")
    log = (run_dir / "run.log").read_text(encoding="utf-8")
    assert f"round 1: generated test {BROKEN_FILE} ({shop.broken}) could not be loaded" in log


def test_a_selected_run_of_only_the_broken_test_completes_with_its_error(shop):
    assert shop.alone.status == "completed"
    executions = by_case(shop.conn, shop.alone.run_id)
    assert list(executions) == [shop.broken]
    assert executions[shop.broken]["result"] == "error"


def test_a_project_file_that_cannot_be_loaded_is_named_in_the_error_of_the_run(shop):
    assert shop.project_file.status == "completed"
    run = execution.get_run(shop.conn, shop.project_file.run_id)
    assert run["error"].startswith(
        "test file tests.test_broken could not be loaded: ImportError: cannot import name 'NoSuchThing' from"
        " 'shop.cart'"
    )
    assert ";" not in run["error"]  # only the file of the project: the generated one was removed and is not named
    executions = by_case(shop.conn, shop.project_file.run_id)
    assert executions[shop.broken]["result"] == "error"  # its own file was removed first
    assert (executions[shop.good]["status"], executions[shop.good]["reason"]) == ("blocked", "not_reported")
    assert len(executions) == 2  # pytest stopped at the project file: no project test ran
