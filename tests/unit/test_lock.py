"""The session lock is an operating-system lock, never the existence of the file (runtime.md, Start step 4)."""

import os

import pytest

from retroagent.runtime import lock


def test_the_holder_writes_its_process_id(tmp_path):
    held = lock.acquire(tmp_path / "retro.lock")
    try:
        assert (tmp_path / "retro.lock").read_text() == f"{os.getpid()}\n"
    finally:
        held.release()


def test_a_held_lock_is_refused_and_names_the_holder(tmp_path):
    held = lock.acquire(tmp_path / "retro.lock")
    try:
        with pytest.raises(lock.LockHeld) as refused:
            lock.acquire(tmp_path / "retro.lock")  # another open file: refused like another process
        assert refused.value.pid == os.getpid()
        assert f"process {os.getpid()}" in str(refused.value)
    finally:
        held.release()


def test_a_lock_file_without_a_holder_is_taken_over(tmp_path):
    (tmp_path / "retro.lock").write_text("999999999\n")
    held = lock.acquire(tmp_path / "retro.lock")
    try:
        assert (tmp_path / "retro.lock").read_text() == f"{os.getpid()}\n"
    finally:
        held.release()


def test_release_keeps_the_file_and_frees_the_lock(tmp_path):
    lock.acquire(tmp_path / "retro.lock").release()
    assert (tmp_path / "retro.lock").is_file()
    again = lock.acquire(tmp_path / "retro.lock")
    again.release()
    again.release()  # a second release does nothing
