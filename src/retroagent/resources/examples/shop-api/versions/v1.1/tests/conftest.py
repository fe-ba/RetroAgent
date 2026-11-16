import os
import threading

import pytest

from shop.api import make_server
from shop.store import Store


@pytest.fixture
def store():
    return Store()


@pytest.fixture
def cart(store):
    return store.create_cart()


@pytest.fixture(scope="session")
def base_url():
    """URL of a running shop API.

    Uses the service at RETRO_BASE_URL when it is set; otherwise starts one for the test session.
    """
    url = os.environ.get("RETRO_BASE_URL")
    if url:
        yield url.rstrip("/")
        return
    server = make_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
