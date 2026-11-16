"""Fixtures of the integration tests."""

import pytest


@pytest.fixture(scope="session")
def pip_cache(tmp_path_factory):
    """A pip cache shared by every run of the pytest session.

    The setup of the example installs pytest with ``--cache-dir {cache_dir}/pip``, and ``{cache_dir}`` is new for
    each temporary project. Linking it here downloads the packages once per session; without the network, the
    tests that need it fail.
    """
    return tmp_path_factory.mktemp("pip-cache")
