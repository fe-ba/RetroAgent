"""SC-02: initialize a project. ``RETRO.md`` and ``.retro/`` are removed from the example and committed; ``retro
init`` detects pytest and creates the three files, and nothing else of the working copy changes. ``retro --help``
lists every command and option of cli.md."""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

from retroagent.cli.main import main
from retroagent.examples import materialize

CLI_MD = Path(__file__).parents[2] / "docs" / "reference" / "cli.md"


def git(repo, *args) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def shop(tmp_path, monkeypatch):
    monkeypatch.setenv("RETRO_HOME", str(tmp_path / "home"))
    path = tmp_path / "shop-api"
    materialize("shop-api", path)
    git(path, "rm", "-r", "--quiet", "RETRO.md", ".retro")
    git(path, "commit", "--quiet", "-m", "Remove the RetroAgent files")
    assert git(path, "status", "--porcelain", "--untracked-files=all") == ""
    return path


def test_init_detects_pytest_and_creates_only_the_three_files(shop, capsys):
    assert main(["-C", str(shop), "init"]) == 0
    out = capsys.readouterr().out
    assert "Tests: pytest --junitxml={junit} (from pyproject.toml)" in out
    assert "Created: RETRO.md, .retro/config.yaml, .retro/.gitignore." in out
    status = git(shop, "status", "--porcelain", "--untracked-files=all").splitlines()
    assert sorted(status) == ["?? .retro/.gitignore", "?? .retro/config.yaml", "?? RETRO.md"]

    config = yaml.safe_load((shop / ".retro" / "config.yaml").read_text())
    assert config == {
        "project": {"name": "shop-api", "requirements": ["docs/requirements.md"]},
        "versions": {"base": "v1.1", "candidate": "v1.2"},
        "tests": {"command": "pytest --junitxml={junit}", "junit": "{junit}"},
    }
    assert (shop / ".retro" / ".gitignore").read_text() == "retro.db\nretro.db-*\nretro.lock\nruns/\n"
    retro_md = (shop / "RETRO.md").read_text()
    for section in ("## Overview", "## Modules", "## Running", "## Test conventions", "## Known issues"):
        assert section in retro_md
    assert "`pytest --junitxml={junit}`" in retro_md


def test_init_never_overwrites_a_file(shop, capsys):
    assert main(["init", "-C", str(shop)]) == 0
    before = {name: (shop / name).read_bytes() for name in ("RETRO.md", ".retro/config.yaml", ".retro/.gitignore")}
    (shop / "RETRO.md").write_text("Edited by the user.\n")
    before["RETRO.md"] = b"Edited by the user.\n"
    assert main(["-C", str(shop), "init"]) == 0
    assert "Nothing to create" in capsys.readouterr().out
    assert {name: (shop / name).read_bytes() for name in before} == before


def test_init_needs_the_top_level_of_a_repository(shop, tmp_path, capsys):
    assert main(["-C", str(shop / "src"), "init"]) == 2
    assert "is not the top level of its git repository" in capsys.readouterr().err
    outside = tmp_path / "outside"
    outside.mkdir()
    assert main(["-C", str(outside), "init"]) == 2
    assert "is not a git repository" in capsys.readouterr().err
    assert not (shop / "src" / "RETRO.md").exists() and list(outside.iterdir()) == []


def table_cells(section: str) -> list[str]:
    text = CLI_MD.read_text()
    body = text.split(f"## {section}\n", 1)[1].split("\n## ", 1)[0]
    return [line.split("|")[1].strip().strip("`") for line in body.splitlines() if re.match(r"\| `", line)]


def test_help_lists_every_command_and_option_of_cli_md(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    options = [flag.split()[0] for cell in table_cells("Global options") for flag in cell.replace("`", "").split(", ")]
    assert len(options) == 16
    for option in options:
        assert re.search(rf"(^|[\s,]){re.escape(option)}([\s,]|$)", help_text, re.MULTILINE), option
    commands = [cell.removeprefix("retro ") for cell in table_cells("Commands")]
    assert len(commands) == 7
    for command in commands:
        assert command in help_text, command
