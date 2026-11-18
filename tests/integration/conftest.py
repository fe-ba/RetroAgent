"""Fixtures of the integration tests."""

import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from fixtures.agent_session import Scripted, analyze_script, design_script, select_script
from fixtures.example_project import example_project, project_copy, start
from fixtures.reference_scenario import ReferenceScenario, load_reference_scenario
from fixtures.report_session import open_project

from retroagent.memory import connect
from retroagent.runtime import commands
from retroagent.runtime.commands import RunOutcome


@pytest.fixture(scope="session")
def pip_cache(tmp_path_factory):
    """A pip cache shared by every run of the pytest session.

    The setup of the example installs pytest with ``--cache-dir {cache_dir}/pip``, and ``{cache_dir}`` is new for
    each temporary project. Linking it here downloads the packages once per session; without the network, the
    tests that need it fail.
    """
    return tmp_path_factory.mktemp("pip-cache")


@dataclass(frozen=True)
class BothRuns:
    path: Path
    outcome: RunOutcome


@pytest.fixture(scope="session")
def shop_after_both_runs(tmp_path_factory, pip_cache) -> BothRuns:
    """An example project after ``/run all --on both`` with v1.0 and v1.1: RUN-0001 and RUN-0002.

    For tests that only read its memory and evidence; a test that changes the project needs its own copy.
    """
    with example_project(tmp_path_factory, pip_cache) as path:
        with start(path, trust_commands=True, mode="auto") as started:
            outcome = commands.run(started, "all", "both")
    return BothRuns(path, outcome)


@pytest.fixture(scope="session")
def shop_after_design(tmp_path_factory, pip_cache, shop_after_both_runs) -> Path:
    """An example project after ``/run all --on both``, ``/analyze``, ``/select`` and ``/design``, with the
    reference scripts: its current suite has one ``designed`` test case, for REQ-002 (``fixtures.agent_session``).

    For tests that copy it with ``project_copy``; nobody changes it.
    """
    with project_copy(tmp_path_factory, shop_after_both_runs.path) as path:
        script = Scripted([*analyze_script(), *select_script(), *design_script()])
        with start(path, script, trust_commands=True) as session:
            commands.analyze(session)
            commands.select(session)
            commands.design_tests(session)
        assert script.remaining == 0
    return path


@pytest.fixture
def local_time(monkeypatch):
    """The local time zone is UTC-5 (POSIX ``EST5``): the reports of these tests do not depend on the machine."""
    monkeypatch.setenv("TZ", "EST5")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def reference(tmp_path, local_time, monkeypatch):
    """The records of the reference scenario, cycle 1, in a temporary project, and the session that reports on it.

    The user level is an empty temporary directory: the configuration of the person running the tests never applies.
    """
    monkeypatch.setenv("RETRO_HOME", str(tmp_path / "retro-home"))
    project = open_project(tmp_path / "project")
    scenario = load_reference_scenario(project.conn)
    yield project.with_id(scenario.session_id), scenario
    project.conn.close()


@pytest.fixture(scope="module")
def agent_project(tmp_path_factory, pip_cache):
    """An example project shared by the tests of one module; each test starts its own session on it."""
    with example_project(tmp_path_factory, pip_cache) as path:
        yield path


@pytest.fixture
def agent(agent_project):
    """A non-interactive session on the shared example project, in mode default, with the project commands trusted
    and the real bundled servers. Its provider is an empty FakeProvider: tests pass their own to the turn."""
    with start(agent_project, trust_commands=True) as session:
        yield session


@pytest.fixture
def fake_model(monkeypatch):
    """Every session started by ``main`` gets the provider given to this fixture instead of LiteLLM."""
    from retroagent.runtime import session as session_module

    def use(provider):
        monkeypatch.setattr(session_module, "_make_provider", lambda profile, session, factory: provider)
        return provider

    return use


@pytest.fixture(scope="module")
def pristine_example(tmp_path_factory, pip_cache):
    """An example project that nobody changes, for tests that copy it."""
    with example_project(tmp_path_factory, pip_cache) as path:
        yield path


@dataclass(frozen=True)
class ReferenceProject:
    path: Path
    scenario: ReferenceScenario


@contextmanager
def _reference_copy(tmp_path_factory, source: Path, triage: bool):
    with project_copy(tmp_path_factory, source) as path:
        conn = connect(path)
        try:
            scenario = load_reference_scenario(conn, triage=triage)
        finally:
            conn.close()
        yield ReferenceProject(path, scenario)


@pytest.fixture
def reference_project(tmp_path_factory, pristine_example) -> ReferenceProject:
    """A copy of the example project, with its git repository, holding the records of the reference scenario, cycle
    1, without triage and without DEF-001: the failures of RUN-0004 wait for triage. The session of the scenario has
    the versions v1.0 and v1.1 at their real commits, so the git check of ``expected_change`` runs."""
    with _reference_copy(tmp_path_factory, pristine_example, triage=False) as project:
        yield project


@pytest.fixture
def triaged_reference_project(tmp_path_factory, pristine_example, local_time) -> ReferenceProject:
    """The same, with the whole of cycle 1: triage and DEF-001. Ready for the completion report, in the local time
    zone of the expected report (UTC-5), which the bundled servers inherit."""
    with _reference_copy(tmp_path_factory, pristine_example, triage=True) as project:
        yield project
