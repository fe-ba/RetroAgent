"""The service of the target project: free port, readiness below 500, stop (project-contract.md)."""

import os
import shlex
import socket
import sys
import time

import pytest

from retroagent.config import expand
from retroagent.servers.test_runner import service

SERVER = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port, status = int(sys.argv[1]), int(sys.argv[2])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" and status == 200 else status)
        self.end_headers()

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""


@pytest.fixture
def start_server(tmp_path):
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    started = []

    def start(status: int):
        port = service.free_port()
        command = expand(f"{shlex.quote(sys.executable)} server.py {{port}} {status}", {"port": port})
        process = service.start(command, cwd=tmp_path, env=os.environ, log=tmp_path / "service.log")
        started.append(process)
        return process, service.ready_url(expand("http://127.0.0.1:{port}", {"port": port}), "/health")

    yield start
    for process in started:
        service.stop(process)


def test_free_port_can_be_bound():
    port = service.free_port()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_ready_url_joins_base_and_path():
    assert service.ready_url("http://127.0.0.1:8000/", "/health") == "http://127.0.0.1:8000/health"
    assert service.ready_url("http://127.0.0.1:8000/api", "health") == "http://127.0.0.1:8000/api/health"
    assert service.ready_url("http://127.0.0.1:8000", "/") == "http://127.0.0.1:8000/"


@pytest.mark.parametrize("status", [200, 404])
def test_any_status_below_500_means_ready(start_server, status):
    process, url = start_server(status)
    assert service.wait_ready(url, timeout=10, service=process)


def test_a_server_error_is_not_ready(start_server):
    process, url = start_server(503)
    started = time.monotonic()
    assert not service.wait_ready(url, timeout=1, service=process)
    assert time.monotonic() - started >= 1


def test_nothing_listening_is_not_ready(tmp_path):
    process = service.start("sleep 30", cwd=tmp_path, env=os.environ, log=tmp_path / "service.log")
    try:
        assert not service.wait_ready(f"http://127.0.0.1:{service.free_port()}/", timeout=1, service=process)
    finally:
        service.stop(process)


def test_a_service_that_exits_is_not_ready_without_waiting(tmp_path):
    process = service.start("exit 1", cwd=tmp_path, env=os.environ, log=tmp_path / "service.log")
    started = time.monotonic()
    assert not service.wait_ready(f"http://127.0.0.1:{service.free_port()}/", timeout=10, service=process)
    assert time.monotonic() - started < 5


def test_stop_ends_the_service_and_frees_the_port(start_server):
    process, url = start_server(200)
    assert service.wait_ready(url, timeout=10, service=process)
    service.stop(process)
    assert process.poll() is not None
    assert not service.wait_ready(url, timeout=0.5)
