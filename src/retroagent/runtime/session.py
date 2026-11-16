"""The session: Start and End of spec/runtime.md, without the model and the MCP servers.

Start, in order: resolve the project, load the configuration, take the lock, open memory and create the session
record, recover from an interrupted session, and resolve the session versions. Steps 7 and 9 to 13 (model,
approvals of project extensions, MCP servers, probe, context budget) belong to later slices. End removes leftover
worktrees, sets ``ended_at`` and releases the lock.
"""

import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from retroagent.config import Config, ConfigError, load_config
from retroagent.memory import SchemaTooNew, connect, execution, sessions
from retroagent.runtime import lock
from retroagent.servers.test_runner import worktree

# Slice 1 has no model. The session record needs one; slice 3 writes "<provider>/<model name>" (Start step 7).
MODEL_PLACEHOLDER = "none"
# The result limit of mcp-tools.md (Large output) before the context window of a model is known.
RESULT_CHAR_LIMIT = 20_000

ROLES = ("base", "candidate")


class SessionError(Exception):
    """The session cannot start: invalid usage, invalid configuration, the lock is held. Exit code 2."""


class UnknownRef(Exception):
    """A ref does not resolve to a commit of the project."""

    def __init__(self, ref: str):
        self.ref = ref
        super().__init__(f"{ref!r} is not a tag, branch or commit of the project")


@dataclass(frozen=True)
class Options:
    """What the command line says about the session."""

    project: str | Path | None = None  # -C; the current directory when None
    interactive: bool = True
    trust_commands: bool = False
    base: str | None = None
    candidate: str | None = None


@dataclass(frozen=True)
class Version:
    ref: str
    commit: str


class Session:
    def __init__(self, project_dir: Path, config: Config, options: Options, held: lock.Lock):
        self.project_dir, self.config = project_dir, config
        self.interactive, self.trust_commands = options.interactive, options.trust_commands
        self._lock = held
        self.conn: sqlite3.Connection | None = None
        self.id: int | None = None
        self.recovered_runs: list[str] = []

    def versions(self) -> dict[str, Version | None]:
        """The session versions, as written in the session record."""
        row = sessions.get_session(self.conn, self.id)
        return {
            role: Version(row[f"{role}_ref"], row[f"{role}_commit"]) if row[f"{role}_ref"] is not None else None
            for role in ROLES
        }

    def end(self) -> None:
        """End steps 2 to 4. Safe to call more than once and after a partial start."""
        try:
            worktree.remove_leftovers(self.project_dir)
            if self.conn is not None:
                if self.id is not None:
                    sessions.end_session(self.conn, self.id)
                self.conn.close()
                self.conn = None
        finally:
            self._lock.release()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc) -> None:
        self.end()


def start(options: Options) -> Session:
    """Start a session. Raises ``SessionError`` for every condition of exit code 2."""
    project_dir = project_top_level(Path(options.project) if options.project is not None else Path.cwd())
    (project_dir / ".retro").mkdir(exist_ok=True)
    try:
        config = load_config(project_dir)
    except ConfigError as error:
        raise SessionError(str(error)) from error
    try:
        held = lock.acquire(project_dir / ".retro" / "retro.lock")
    except lock.LockHeld as error:
        raise SessionError(str(error)) from error
    # Nothing of project memory is read or written before the lock is held.
    session = Session(project_dir, config, options, held)
    try:
        try:
            session.conn = connect(project_dir)
        except SchemaTooNew as error:
            raise SessionError(str(error)) from error
        session.id = sessions.start_session(
            session.conn,
            model=MODEL_PLACEHOLDER,
            interactive=options.interactive,
            result_char_limit=RESULT_CHAR_LIMIT,
        )
        session.recovered_runs = recover(session.conn, project_dir, session.id)
        refs = {
            "base": options.base or config["versions.base"],
            "candidate": options.candidate or config["versions.candidate"],
        }
        try:
            set_versions(session.conn, session.id, project_dir, **refs)
        except UnknownRef as error:
            raise SessionError(str(error)) from error
    except BaseException:
        session.end()
        raise
    return session


def project_top_level(path: Path) -> Path:
    """Start step 2: the target project must be the top level of a git repository."""
    path = path.resolve()
    if not path.is_dir():
        raise SessionError(f"{path} is not a directory")
    result = _git(path, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise SessionError(f"{path} is not a git repository")
    top = Path(result.stdout.strip()).resolve()
    if top != path:
        raise SessionError(f"{path} is not the top level of its git repository; use {top}")
    return path


def recover(conn: sqlite3.Connection, project_dir: Path, session_id: int) -> list[str]:
    """Start step 6: runs left ``running`` become ``interrupted``; leftover worktrees are removed."""
    interrupted = []
    for run in execution.running_runs(conn):
        message = f"session: the session that started the run ended before it; recovered by session {session_id}"
        execution.finish_run(conn, run["id"], status="interrupted", error=message)
        interrupted.append(run["id"])
    worktree.remove_leftovers(project_dir)
    return interrupted


def set_versions(
    conn: sqlite3.Connection, session_id: int, project_dir: Path, *, base: str | None, candidate: str | None
) -> dict[str, Version | None]:
    """Resolve each ref to its commit and write both to the session record. A ref left None stays unset.

    Every ref is resolved before anything is written: an ``UnknownRef`` leaves the record unchanged.
    """
    versions = {
        role: Version(ref, resolve_commit(project_dir, ref)) if ref is not None else None
        for role, ref in (("base", base), ("candidate", candidate))
    }
    sessions.set_versions(
        conn,
        session_id,
        base_ref=versions["base"].ref if versions["base"] else None,
        base_commit=versions["base"].commit if versions["base"] else None,
        candidate_ref=versions["candidate"].ref if versions["candidate"] else None,
        candidate_commit=versions["candidate"].commit if versions["candidate"] else None,
    )
    return versions


def resolve_commit(project_dir: Path, ref: str) -> str:
    """The full commit hash of a tag, a branch or a commit. Raises ``UnknownRef``."""
    if not ref:
        raise UnknownRef(ref)
    result = _git(project_dir, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}")
    if result.returncode != 0:
        raise UnknownRef(ref)
    return result.stdout.strip()


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False
    )
