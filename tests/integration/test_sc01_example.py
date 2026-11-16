"""SC-01: create the example."""

import subprocess

from retroagent.cli.main import main

TAGS = {
    "v1.0": "c7d45ada468e3746c498cb3417999e117154a942",
    "v1.1": "46a5ef0910ce409a767f7549ed0c557106409321",
    "v1.2": "9936dccd1584a9226feabe90acf9dd8ab1c62e59",
}


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def test_sc01_create_the_example(tmp_path, capsys):
    project = tmp_path / "demo"

    assert main(["example", "list"]) == 0
    assert "shop-api" in capsys.readouterr().out

    assert main(["example", "shop-api", str(project)]) == 0

    for tag, commit in TAGS.items():
        assert _git(project, "rev-parse", f"{tag}^{{commit}}") == commit
    assert _git(project, "branch", "--show-current") == "main"
    assert len(_git(project, "rev-list", "--all").splitlines()) == 3
    assert _git(project, "status", "--porcelain") == ""

    assert not [p for p in project.rglob("*") if ".git" not in p.parts and p.name in ("ORACLE.md", "expected")]

    head, tags = _git(project, "rev-parse", "HEAD"), _git(project, "tag", "--list")
    capsys.readouterr()
    assert main(["example", "shop-api", str(project)]) == 2
    assert "must not exist or must be empty" in capsys.readouterr().err
    assert (_git(project, "rev-parse", "HEAD"), _git(project, "tag", "--list")) == (head, tags)
