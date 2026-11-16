"""Fixtures of the integration tests."""

from dataclasses import dataclass
from pathlib import Path

import pytest
from fixtures.example_project import example_project, start

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
        with start(path, trust_commands=True) as started:
            outcome = commands.run(started, "all", "both")
    return BothRuns(path, outcome)
