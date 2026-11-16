import subprocess

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
