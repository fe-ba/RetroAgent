"""Project commands: clean environment, process groups and timeouts (ADR-0024, NFR-16)."""

import os
import time
from pathlib import Path

from retroagent.config import load_config
from retroagent.servers.test_runner import process
from retroagent.servers.test_runner.process import WELL_KNOWN_KEYS, clean_environment


def alive(pid: int) -> bool:
    """True while the process exists and is not a zombie waiting to be reaped."""
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists():
        try:
            return stat.read_text().rpartition(")")[2].split()[0] != "Z"
        except (FileNotFoundError, ProcessLookupError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_dead(pid: int, seconds: float = 5) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_clean_environment_removes_credentials_and_adds_extra(monkeypatch):
    for name in WELL_KNOWN_KEYS:
        monkeypatch.setenv(name, "secret")
    monkeypatch.setenv("MY_MODEL_KEY", "secret")
    monkeypatch.setenv("KEEP_ME", "kept")
    env = clean_environment(["MY_MODEL_KEY"], {"RETRO_RUN_ID": "RUN-0001", "SHOP_DB": "memory"})
    assert not set(WELL_KNOWN_KEYS) & set(env)
    assert "MY_MODEL_KEY" not in env
    assert env["KEEP_ME"] == "kept"
    assert env["RETRO_RUN_ID"] == "RUN-0001" and env["SHOP_DB"] == "memory"
    assert os.environ["MY_MODEL_KEY"] == "secret"  # the environment of retro is not changed


def test_model_credentials_do_not_reach_a_command(tmp_path, monkeypatch):
    """The credential test at the process level: configuration, environment and a real command."""
    home, project = tmp_path / "home", tmp_path / "project"
    (project / ".retro").mkdir(parents=True)
    home.mkdir()
    monkeypatch.setenv("RETRO_HOME", str(home))
    (home / "config.yaml").write_text(
        "models:\n  hosted:\n    provider: google\n    name: gemini\n    api_key_env: TEAM_GEMINI_TOKEN\n"
    )
    (project / ".retro" / "config.yaml").write_text("tests:\n  env:\n    SHOP_MODE: test\n")
    monkeypatch.setenv("GEMINI_API_KEY", "sentinel-well-known-key")
    monkeypatch.setenv("TEAM_GEMINI_TOKEN", "sentinel-profile-key")
    config = load_config(project)

    env = clean_environment(config.credential_env_names, {**config["tests.env"], "RETRO_VERSION": "base"})
    log = tmp_path / "run.log"
    outcome = process.run("env > environment.txt", cwd=tmp_path, env=env, timeout=30, log=log)

    assert outcome.exit_code == 0
    seen = (tmp_path / "environment.txt").read_text()
    assert "sentinel" not in seen
    assert "GEMINI_API_KEY=" not in seen and "TEAM_GEMINI_TOKEN=" not in seen
    assert "SHOP_MODE=test" in seen and "RETRO_VERSION=base" in seen
    assert "sentinel" not in log.read_text()


def test_exit_code_output_and_times_go_to_the_log(tmp_path):
    log = tmp_path / "run.log"
    outcome = process.run("echo hello; echo oops >&2; exit 3", cwd=tmp_path, env=os.environ, timeout=30, log=log)
    assert outcome == process.Outcome(3, False, outcome.started_at, outcome.ended_at)
    assert outcome.started_at <= outcome.ended_at
    text = log.read_text()
    assert "$ echo hello; echo oops >&2; exit 3" in text
    assert "hello\noops\n" in text
    assert "exit code 3" in text


def test_commands_get_no_input(tmp_path):
    outcome = process.run("read answer", cwd=tmp_path, env=os.environ, timeout=5, log=tmp_path / "log")
    assert not outcome.timed_out and outcome.exit_code != 0


def test_timeout_terminates_the_whole_group(tmp_path):
    log = tmp_path / "run.log"
    command = "sleep 60 & echo $! > child.pid; sleep 60"
    started = time.monotonic()
    outcome = process.run(command, cwd=tmp_path, env=os.environ, timeout=1, log=log)
    assert outcome.timed_out and outcome.exit_code is None
    assert time.monotonic() - started < 10
    assert wait_dead(int((tmp_path / "child.pid").read_text()))
    assert "stopped after 1 seconds" in log.read_text()


def test_processes_left_by_a_finished_command_are_terminated(tmp_path):
    outcome = process.run(
        "sleep 60 & echo $! > child.pid", cwd=tmp_path, env=os.environ, timeout=30, log=tmp_path / "log"
    )
    assert outcome.exit_code == 0
    assert wait_dead(int((tmp_path / "child.pid").read_text()))


def test_start_and_terminate_a_long_running_command(tmp_path):
    started = process.start("sleep 60 & echo $! > child.pid; wait", cwd=tmp_path, env=os.environ, log=tmp_path / "l")
    deadline = time.monotonic() + 5
    while not (tmp_path / "child.pid").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    process.terminate(started)
    assert started.poll() is not None
    assert wait_dead(int((tmp_path / "child.pid").read_text()))
