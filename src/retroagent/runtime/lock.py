"""The session lock: an operating-system file lock on ``.retro/retro.lock`` (runtime.md, Start step 4).

The lock is held by an open file, never by the existence of the file: the operating system releases it when the
process ends, however it ends, so a file left by a crashed session is simply taken over. The holder writes its
process ID at the start of the file so that a second session can name it. This is the only platform-specific
module of the runtime.
"""

import os
import sys
from pathlib import Path

# Windows locks a byte range, and a locked range cannot be read by another process. The locked byte is far from the
# process ID at the start of the file, so the two never overlap.
_WINDOWS_LOCKED_BYTE = 1 << 20

if sys.platform == "win32":
    import msvcrt

    def _lock(fd: int) -> None:
        os.lseek(fd, _WINDOWS_LOCKED_BYTE, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, _WINDOWS_LOCKED_BYTE, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class LockHeld(Exception):
    """Another running session holds the lock. ``pid`` is its process, or None when it could not be read."""

    def __init__(self, path: Path, pid: int | None):
        self.path, self.pid = path, pid
        holder = f"process {pid}" if pid is not None else "a process that could not be identified"
        super().__init__(f"another session holds the lock {path}: {holder}")


class Lock:
    def __init__(self, path: Path, fd: int):
        self.path, self._fd = path, fd

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            _unlock(self._fd)
        finally:
            os.close(self._fd)
            self._fd = None


def acquire(path: str | Path) -> Lock:
    """Take the lock without waiting. Raises ``LockHeld``."""
    path = Path(path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    try:
        _lock(fd)
    except OSError:
        pid = _read_pid(fd)
        os.close(fd)
        raise LockHeld(path, pid) from None
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
    except BaseException:
        Lock(path, fd).release()
        raise
    return Lock(path, fd)


def _read_pid(fd: int) -> int | None:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        text = os.read(fd, 32).decode("ascii").strip()
        return int(text) if text.isdigit() else None
    except (OSError, UnicodeDecodeError):
        return None
