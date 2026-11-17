"""Helpers for the tests of the bundled servers through the real client: a session record created directly, as
ADR-0026 allows, the database as text, and the processes of the servers."""

import os
import subprocess
from pathlib import Path

from retroagent.memory import connect, sessions
from retroagent.runtime.session import resolve_commit
from retroagent.servers.errors import ToolError

RESULT_CHAR_LIMIT = 20_000


def git(repo, *args: str) -> str:
    return subprocess.run(
        ["git", "--no-optional-locks", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def open_session(path: Path, base: str | None = "v1.0", candidate: str | None = "v1.1", limit=RESULT_CHAR_LIMIT) -> int:
    """A running session on ``path`` with these versions, as the runtime would write it."""
    conn = connect(path)
    try:
        return sessions.start_session(
            conn,
            model="fake/model",
            interactive=False,
            result_char_limit=limit,
            base_ref=base,
            base_commit=resolve_commit(path, base) if base else None,
            candidate_ref=candidate,
            candidate_commit=resolve_commit(path, candidate) if candidate else None,
        )
    finally:
        conn.close()


def set_versions(path: Path, session_id: int, base: str | None, candidate: str | None) -> None:
    conn = connect(path)
    try:
        sessions.set_versions(
            conn,
            session_id,
            base_ref=base,
            base_commit=resolve_commit(path, base) if base else None,
            candidate_ref=candidate,
            candidate_commit=resolve_commit(path, candidate) if candidate else None,
        )
    finally:
        conn.close()


def dump(path: Path) -> list[str]:
    """Every row of project memory, as SQL."""
    conn = connect(path)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def error_of(call) -> ToolError:
    """The ToolError raised by ``call()``; fails when it returns."""
    try:
        value = call()
    except ToolError as error:
        return error
    raise AssertionError(f"no error: {value!r}")


def children(pattern: bytes) -> list[int]:
    """Processes started by this process whose command line contains ``pattern`` (Linux)."""
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            command = Path(f"/proc/{entry}/cmdline").read_bytes()
            parent = int(Path(f"/proc/{entry}/stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        if parent == os.getpid() and pattern in command:
            found.append(int(entry))
    return found


def environment_of(pid: int) -> dict[str, str]:
    raw = Path(f"/proc/{pid}/environ").read_bytes().decode(errors="replace")
    return dict(item.split("=", 1) for item in raw.split("\0") if "=" in item)


def group_alive(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
