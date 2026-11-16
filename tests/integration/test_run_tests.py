"""Runs of the example against v1.0 and v1.1 (ORACLE.md, Raw results and Reference scenario).

One example project for the whole module, created in a temporary directory with a temporary ``RETRO_HOME``.
The fixture makes RUN-0001 (full run against v1.0) and RUN-0002 (full run against v1.1); the tests run in file
order and each later run is made by the test that checks it.
"""

import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import files

import pytest
import yaml

from retroagent.config import cache_dir, retro_home, worktrees_dir
from retroagent.examples import materialize
from retroagent.memory import connect, design, execution, impact, requirements, sessions
from retroagent.servers.errors import ToolError
from retroagent.servers.test_runner import junit, process
from retroagent.servers.test_runner.runner import run_tests

pytestmark = pytest.mark.network

SEARCH = "tests.test_catalog::test_req_001_search_results_are_sorted_by_name"
TAX = "tests.test_tax::test_req_007_tax_rounds_half_up"
SHIPPING = "tests.test_shipping::test_req_005_shipping_charged_when_discount_drops_below_threshold"
COUPON = "tests.test_discounts::test_req_004_second_coupon_is_rejected"
GENERATED = "test_req_002_quantity_above_stock_is_rejected"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@dataclass
class Shop:
    path: object
    conn: object
    session_id: int
    commits: dict
    full_v10: str = ""
    full_v11: str = ""

    def run(self, version, scope="all", test_case_ids=None, approved=True):
        return run_tests(
            self.path,
            session_id=self.session_id,
            version=version,
            scope=scope,
            base_ref="v1.0",
            base_commit=self.commits["v1.0"],
            candidate_ref="v1.1",
            candidate_commit=self.commits["v1.1"],
            commands_approved=approved,
            test_case_ids=test_case_ids,
        )

    def executions(self, run_id):
        """test_id -> (test case id, status, result, reason, test_revision, [(attempt number, result)])."""
        rows = self.conn.execute(
            "SELECT e.*, tc.test_id FROM test_execution AS e JOIN test_case AS tc ON tc.id = e.test_case_id"
            " WHERE e.run_id = ? ORDER BY e.id",
            (run_id,),
        ).fetchall()
        return {
            row["test_id"] or row["test_case_id"]: (
                row["test_case_id"],
                row["status"],
                row["result"],
                row["reason"],
                row["test_revision"],
                [(a["number"], a["result"]) for a in execution.list_attempts(self.conn, row["id"])],
            )
            for row in rows
        }

    def counts(self, run_id):
        executions = self.executions(run_id).values()
        return (
            len([e for e in executions if e[1] == "executed"]),
            len([e for e in executions if e[2] == "passed"]),
            len([e for e in executions if e[2] in ("failed", "error")]),
        )

    def evidence(self, run_id):
        return self.path / execution.get_run(self.conn, run_id)["evidence_dir"]

    def test_case_ids(self):
        return [row["id"] for row in self.conn.execute("SELECT id FROM test_case ORDER BY id")]

    @contextmanager
    def config(self, change):
        """Change ``.retro/config.yaml`` of the working copy for one run, then restore it byte for byte."""
        path = self.path / ".retro" / "config.yaml"
        original = path.read_bytes()
        config = yaml.safe_load(original)
        change(config)
        path.write_text(yaml.safe_dump(config))
        try:
            yield
        finally:
            path.write_bytes(original)


@pytest.fixture(scope="module")
def shop(tmp_path_factory, pip_cache):
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("RETRO_HOME", str(tmp_path_factory.mktemp("retro-home")))
        for name in process.WELL_KNOWN_KEYS:  # a real key never reaches a command or a log of these tests
            patch.delenv(name, raising=False)
        path = tmp_path_factory.mktemp("work") / "shop-api-demo"
        materialize("shop-api", path)
        cache = cache_dir(path)
        cache.mkdir(parents=True)
        (cache / "pip").symlink_to(pip_cache, target_is_directory=True)
        conn = connect(path)
        session_id = sessions.start_session(conn, model="fake/model", interactive=False, result_char_limit=20000)
        for number in range(1, 9):  # what memory.sync_requirements will store; only the identifiers matter here
            requirement_id = f"REQ-{number:03d}"
            requirements.add_requirement(
                conn, id=requirement_id, title=requirement_id, description="-", source_file="docs/requirements.md"
            )
        commits = {tag: git(path, "rev-parse", f"{tag}^{{commit}}").strip() for tag in ("v1.0", "v1.1")}
        built = Shop(path, conn, session_id, commits)
        built.full_v10 = built.run("base").run_id
        built.full_v11 = built.run("candidate").run_id
        yield built
        conn.close()


def test_a_full_run_on_v1_0_discovers_22_tests_in_xml_order(shop):
    run = execution.get_run(shop.conn, shop.full_v10)
    assert (run["id"], run["status"], run["version_role"], run["scope"]) == ("RUN-0001", "completed", "base", "all")
    assert shop.counts(shop.full_v10) == (22, 20, 2)

    reported = [entry.test_id for entry in junit.parse([shop.evidence(shop.full_v10) / "junit-1.xml"])]
    known = shop.conn.execute("SELECT id, test_id, origin FROM test_case WHERE id <= 'TC-022' ORDER BY id").fetchall()
    assert [row["id"] for row in known] == [f"TC-{n:03d}" for n in range(1, 23)]
    assert [row["test_id"] for row in known] == reported
    assert {row["origin"] for row in known} == {"project_suite"}

    failed = {test_id for test_id, e in shop.executions(shop.full_v10).items() if e[2] != "passed"}
    assert failed == {SEARCH, TAX}
    search = design.get_test_case(shop.conn, shop.executions(shop.full_v10)[SEARCH][0])
    links = shop.conn.execute(
        "SELECT requirement_id, link FROM test_case_requirement WHERE test_case_id = ?", (search["id"],)
    ).fetchall()
    assert [tuple(row) for row in links] == [("REQ-001", "name")]


def test_a_full_run_on_v1_1_discovers_the_four_tests_added_by_the_change(shop):
    run = execution.get_run(shop.conn, shop.full_v11)
    assert (run["id"], run["status"], run["version_role"]) == ("RUN-0002", "completed", "candidate")
    assert shop.counts(shop.full_v11) == (26, 22, 4)

    reported = [entry.test_id for entry in junit.parse([shop.evidence(shop.full_v11) / "junit-1.xml"])]
    known_before = set(shop.executions(shop.full_v10))
    added = shop.conn.execute("SELECT id, test_id FROM test_case WHERE id > 'TC-022' ORDER BY id").fetchall()
    assert [row["id"] for row in added] == ["TC-023", "TC-024", "TC-025", "TC-026"]
    assert [row["test_id"] for row in added] == [test_id for test_id in reported if test_id not in known_before]

    failed = {test_id for test_id, e in shop.executions(shop.full_v11).items() if e[2] != "passed"}
    assert failed == {SEARCH, TAX, SHIPPING, COUPON}


def test_the_first_attempt_gives_the_result_and_reruns_detect_the_flaky_test(shop):
    for run_id, failing in ((shop.full_v10, (TAX,)), (shop.full_v11, (TAX, SHIPPING, COUPON))):
        executions = shop.executions(run_id)
        assert executions[SEARCH][2] == "failed"
        assert executions[SEARCH][5] == [(1, "failed"), (2, "passed"), (3, "passed")]
        for test_id in failing:
            assert executions[test_id][2] == "failed"
            assert executions[test_id][5] == [(1, "failed"), (2, "failed"), (3, "failed")]
        for test_id, e in executions.items():
            if test_id not in (SEARCH, *failing):
                assert e[1:3] == ("executed", "passed") and e[5] == [(1, "passed")]


def test_every_attempt_has_its_evidence(shop):
    for run_id in (shop.full_v10, shop.full_v11):
        evidence = shop.evidence(run_id)
        run = execution.get_run(shop.conn, run_id)
        assert run["junit_path"] == f".retro/runs/{run_id}/junit-1.xml"
        assert run["command"].endswith(f"--junitxml={evidence}/junit-1.xml")
        assert "exit code" in (evidence / "run.log").read_text()
        assert (evidence / "service.log").is_file()
        for test_id, e in shop.executions(run_id).items():
            for number, result in e[5]:
                entries = {entry.test_id: entry for entry in junit.parse([evidence / f"junit-{number}.xml"])}
                assert entries[test_id].outcome == result


def test_a_suite_run_on_v1_0_blocks_the_tests_added_in_v1_1(shop):
    tests_dir = shop.path / ".retro" / "tests"
    tests_dir.mkdir()
    source = files("retroagent.resources").joinpath("examples", "shop-api", "expected", f"{GENERATED}.py")
    (tests_dir / f"{GENERATED}.py").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    generated = design.add_test_case(
        shop.conn, title="Quantity above stock", priority="high", designed_by="fake/model", requirement_ids=["REQ-002"]
    )
    design.mark_implemented(shop.conn, generated, f"{GENERATED}.py::{GENERATED}")
    designed_only = design.add_test_case(
        shop.conn, title="Unknown product", priority="medium", designed_by="fake/model", requirement_ids=["REQ-002"]
    )
    assert (generated, designed_only) == ("TC-027", "TC-028")
    analysis_id = impact.add_analysis(
        shop.conn,
        session_id=shop.session_id,
        base_ref="v1.0",
        base_commit=shop.commits["v1.0"],
        candidate_ref="v1.1",
        candidate_commit=shop.commits["v1.1"],
        files=[{"path": "src/shop/pricing.py", "change": "modified", "lines_added": 1, "lines_removed": 1}],
    )
    suite_id = design.add_suite(shop.conn, analysis_id=analysis_id, session_id=shop.session_id)
    for position, test_case_id in enumerate(shop.test_case_ids(), start=1):
        design.add_to_suite(shop.conn, suite_id, test_case_id=test_case_id, position=position, selection_reason="all")

    summary = shop.run("base", "suite")

    assert (summary.run_id, summary.status) == ("RUN-0003", "completed")
    assert shop.counts(summary.run_id) == (23, 21, 2)
    executions = shop.executions(summary.run_id)
    blocked = sorted(e[0] for e in executions.values() if e[1] == "blocked")
    assert blocked == ["TC-023", "TC-024", "TC-025", "TC-026"]
    assert {e[3] for e in executions.values() if e[1] == "blocked"} == {"not_reported"}
    bound = f"tests.retro.{GENERATED}::{GENERATED}"
    assert design.get_test_case(shop.conn, generated)["test_id"] == bound
    assert executions[bound][:5] == (generated, "executed", "passed", None, 1)
    assert "TC-028" not in {e[0] for e in executions.values()}
    assert shop.test_case_ids()[-1] == "TC-028"  # a suite run registers nothing


def test_a_failing_setup_blocks_every_known_test_case(shop):
    known = [row["id"] for row in design.active_implemented_test_cases(shop.conn)]
    assert len(known) == 27

    with shop.config(lambda config: config["tests"].update(setup="exit 3")):
        summary = shop.run("candidate")

    run = execution.get_run(shop.conn, summary.run_id)
    assert (run["status"], run["error"], run["exit_code"], run["junit_path"]) == (
        "error",
        "setup: exit code 3",
        None,
        None,
    )
    executions = shop.executions(summary.run_id).values()
    assert sorted(e[0] for e in executions) == known
    assert {e[1:4] for e in executions} == {("blocked", None, "setup_failed")}


def test_model_credentials_do_not_reach_the_commands(shop, monkeypatch):
    sentinels = {
        "GEMINI_API_KEY": "sentinel-gemini",
        "OPENAI_API_KEY": "sentinel-openai",
        "TEAM_TOKEN": "sentinel-team",
    }
    for name, value in sentinels.items():
        monkeypatch.setenv(name, value)
    user_config = retro_home() / "config.yaml"
    user_config.write_text("models:\n  hosted:\n    provider: google\n    name: gemini\n    api_key_env: TEAM_TOKEN\n")

    def dump_environment(config):
        tests, service = config["tests"], config["service"]
        tests["setup"] = "env > {run_dir}/setup.env && " + tests["setup"]
        tests["command"] = "env > {run_dir}/command.env && " + tests["command"]
        tests["select"] = "env > {run_dir}/command.env && " + tests["select"]
        service["start"] = "env > {run_dir}/service.env && exec " + service["start"]
        tests["env"] = {"PROJECT_TOKEN": "kept"}

    try:
        with shop.config(dump_environment):
            summary = shop.run("base", "selected", ["TC-001"])
    finally:
        user_config.unlink()

    assert summary.status == "completed"
    evidence = shop.evidence(summary.run_id)
    for name in ("setup.env", "command.env", "service.env"):
        assert (evidence / name).is_file()
    for path in evidence.rglob("*"):
        if path.is_file():
            text = path.read_text(errors="replace")
            assert not [value for value in sentinels.values() if value in text], path
    command_env = (evidence / "command.env").read_text().splitlines()
    for line in ("PROJECT_TOKEN=kept", f"RETRO_RUN_ID={summary.run_id}", "RETRO_VERSION=base"):
        assert line in command_env
    assert any(line.startswith("RETRO_BASE_URL=http://127.0.0.1:") for line in command_env)


def test_without_approval_nothing_runs(shop):
    runs = shop.conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]
    evidence = sorted(path.name for path in (shop.path / ".retro" / "runs").iterdir())

    with pytest.raises(ToolError) as refused:
        shop.run("candidate", approved=False)

    assert refused.value.code == "denied"
    assert shop.conn.execute("SELECT COUNT(*) FROM run").fetchone()[0] == runs
    assert sorted(path.name for path in (shop.path / ".retro" / "runs").iterdir()) == evidence


def test_no_worktree_is_left_and_the_working_copy_is_unchanged(shop):
    root = worktrees_dir(shop.path)
    assert not root.exists() or not any(root.iterdir())
    assert git(shop.path, "worktree", "list", "--porcelain").count("worktree ") == 1
    changes = [line for line in git(shop.path, "status", "--porcelain").splitlines() if line[3:].strip()]
    assert [line for line in changes if not line[3:].startswith(".retro/")] == []
