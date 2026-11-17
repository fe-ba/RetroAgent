"""``test_runner.write_test`` and ``test_runner.get_evidence`` through the runtime and the real ``test_runner`` server,
on shop-api after ``/design``: the result and the record, every error code, a written test run by ``run_tests``
with its revision, a rewrite with its revision and the difference in the question, and the evidence of a run."""

from types import SimpleNamespace

import pytest
from fixtures.agent_session import GENERATED_FILE, GENERATED_NAME, generated_code
from fixtures.example_project import project_copy, start
from fixtures.mcp_project import error_of

from retroagent.memory import design, execution, sessions
from retroagent.runtime import commands, permissions, turn

WRITE, EVIDENCE = "test_runner__write_test", "test_runner__get_evidence"
FAILING_NAME = "test_req_002_fails_on_purpose"
FAILING_CODE = f'"""Fails on purpose, to have evidence."""\n\n\ndef {FAILING_NAME}():\n    assert 1 + 1 == 3, "boom"\n'
REWRITTEN = generated_code() + "    assert len(cart.items) == 1\n"


def designed_cases(conn) -> list[str]:
    rows = conn.execute("SELECT id FROM test_case WHERE status = 'designed' AND retired_at IS NULL ORDER BY id")
    return [row["id"] for row in rows]


def snapshot(session) -> tuple:
    """What a refused call must leave as it was: every test case and every file of ``.retro/tests/``."""
    rows = [tuple(row) for row in session.conn.execute("SELECT * FROM test_case ORDER BY id")]
    links = [tuple(row) for row in session.conn.execute("SELECT * FROM test_case_requirement ORDER BY rowid")]
    root = session.project_dir / ".retro" / "tests"
    files = sorted((str(p.relative_to(root)), p.is_symlink() or p.is_dir() or p.read_bytes()) for p in root.rglob("*"))
    return rows, links, files


def write(session, ask=None, **arguments):
    return turn.call_tool(session, WRITE, arguments, ask=ask or (lambda request: permissions.ONCE))


@pytest.fixture
def project(tmp_path_factory, shop_after_design):
    with project_copy(tmp_path_factory, shop_after_design) as path:
        yield path


def test_write_test_writes_the_file_and_sets_the_test_case_implemented(project):
    with start(project, trust_commands=True) as session:
        test_case_id = designed_cases(session.conn)[0]
        result = write(session, test_case_id=test_case_id, file=GENERATED_FILE, test_name=GENERATED_NAME,
                       code=generated_code())  # fmt: skip
        assert result == {
            "test_case_id": test_case_id,
            "implementation": f"{GENERATED_FILE}::{GENERATED_NAME}",
            "revision": 1,
        }
        row = design.get_test_case(session.conn, test_case_id)
        assert (row["status"], row["implementation"], row["revision"], row["test_id"]) == (
            "implemented", f"{GENERATED_FILE}::{GENERATED_NAME}", 1, None,
        )  # fmt: skip
        assert (project / ".retro" / "tests" / GENERATED_FILE).read_text(encoding="utf-8") == generated_code()
        call = session.conn.execute("SELECT * FROM tool_call WHERE tool = 'write_test'").fetchone()
        assert (call["server"], call["outcome"]) == ("test_runner", "ok")


def test_every_error_of_write_test_writes_nothing(project, tmp_path):
    with start(project, trust_commands=True) as session:
        conn = session.conn
        designed = designed_cases(conn)[0]
        project_test = conn.execute("SELECT id FROM test_case WHERE origin = 'project_suite' LIMIT 1").fetchone()["id"]
        retired = design.add_test_case(conn, title="Old", priority="low", designed_by="fake/model")
        design.retire_test_case(conn, retired, reason="obsolete", retired_by="fake/model")
        other = design.add_test_case(conn, title="Other", priority="low", designed_by="fake/model",
                                     requirement_ids=["REQ-002"])  # fmt: skip
        write(session, test_case_id=other, file="test_other.py", test_name="test_req_002_other", code="x = 1\n")
        tests = project / ".retro" / "tests"
        (tests / "test_left_by_someone.py").write_text("y = 2\n", encoding="utf-8")
        outside = tmp_path / "outside"
        outside.mkdir()
        (tests / "linked").symlink_to(outside, target_is_directory=True)
        valid = {"test_case_id": designed, "file": GENERATED_FILE, "test_name": GENERATED_NAME, "code": "z = 3\n"}
        cases = [
            ("not_found", {**valid, "test_case_id": "TC-999"}),
            ("invalid_state", {**valid, "test_case_id": project_test}),
            ("invalid_state", {**valid, "test_case_id": retired}),
            ("invalid_argument", {**valid, "file": "../escape.py"}),
            ("invalid_argument", {**valid, "file": "/tmp/escape.py"}),
            ("invalid_argument", {**valid, "file": "linked/test_escape.py"}),
            ("invalid_argument", {**valid, "test_name": "test_quantity_above_stock"}),  # traces REQ-002
            ("invalid_argument", {**valid, "test_name": "test_req_003_quantity"}),
            ("invalid_argument", {**valid, "fields": {"steps": ["Add 6 units"]}}),  # only in a rewrite
            ("invalid_argument", {**valid, "file": "test_other.py"}),  # INV-17: the file of another test
            ("invalid_argument", {**valid, "test_name": "test_req_002_other"}),  # INV-17: its name
            ("invalid_argument", {**valid, "file": "test_left_by_someone.py"}),  # belongs to no test case
            ("invalid_argument", {**valid, "result": "passed"}),  # no input for a result (INV-03)
            ("invalid_argument", {**valid, "code": ""}),
            (
                "invalid_argument",
                {**valid, "test_case_id": other, "file": "test_moved.py", "test_name": "test_req_002_other"},
            ),  # a rewrite keeps the file  # fmt: skip
        ]
        before = snapshot(session)
        for code, arguments in cases:
            assert error_of(lambda arguments=arguments: write(session, **arguments)).code == code, arguments
        assert snapshot(session) == before
        assert list(outside.iterdir()) == []
        assert not (project / ".retro" / "escape.py").exists() and not (tmp_path / "escape.py").exists()

        session.mode = "plan"
        assert error_of(lambda: write(session, **valid)).code == "denied"
        assert snapshot(session) == before


# A written test in runs, a rewrite, and the evidence: one sequence of runs for the module.


@pytest.fixture(scope="module")
def written(tmp_path_factory, pip_cache, shop_after_design):
    """Two generated tests written by ``write_test``: the oracle's, which passes, and one that fails. RUN 1 runs both
    against the baseline; then the first is rewritten, and RUN 2 runs it again."""
    with project_copy(tmp_path_factory, shop_after_design, pip_cache) as path:
        with start(path, trust_commands=True) as session:
            conn = session.conn
            passing = designed_cases(conn)[0]
            failing = design.add_test_case(conn, title="Fails", priority="low", designed_by="fake/model",
                                           requirement_ids=["REQ-002"])  # fmt: skip
            write(session, test_case_id=passing, file=GENERATED_FILE, test_name=GENERATED_NAME, code=generated_code())
            write(session, test_case_id=failing, file="test_fails.py", test_name=FAILING_NAME, code=FAILING_CODE)
            first = commands.run(session, [passing, failing], "base", ask=lambda request: permissions.ONCE)
            asked = []

            def ask(request):
                asked.append(request)
                return permissions.ONCE

            fields = {"expected_result": "InsufficientStock is raised and the cart keeps one line of 3 units."}
            rewrite = write(session, ask=ask, test_case_id=passing, file=GENERATED_FILE, test_name=GENERATED_NAME,
                            code=REWRITTEN, fields=fields)  # fmt: skip
            second = commands.run(session, [passing], "base", ask=lambda request: permissions.ONCE)
            yield SimpleNamespace(
                session=session, path=path, passing=passing, failing=failing, first=first.runs[0],
                second=second.runs[0], rewrite=rewrite, question=asked[0], fields=fields,
            )  # fmt: skip


def execution_of(conn, run_id, test_case_id):
    return next(row for row in execution.list_executions(conn, run_id) if row["test_case_id"] == test_case_id)


@pytest.mark.network
def test_a_written_test_is_run_and_its_execution_carries_the_revision(written):
    conn = written.session.conn
    assert written.first.status == "completed"
    passed = execution_of(conn, written.first.run_id, written.passing)
    assert (passed["status"], passed["result"], passed["test_revision"]) == ("executed", "passed", 1)
    failed = execution_of(conn, written.first.run_id, written.failing)
    assert (failed["result"], failed["test_revision"]) == ("failed", 1)
    test_id = design.get_test_case(conn, written.passing)["test_id"]
    assert test_id.endswith(f"::{GENERATED_NAME}")  # bound the first time a run reported it


@pytest.mark.network
def test_a_rewrite_creates_revision_2_and_the_next_run_records_it(written):
    session = written.session
    assert written.rewrite == {
        "test_case_id": written.passing,
        "implementation": f"{GENERATED_FILE}::{GENERATED_NAME}",
        "revision": 2,
    }
    row = design.get_test_case(session.conn, written.passing)
    assert (row["revision"], row["expected_result"]) == (2, written.fields["expected_result"])
    assert (written.path / ".retro" / "tests" / GENERATED_FILE).read_text(encoding="utf-8") == REWRITTEN
    again = execution_of(session.conn, written.second.run_id, written.passing)
    assert (again["result"], again["test_revision"]) == ("passed", 2)
    # The history keeps the execution of revision 1.
    history = turn.call_tool(session, "memory__get_test_case_history", {"test_case_id": written.passing}, ask=None)
    assert [e["run_id"] for e in history["executions"]] == [written.first.run_id, written.second.run_id]
    stored = execution.test_case_history(session.conn, written.passing)
    assert [(row["run_id"], row["result"], row["test_revision"]) for row in stored] == [
        (written.first.run_id, "passed", 1),
        (written.second.run_id, "passed", 2),
    ]


@pytest.mark.network
def test_the_question_of_a_rewrite_shows_the_difference_with_the_previous_revision(written):
    details = written.question.details
    assert details[3] == "Rewrite: revision 2. Changes to the code:"
    assert details[4].splitlines()[:2] == [
        f"--- {GENERATED_FILE} (revision 1)",
        f"+++ {GENERATED_FILE} (revision 2)",
    ]
    assert "+    assert len(cart.items) == 1" in details[4].splitlines()
    assert details[5] == "Design fields that change with it: expected_result"


def evidence(session, **arguments) -> dict:
    return turn.call_tool(session, EVIDENCE, arguments, ask=None)


@pytest.mark.network
def test_get_evidence_returns_the_failed_executions_with_every_attempt_and_the_run_log(written):
    session, run_id = written.session, written.first.run_id
    result = evidence(session, run_id=run_id)
    text = result["evidence"]
    assert (result["run_id"], result["truncated"]) == (run_id, False)
    assert text.startswith(f"Run {run_id} against base v1.0 (")
    assert f"### {written.failing} test_fails.py::{FAILING_NAME}: executed, result failed, revision 1" in text
    assert written.passing not in text  # a passed execution is not evidence of a failure
    attempts = [line.split(":")[0] for line in text.splitlines() if line.startswith("Attempt ")]
    assert attempts == ["Attempt 1", "Attempt 2", "Attempt 3"]  # the first one and two reruns
    assert text.count("boom") >= 3
    run_log = (written.path / ".retro" / "runs" / run_id / "run.log").read_text(encoding="utf-8")
    assert f"## run.log (.retro/runs/{run_id}/run.log)" in text and run_log.rstrip("\n") in text

    one = evidence(session, run_id=run_id, test_case_id=written.passing)["evidence"]
    assert f"### {written.passing} {GENERATED_FILE}::{GENERATED_NAME}: executed, result passed, revision 1" in one
    assert written.failing not in one.split("## run.log")[0]


@pytest.mark.network
def test_get_evidence_comes_in_parts_that_join_into_the_whole(written):
    session, run_id = written.session, written.first.run_id
    whole = evidence(session, run_id=run_id)["evidence"]
    sessions.set_result_limit(session.conn, session.id, 400)
    try:
        parts, start_line = [], 1
        while True:
            result = evidence(session, run_id=run_id, start_line=start_line)
            parts.append(result["evidence"])
            assert len(result["evidence"]) <= 400
            if not result["truncated"]:
                break
            start_line = result["next_line"]
        assert len(parts) > 2 and "".join(parts) == whole
    finally:
        sessions.set_result_limit(session.conn, session.id, 20_000)


@pytest.mark.network
def test_get_evidence_errors(written):
    session, run_id = written.session, written.first.run_id
    assert error_of(lambda: evidence(session, run_id="RUN-9999")).code == "not_found"
    assert error_of(lambda: evidence(session, run_id=run_id, test_case_id="TC-999")).code == "not_found"
    project_test = session.conn.execute(
        "SELECT id FROM test_case WHERE origin = 'project_suite' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    assert error_of(lambda: evidence(session, run_id=run_id, test_case_id=project_test)).code == "not_found"
    assert error_of(lambda: evidence(session, run_id=run_id, start_line=0)).code == "invalid_argument"
    assert error_of(lambda: evidence(session, run_id=run_id, start_line=100_000)).code == "invalid_argument"
    assert "No execution failed or was blocked." in evidence(session, run_id=written.second.run_id)["evidence"]
