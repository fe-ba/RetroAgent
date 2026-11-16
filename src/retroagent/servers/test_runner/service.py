"""The service of the target project: a free port, start, readiness and stop (project-contract.md, step 4)."""

import socket
import subprocess
import time
import urllib.error
import urllib.request

from retroagent.servers.test_runner import process

POLL_SECONDS = 0.2

# Readiness is checked on the local machine: proxies configured in the environment are not used.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def ready_url(base_url: str, ready_path: str) -> str:
    return base_url.rstrip("/") + "/" + ready_path.lstrip("/")


start = process.start
stop = process.terminate


def wait_ready(url: str, *, timeout: float, service: subprocess.Popen | None = None) -> bool:
    """Poll ``url`` until it answers with a status below 500, for at most ``timeout`` seconds.

    False at the deadline, or as soon as the service process has ended.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service is not None and service.poll() is not None:
            return False
        try:
            with _opener.open(url, timeout=max(0.1, min(2.0, deadline - time.monotonic()))) as response:
                if response.status < 500:
                    return True
        except urllib.error.HTTPError as error:
            if error.code < 500:
                return True
        except (OSError, ValueError):
            pass  # not listening yet
        time.sleep(POLL_SECONDS)
    return False
