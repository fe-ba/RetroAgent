import shutil
import subprocess
import sys

import pytest
from fixtures.agent_session import write_user_config

from retroagent import __version__
from retroagent.cli.main import main


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """A bare `retro` starts a session on the current directory: never let it be this repository."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RETRO_HOME", str(tmp_path / "home"))
    write_user_config(tmp_path / "home")


def git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "project"
    (path / "src").mkdir(parents=True)
    git(path, "init", "--quiet", "--initial-branch=main")
    (path / "src" / "app.py").write_text("x = 1\n")
    git(path, "add", ".")
    git(path, "commit", "--quiet", "-m", "one")
    git(path, "tag", "v1")
    return path


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"retro {__version__}"
    assert __version__ == "0.1.0"


def test_help_lists_only_what_exists(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "example" in out
    for missing in ("init", "config", "defects"):
        assert missing not in out


@pytest.mark.parametrize(
    "argv",
    [
        ["example"],
        ["example", "list", "extra"],
        ["example", "shop-api"],
        ["-p"],
        ["-p", "hello"],
        ["-p", "/help"],
        ["-p", "/analyze v1.0 v1.1"],
        ["-p", "/run all --on nowhere"],
        ["-p", "/history 0"],
        ["--mode", "nowhere", "-p", "/status"],
    ],
)
def test_invalid_usage_exits_2(argv):
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2


def test_example_list(capsys):
    assert main(["example", "list"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("shop-api:")
    assert "Versions: v1.0, v1.1, v1.2." in out


def test_unknown_example_exits_2(tmp_path, capsys):
    assert main(["example", "nope", str(tmp_path / "demo")]) == 2
    assert "unknown example: nope" in capsys.readouterr().err


def test_non_empty_directory_exits_2(tmp_path, capsys):
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    assert main(["example", "shop-api", str(tmp_path)]) == 2
    assert "must not exist or must be empty" in capsys.readouterr().err


def test_installed_entry_point_prints_version():
    retro = shutil.which("retro", path=str(__import__("pathlib").Path(sys.executable).parent))
    assert retro, "the `retro` entry point is not installed next to the interpreter"
    result = subprocess.run([retro, "--version"], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "retro 0.1.0"


def test_help_lists_the_session_options(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for option in ("-C", "--print", "--trust-commands", "--base", "--candidate", "--version"):
        assert option in out


def test_a_directory_that_is_not_a_repository_exits_2(tmp_path, capsys):
    assert main(["-C", str(tmp_path), "-p", "/status"]) == 2
    assert "is not a git repository" in capsys.readouterr().err
    assert not (tmp_path / ".retro").exists()


def test_a_subdirectory_of_a_repository_exits_2_and_names_the_top_level(repo, capsys):
    assert main(["-C", str(repo / "src"), "-p", "/status"]) == 2
    err = capsys.readouterr().err
    assert "is not the top level of its git repository" in err
    assert str(repo) in err


def test_an_invalid_configuration_exits_2(repo, capsys):
    (repo / ".retro").mkdir()
    (repo / ".retro" / "config.yaml").write_text("tests:\n  reruns: -1\n")
    assert main(["-C", str(repo), "-p", "/status"]) == 2
    assert "tests.reruns" in capsys.readouterr().err


def test_a_ref_that_does_not_resolve_exits_2(repo, capsys):
    assert main(["-C", str(repo), "--base", "v9", "-p", "/status"]) == 2
    assert "'v9' is not a tag, branch or commit" in capsys.readouterr().err


def test_a_direct_command_in_non_interactive_mode(repo, capsys):
    assert main(["-C", str(repo), "--base", "v1", "-p", "/status"]) == 0
    out = capsys.readouterr().out
    assert "v1 (" in out and "Model calls" in out
    assert main(["-C", str(repo), "-p", "/history"]) == 0


def test_run_without_trusted_commands_exits_4(repo, capsys):
    assert main(["-C", str(repo), "--candidate", "v1", "-p", "/run all"]) == 4
    assert "denied" in capsys.readouterr().err


def test_run_without_the_version_it_needs_exits_1(repo, capsys):
    (repo / ".retro").mkdir()
    (repo / ".retro" / "config.yaml").write_text("tests:\n  command: pytest --junitxml={junit}\n")
    assert main(["-C", str(repo), "--trust-commands", "-p", "/run all"]) == 1
    err = capsys.readouterr().err
    assert "invalid_state: the candidate version of the session is not set" in err
