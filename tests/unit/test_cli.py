import shutil
import subprocess
import sys

import pytest

from retroagent import __version__
from retroagent.cli.main import main


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


@pytest.mark.parametrize("argv", [[], ["bogus"], ["example"], ["example", "list", "extra"], ["example", "shop-api"]])
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
