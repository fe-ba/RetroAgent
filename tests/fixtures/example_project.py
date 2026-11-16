"""An example project for integration tests, and a session on it."""

from contextlib import contextmanager
from pathlib import Path

import pytest

from retroagent.config import cache_dir
from retroagent.examples import materialize
from retroagent.runtime import session
from retroagent.servers.test_runner import process


@contextmanager
def example_project(tmp_path_factory, pip_cache):
    """``retro example shop-api`` in a new temporary directory, with its own ``RETRO_HOME`` and no model key in the
    environment while the block runs."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("RETRO_HOME", str(tmp_path_factory.mktemp("retro-home")))
        for name in process.WELL_KNOWN_KEYS:  # a real key never reaches a command or a log of these tests
            patch.delenv(name, raising=False)
        path = tmp_path_factory.mktemp("work") / "shop-api-demo"
        materialize("shop-api", path)
        cache = cache_dir(path)
        cache.mkdir(parents=True)
        (cache / "pip").symlink_to(pip_cache, target_is_directory=True)
        yield path


def start(path: Path, **options) -> session.Session:
    """A non-interactive session on ``path``; the versions come from the example's configuration."""
    return session.start(session.Options(project=path, interactive=False, **options))
