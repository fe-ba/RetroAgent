"""An example project for integration tests, and a session on it."""

from contextlib import contextmanager
from pathlib import Path

import pytest

from fixtures.agent_session import factory, write_user_config
from retroagent.config import cache_dir
from retroagent.examples import materialize
from retroagent.runtime import session
from retroagent.servers.test_runner import process


@contextmanager
def example_project(tmp_path_factory, pip_cache):
    """``retro example shop-api`` in a new temporary directory, with its own ``RETRO_HOME``, which holds the local
    model profile of the tests, and no model key in the environment while the block runs."""
    with pytest.MonkeyPatch.context() as patch:
        home = tmp_path_factory.mktemp("retro-home")
        write_user_config(home)
        patch.setenv("RETRO_HOME", str(home))
        for name in process.WELL_KNOWN_KEYS:  # a real key never reaches a command or a log of these tests
            patch.delenv(name, raising=False)
        path = tmp_path_factory.mktemp("work") / "shop-api-demo"
        materialize("shop-api", path)
        cache = cache_dir(path)
        cache.mkdir(parents=True)
        (cache / "pip").symlink_to(pip_cache, target_is_directory=True)
        yield path


def start(path: Path, provider=None, **options) -> session.Session:
    """A non-interactive session on ``path``, whose model is ``provider`` or an empty ``FakeProvider``; the versions
    come from the example's configuration."""
    return session.start(
        session.Options(project=path, interactive=False, **options), provider_factory=factory(provider)
    )
