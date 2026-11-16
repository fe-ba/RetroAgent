"""Rules of a run (project-contract.md, Test execution; mcp-tools.md, test_runner.run_tests).

The project is a small git repository whose test command is ``fake_tests.py``: it writes a JUnit XML from a plan
of rounds kept outside the project, so every result below is still parsed from a JUnit XML by the runner.
"""

import json
import os
import shlex
import subprocess
import sys

import pytest
import yaml

from retroagent.config import worktrees_dir
from retroagent.memory import connect, design, execution, impact, requirements, sessions
from retroagent.servers.errors import ToolError
from retroagent.servers.test_runner import process, runner

FAKE_TESTS = r"""
import json, os, sys, time
from pathlib import Path
from xml.sax.saxutils import quoteattr

plan_path = Path(os.environ["PLAN"])
calls_path = plan_path.with_name("calls.json")
calls = json.loads(calls_path.read_text()) if calls_path.exists() else []
generated = sorted(str(p) for p in Path("tests/retro").rglob("*.py")) if Path("tests/retro").is_dir() else []
calls.append({"names": sys.argv[2:], "generated": generated})
calls_path.write_text(json.dumps(calls))
rounds = json.loads(plan_path.read_text())
spec = rounds[min(len(calls), len(rounds)) - 1]
if spec == "sleep":
    time.sleep(60)
if spec == "no_xml":
    sys.exit(2)
BODY = {
    "passed": "",
    "failed": '<failure message="boom">assert 1 == 2</failure>',
    "error": '<error message="crash">Traceback</error>',
    "skipped": '<skipped message="not here" />',
    "both": '<failure message="f" /><error message="e" />',
}
cases = []
for test_id, outcome in spec.items():
    classname, name = test_id.split("::")
    attributes = f"classname={quoteattr(classname)} name={quoteattr(name)} time=\"0.5\""
    cases.append(f"<testcase {attributes}>{BODY[outcome]}</testcase>")
out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("<testsuites><testsuite name=\"fake\">" + "".join(cases) + "</testsuite></testsuites>")
sys.exit(1 if any(o in ("failed", "error", "both") for o in spec.values()) else 0)
"""

A, B, C = "tests.test_a::test_a", "tests.test_a::test_b", "tests.test_a::test_c"
PYTHON = shlex.quote(sys.executable)


def git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class Project:
    def __init__(self, tmp_path):
        self.path = tmp_path / "project"
        self.path.mkdir()
        git(self.path, "init", "--quiet", "--initial-branch=main")
        (self.path / "fake_tests.py").write_text(FAKE_TESTS)
        git(self.path, "add", ".")
        git(self.path, "commit", "--quiet", "-m", "one")
        self.commit = git(self.path, "rev-parse", "HEAD")
        self.plan_path = tmp_path / "plan" / "plan.json"
        self.plan_path.parent.mkdir()
        self.conn = connect(self.path)
        self.session_id = sessions.start_session(
            self.conn, model="fake/model", interactive=False, result_char_limit=8000
        )
        self.configure()

    def configure(self, *, select=True, **keys):
        tests = {
            "command": f"{PYTHON} fake_tests.py {{junit}}",
            "env": {"PLAN": str(self.plan_path)},
            "reruns": 2,
        }
        if select:
            tests["select"] = f'{PYTHON} fake_tests.py {{junit}} "{{names}}"'
        config = {"tests": tests}
        for key, value in keys.items():
            section, name = key.split("__")
            config.setdefault(section, {})[name] = value
        (self.path / ".retro" / "config.yaml").write_text(yaml.safe_dump(config))

    def plan(self, *rounds):
        self.plan_path.write_text(json.dumps(rounds))
        self.plan_path.with_name("calls.json").unlink(missing_ok=True)

    @property
    def calls(self):
        return json.loads(self.plan_path.with_name("calls.json").read_text())

    def run(self, scope="all", test_case_ids=None, approved=True):
        return runner.run_tests(
            self.path,
            session_id=self.session_id,
            version="candidate",
            scope=scope,
            base_ref="v0",
            base_commit=self.commit,
            candidate_ref="v1",
            candidate_commit=self.commit,
            commands_approved=approved,
            test_case_ids=test_case_ids,
        )

    def discover(self, *test_ids):
        self.plan({test_id: "passed" for test_id in test_ids})
        self.run()
        return [self.case(test_id)["id"] for test_id in test_ids]

    def case(self, test_id):
        return self.conn.execute("SELECT * FROM test_case WHERE test_id = ?", (test_id,)).fetchone()

    def executions(self, run_id):
        """test case id -> (status, result, reason, test_revision, [(attempt number, result)])."""
        return {
            row["test_case_id"]: (
                row["status"],
                row["result"],
                row["reason"],
                row["test_revision"],
                [(a["number"], a["result"]) for a in execution.list_attempts(self.conn, row["id"])],
            )
            for row in execution.list_executions(self.conn, run_id)
        }

    def test_case_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM test_case").fetchone()[0]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("RETRO_HOME", str(tmp_path / "home"))
    for name in process.WELL_KNOWN_KEYS:
        monkeypatch.delenv(name, raising=False)
    built = Project(tmp_path)
    yield built
    built.conn.close()
    root = worktrees_dir(built.path)
    assert not root.exists() or not any(root.iterdir()), "a worktree was left behind"
    assert git(built.path, "worktree", "list", "--porcelain").count("worktree ") == 1


def generated_test(project, file="test_gen.py", name="test_gen_one"):
    (project.path / ".retro" / "tests").mkdir(exist_ok=True)
    (project.path / ".retro" / "tests" / file).write_text(f"def {name}():\n    pass\n")
    test_case_id = design.add_test_case(project.conn, title="generated", priority="high", designed_by="fake/model")
    design.mark_implemented(project.conn, test_case_id, f"{file}::{name}")
    return test_case_id


def test_a_full_run_discovers_tests_in_xml_order_with_name_links(project):
    requirements.add_requirement(project.conn, id="REQ-001", title="t", description="d", source_file="r.md")
    project.plan({B + "_req_001": "passed", A: "passed", "tests.test_a::test_s": "skipped", C: "both"})

    summary = project.run()

    assert summary.status == "completed"
    rows = project.conn.execute("SELECT * FROM test_case ORDER BY id").fetchall()
    assert [(r["id"], r["test_id"]) for r in rows] == [
        ("TC-001", B + "_req_001"),
        ("TC-002", A),
        ("TC-003", "tests.test_a::test_s"),
        ("TC-004", C),
    ]
    assert {(r["origin"], r["priority"], r["status"]) for r in rows} == {("project_suite", "medium", "implemented")}
    assert rows[1]["implementation"] == A
    links = project.conn.execute("SELECT * FROM test_case_requirement").fetchall()
    assert [(r["test_case_id"], r["requirement_id"], r["link"]) for r in links] == [("TC-001", "REQ-001", "name")]

    executions = project.executions(summary.run_id)
    assert executions["TC-002"] == ("executed", "passed", None, None, [(1, "passed")])
    assert executions["TC-003"] == ("skipped", None, "not here", None, [])
    assert executions["TC-004"][:2] == ("executed", "error")  # a failure and an error give error
    assert summary.counts == {"executed": 3, "blocked": 0, "skipped": 1, "passed": 2, "failed": 0, "error": 1}

    run = execution.get_run(project.conn, summary.run_id)
    assert run["exit_code"] == 1
    assert run["junit_path"] == f".retro/runs/{summary.run_id}/junit-1.xml"
    assert run["command"] == f"{sys.executable} fake_tests.py {project.path}/.retro/runs/{summary.run_id}/junit-1.xml"


def test_the_first_attempt_gives_the_result_and_reruns_always_run(project):
    project.plan({A: "failed", B: "error", C: "passed"}, {A: "passed", B: "error"}, {A: "passed", B: "error"})

    summary = project.run()

    executions = project.executions(summary.run_id)
    assert executions["TC-001"][:2] == ("executed", "failed")
    assert executions["TC-001"][4] == [(1, "failed"), (2, "passed"), (3, "passed")]
    assert executions["TC-002"][4] == [(1, "error"), (2, "error"), (3, "error")]
    assert executions["TC-003"][4] == [(1, "passed")]
    assert [call["names"] for call in project.calls] == [[], ["test_a or test_b"], ["test_a or test_b"]]
    run_dir = project.path / ".retro" / "runs" / summary.run_id
    assert sorted(p.name for p in run_dir.iterdir()) == [
        "junit-1.xml",
        "junit-2.xml",
        "junit-3.xml",
        "run.log",
        "service.log",
    ]


def test_without_tests_select_reruns_run_the_full_command(project):
    project.configure(select=False)
    project.plan({A: "failed", B: "passed"})

    summary = project.run()

    assert [call["names"] for call in project.calls] == [[], [], []]
    assert project.executions(summary.run_id)["TC-001"][4] == [(1, "failed"), (2, "failed"), (3, "failed")]
    assert len(project.executions(summary.run_id)["TC-002"][4]) == 1


def test_attempt_numbers_are_rounds_and_a_round_without_a_result_leaves_a_gap(project):
    project.plan({A: "failed", B: "failed"}, {B: "skipped"}, {A: "passed", B: "failed"})

    summary = project.run()

    executions = project.executions(summary.run_id)
    assert executions["TC-001"][4] == [(1, "failed"), (3, "passed")]
    assert executions["TC-002"][4] == [(1, "failed"), (3, "failed")]


@pytest.mark.parametrize("failure", ["no_xml", "sleep"])
def test_a_failed_rerun_round_stores_no_attempt_and_stops_the_reruns(project, failure):
    project.configure(tests__timeout=1)
    project.plan({A: "failed"}, failure, {A: "passed"})

    summary = project.run()

    assert summary.status == "completed"
    assert project.executions(summary.run_id)["TC-001"] == ("executed", "failed", None, None, [(1, "failed")])
    assert len(project.calls) == 2
    run = execution.get_run(project.conn, summary.run_id)
    assert (run["exit_code"], run["error"]) == (1, None)
    log = (project.path / run["evidence_dir"] / "run.log").read_text()
    assert "round 2:" in log and "no further round runs" in log


def test_no_valid_junit_xml_blocks_every_known_test_case(project):
    project.discover(A, B)
    project.plan("no_xml")

    summary = project.run()

    run = execution.get_run(project.conn, summary.run_id)
    assert (run["status"], run["exit_code"], run["junit_path"]) == ("error", 2, None)
    assert run["error"].startswith("test command: no valid JUnit XML")
    assert project.executions(summary.run_id) == {
        "TC-001": ("blocked", None, "no_junit", None, []),
        "TC-002": ("blocked", None, "no_junit", None, []),
    }


def test_a_run_that_ends_early_on_an_undiscovered_project_has_no_execution(project):
    project.plan("no_xml")

    summary = project.run()

    assert summary.status == "error"
    assert project.executions(summary.run_id) == {}
    assert project.test_case_count() == 0


def test_a_test_command_stopped_by_the_timeout_interrupts_the_run(project):
    project.discover(A)
    project.configure(tests__timeout=1)
    project.plan("sleep")

    summary = project.run()

    run = execution.get_run(project.conn, summary.run_id)
    assert (run["status"], run["exit_code"]) == ("interrupted", None)
    assert run["error"] == "test command: stopped after 1 seconds"
    assert project.executions(summary.run_id)["TC-001"][:3] == ("blocked", None, "timeout")


@pytest.mark.parametrize(
    ("setup", "error"), [("exit 3", "setup: exit code 3"), ("sleep 30", "setup: stopped after 1 seconds")]
)
def test_a_failed_setup_blocks_the_run(project, setup, error):
    project.discover(A)
    project.configure(tests__setup=setup, tests__timeout=1)
    project.plan({A: "passed"})

    summary = project.run()

    run = execution.get_run(project.conn, summary.run_id)
    assert (run["status"], run["error"], run["exit_code"], run["junit_path"]) == ("error", error, None, None)
    assert run["command"].endswith("junit-1.xml")  # recorded although it never ran
    assert project.executions(summary.run_id)["TC-001"][:3] == ("blocked", None, "setup_failed")
    assert not project.plan_path.with_name("calls.json").exists()


def test_a_service_that_never_answers_blocks_the_run_and_is_stopped(project):
    project.discover(A)
    project.configure(service__start="echo $$ > {run_dir}/service.pid; exec sleep 30", service__ready_timeout=1)
    project.plan({A: "passed"})

    summary = project.run()

    run = execution.get_run(project.conn, summary.run_id)
    assert run["status"] == "error" and run["error"].startswith("service: ")
    assert project.executions(summary.run_id)["TC-001"][:3] == ("blocked", None, "service_not_ready")
    pid = int((project.path / run["evidence_dir"] / "service.pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_a_selected_run_blocks_what_is_not_reported_ignores_the_rest_and_registers_nothing(project):
    project.discover(A, B, C)
    project.plan({A: "passed", B: "passed", "tests.test_a::test_new": "passed"})

    summary = project.run("selected", ["TC-001", "TC-003"])

    assert project.calls[0]["names"] == ["test_a or test_c"]
    assert project.executions(summary.run_id) == {
        "TC-001": ("executed", "passed", None, None, [(1, "passed")]),
        "TC-003": ("blocked", None, "not_reported", None, []),
    }
    assert project.test_case_count() == 3


def test_a_suite_run_executes_the_current_suite(project):
    project.discover(A, B)
    analysis_id = impact.add_analysis(
        project.conn,
        session_id=project.session_id,
        base_ref="v0",
        base_commit=project.commit,
        candidate_ref="v1",
        candidate_commit=project.commit,
        files=[],
    )
    suite_id = design.add_suite(project.conn, analysis_id=analysis_id, session_id=project.session_id)
    design.add_to_suite(project.conn, suite_id, test_case_id="TC-002", position=1, selection_reason="changed")
    project.plan({A: "passed", B: "failed"})

    summary = project.run("suite")

    assert execution.get_run(project.conn, summary.run_id)["suite_id"] == suite_id
    assert list(project.executions(summary.run_id)) == ["TC-002"]
    assert project.calls[0]["names"] == ["test_b"]


def test_a_retired_project_test_keeps_its_executions_but_is_not_blocked_by_an_early_end(project):
    project.discover(A, B)
    design.retire_test_case(project.conn, "TC-001", reason="obsolete", retired_by="fake/model")
    project.plan({A: "passed", B: "passed"})

    summary = project.run()

    assert set(project.executions(summary.run_id)) == {"TC-001", "TC-002"}
    assert project.test_case_count() == 2

    project.plan("no_xml")
    summary = project.run()
    assert set(project.executions(summary.run_id)) == {"TC-002"}


def test_a_generated_test_is_copied_bound_by_its_file_then_matched_by_test_id(project):
    test_case_id = generated_test(project)
    entry = "tests.retro.test_gen::test_gen_one"
    project.plan({A: "passed", entry: "failed"})

    summary = project.run()

    assert project.calls[0]["generated"] == ["tests/retro/test_gen.py"]
    assert design.get_test_case(project.conn, test_case_id)["test_id"] == entry
    executions = project.executions(summary.run_id)
    assert executions[test_case_id][:4] == ("executed", "failed", None, 1)
    assert project.test_case_count() == 2  # only test_a was registered

    project.plan({entry: "passed"})
    assert project.executions(project.run().run_id)[test_case_id][:4] == ("executed", "passed", None, 1)

    project.plan({A: "passed"})
    assert project.executions(project.run().run_id)[test_case_id] == ("blocked", None, "not_reported", 1, [])


def test_a_generated_test_that_cannot_be_bound_is_ignored_and_not_reported(project):
    test_case_id = generated_test(project)
    project.plan({"x.a::test_gen_one": "passed", "y.b::test_gen_one": "passed"})

    summary = project.run()

    assert project.executions(summary.run_id) == {test_case_id: ("blocked", None, "not_reported", 1, [])}
    assert design.get_test_case(project.conn, test_case_id)["test_id"] is None
    assert project.test_case_count() == 1


def test_a_retired_generated_test_is_not_copied(project):
    test_case_id = generated_test(project)
    design.retire_test_case(project.conn, test_case_id, reason="broken", retired_by="fake/model")
    project.plan({A: "passed"})

    summary = project.run()

    assert project.calls[0]["generated"] == []
    assert test_case_id not in project.executions(summary.run_id)


def test_junit_files_matched_by_a_pattern_are_copied_and_removed_before_the_next_round(project):
    project.configure(
        select=False,
        tests__command=f"{PYTHON} fake_tests.py reports/out.xml",
        tests__junit="reports/*.xml",
    )
    project.plan({A: "failed"}, "no_xml")

    summary = project.run()

    run = execution.get_run(project.conn, summary.run_id)
    assert run["junit_path"] == f".retro/runs/{summary.run_id}/junit-1/"
    assert (project.path / run["junit_path"] / "reports" / "out.xml").is_file()
    assert project.executions(summary.run_id)["TC-001"][4] == [(1, "failed")]  # round 2 did not see round 1's file


def interrupt_on_call(monkeypatch, number):
    real, calls = process.run, []

    def run(*args, **kwargs):
        calls.append(args)
        if len(calls) == number:
            raise KeyboardInterrupt
        return real(*args, **kwargs)

    monkeypatch.setattr(process, "run", run)


def test_an_interruption_before_the_junit_xml_interrupts_the_run(project, monkeypatch):
    project.discover(A)
    interrupt_on_call(monkeypatch, 1)

    with pytest.raises(KeyboardInterrupt):
        project.run()

    run = execution.get_run(project.conn, "RUN-0002")
    assert (run["status"], run["error"]) == ("interrupted", "test command: interrupted by the user")
    assert project.executions("RUN-0002")["TC-001"][:3] == ("blocked", None, "interrupted")


def test_an_interruption_during_reruns_keeps_the_run_completed(project, monkeypatch):
    project.plan({A: "failed"})
    interrupt_on_call(monkeypatch, 2)

    with pytest.raises(KeyboardInterrupt):
        project.run()

    assert execution.get_run(project.conn, "RUN-0001")["status"] == "completed"
    assert project.executions("RUN-0001")["TC-001"] == ("executed", "failed", None, None, [(1, "failed")])


def run_count(project):
    return project.conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]


def test_refusals_create_no_run(project):
    designed = design.add_test_case(project.conn, title="designed", priority="low", designed_by="fake/model")
    project.plan({A: "passed"})

    def refused(code, **kwargs):
        with pytest.raises(ToolError) as caught:
            project.run(**kwargs)
        assert caught.value.code == code

    refused("denied", approved=False)
    refused("invalid_state", scope="suite")  # no current suite
    refused("not_found", scope="selected", test_case_ids=["TC-999"])
    refused("invalid_state", scope="selected", test_case_ids=[designed])
    refused("invalid_argument", scope="all", test_case_ids=[designed])
    project.configure(tests__command="pytest -k {names}")
    refused("invalid_argument")
    project.configure(tests__command=None)
    refused("invalid_state")

    assert run_count(project) == 0
    assert not (project.path / ".retro" / "runs").exists()
    assert not project.plan_path.with_name("calls.json").exists()


def test_a_commit_that_cannot_be_checked_out_fails_without_a_run(project):
    project.plan({A: "passed"})
    with pytest.raises(ToolError) as caught:
        runner.run_tests(
            project.path,
            session_id=project.session_id,
            version="base",
            scope="all",
            base_ref="v0",
            base_commit="0" * 40,
            candidate_ref="v1",
            candidate_commit=project.commit,
            commands_approved=True,
        )
    assert caught.value.code == "execution_failed"
    assert run_count(project) == 0
