"""Project commands: each one in its own process group, with a clean environment (ADR-0024).

The whole group is terminated on timeout, on interruption and when the command ends, so no process started
by a command outlives it. POSIX only: process groups are signalled with ``os.killpg``.
"""

import os
import signal
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from retroagent.memory.db import utc_now

# Removed from every subprocess, together with each ``api_key_env`` of the user configuration (NFR-16).
WELL_KNOWN_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")

GRACE_SECONDS = 5


def clean_environment(credential_names: Iterable[str], extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment of ``retro`` without model credentials, then ``extra`` (``tests.env``, ``RETRO_*``)."""
    env = dict(os.environ)
    for name in (*WELL_KNOWN_KEYS, *credential_names):
        env.pop(name, None)
    env.update(extra or {})
    return env


@dataclass(frozen=True)
class Outcome:
    exit_code: int | None
    timed_out: bool
    started_at: str
    ended_at: str


def run(command: str, *, cwd: str | Path, env: Mapping[str, str], timeout: float, log: str | Path) -> Outcome:
    """Run a shell command and wait for it, appending its output, its time and its exit code to ``log``.

    ``KeyboardInterrupt`` terminates the group and is raised again.
    """
    started_at = utc_now()
    _note(log, f"[{started_at}] $ {command}")
    process = _popen(command, cwd, env, log)
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    except BaseException:
        terminate(process)
        _note(log, f"[{utc_now()}] interrupted")
        raise
    terminate(process)
    ended_at = utc_now()
    if timed_out:
        _note(log, f"[{ended_at}] stopped after {timeout} seconds")
    else:
        _note(log, f"[{ended_at}] exit code {process.returncode}")
    return Outcome(None if timed_out else process.returncode, timed_out, started_at, ended_at)


def start(command: str, *, cwd: str | Path, env: Mapping[str, str], log: str | Path) -> subprocess.Popen:
    """Start a long-running command, such as a service. Stop it with ``terminate``."""
    _note(log, f"[{utc_now()}] $ {command}")
    return _popen(command, cwd, env, log)


def terminate(process: subprocess.Popen) -> None:
    """Terminate the process group of ``process``: SIGTERM, then SIGKILL after a grace period."""
    _signal_group(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    _signal_group(process.pid, signal.SIGKILL)
    process.wait()


def _popen(command: str, cwd: str | Path, env: Mapping[str, str], log: str | Path) -> subprocess.Popen:
    with open(log, "ab") as output:
        return subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # its own process group, out of reach of the terminal's Ctrl+C
        )


def _signal_group(group: int, signal_number: int) -> None:
    try:
        os.killpg(group, signal_number)
    except (ProcessLookupError, PermissionError):
        pass  # the group has already ended


def _note(log: str | Path, line: str) -> None:
    with open(log, "a", encoding="utf-8") as output:
        output.write(line + "\n")
