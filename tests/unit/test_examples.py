import subprocess
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest

from retroagent import examples


def _rev(repo, ref):
    result = subprocess.run(["git", "rev-parse", ref], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def test_list_works_from_any_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    found = examples.list_examples()
    assert [(e.name, e.tags) for e in found] == [("shop-api", ("v1.0", "v1.1", "v1.2"))]


def test_unknown_example_is_refused(tmp_path):
    with pytest.raises(examples.UnknownExample):
        examples.materialize("nope", tmp_path / "demo")
    assert not (tmp_path / "demo").exists()


def test_existing_empty_directory_is_accepted(tmp_path):
    target = tmp_path / "demo"
    target.mkdir()
    assert examples.materialize("shop-api", target) == ("v1.0", "v1.1", "v1.2")


def test_non_empty_directory_is_refused_and_left_unchanged(tmp_path):
    target = tmp_path / "demo"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(examples.TargetNotEmpty):
        examples.materialize("shop-api", target)
    assert [p.name for p in target.iterdir()] == ["keep.txt"]


def test_a_file_as_target_is_refused(tmp_path):
    target = tmp_path / "file"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(examples.TargetNotEmpty):
        examples.materialize("shop-api", target)


def test_materialization_is_deterministic(tmp_path):
    examples.materialize("shop-api", tmp_path / "a")
    examples.materialize("shop-api", tmp_path / "b")
    for tag in ("v1.0", "v1.1", "v1.2"):
        assert _rev(tmp_path / "a", tag) == _rev(tmp_path / "b", tag)


def _snapshot_files(snapshot: Path) -> dict[str, bytes]:
    """The files of a bundled snapshot, as materialization copies them (no bytecode)."""
    return {
        path.relative_to(snapshot).as_posix(): path.read_bytes()
        for path in snapshot.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def _commit_files(repo: Path, tag: str) -> dict[str, bytes]:
    names = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--name-only", tag], cwd=repo, check=True, capture_output=True
    ).stdout
    return {
        name: subprocess.run(["git", "show", f"{tag}:{name}"], cwd=repo, check=True, capture_output=True).stdout
        for name in names.decode("utf-8").split("\0")
        if name
    }


def test_each_tag_holds_exactly_the_bytes_of_its_snapshot(tmp_path):
    """Content, not hashes, and independent of the filesystem: a file that git left out of a commit because it
    looked unchanged shows here by name."""
    examples.materialize("shop-api", tmp_path / "demo")
    root = files("retroagent.resources") / "examples" / "shop-api"
    manifest = tomllib.loads((root / "example.toml").read_text(encoding="utf-8"))
    for version in manifest["versions"]:
        expected = _snapshot_files(Path(str(root / "versions" / version["dir"])))
        actual = _commit_files(tmp_path / "demo", version["tag"])
        assert sorted(actual) == sorted(expected), f"{version['tag']}: files differ"
        wrong = [name for name in expected if actual[name] != expected[name]]
        assert not wrong, f"{version['tag']}: content differs in {wrong}"
