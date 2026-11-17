"""The ``git`` server through a real server process and the real client, on shop-api: each tool, each error code
it can return, the working copy left alone, and paged output that joins back."""

import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fixtures.example_project import example_project
from fixtures.mcp_project import RESULT_CHAR_LIMIT, error_of, git, open_session
from fixtures.reference_scenario import CHANGE_SET

from retroagent.mcp_client import Client

V10 = "c7d45ada468e3746c498cb3417999e117154a942"
V11 = "46a5ef0910ce409a767f7549ed0c557106409321"


@pytest.fixture(scope="module")
def shop(tmp_path_factory, pip_cache):
    """shop-api, and one client per kind of session: created on first use, stopped at the end."""
    with example_project(tmp_path_factory, pip_cache) as path:
        clients: dict[tuple, Client] = {}

        def client(base="v1.0", candidate="v1.1", limit=RESULT_CHAR_LIMIT) -> Client:
            key = (base, candidate, limit)
            if key not in clients:
                clients[key] = Client(path, open_session(path, base, candidate, limit))
                clients[key].start()
            return clients[key]

        yield SimpleNamespace(path=path, client=client)
        for started in clients.values():
            started.stop()


def call(shop, tool, arguments=None, **session):
    return shop.client(**session).call("git", tool, arguments or {})


def code(shop, tool, arguments=None, **session) -> str:
    return error_of(lambda: call(shop, tool, arguments, **session)).code


# resolve_ref ---------------------------------------------------------------------------------------------------------


def test_resolve_ref_gives_the_commit_and_the_kind(shop):
    assert call(shop, "resolve_ref", {"ref": "v1.0"}) == {"ref": "v1.0", "commit": V10, "kind": "tag"}
    assert call(shop, "resolve_ref", {"ref": "main"})["kind"] == "branch"
    assert call(shop, "resolve_ref", {"ref": V11[:7]}) == {"ref": V11[:7], "commit": V11, "kind": "commit"}


def test_resolve_ref_errors(shop):
    assert code(shop, "resolve_ref", {"ref": "v9.9"}) == "not_found"
    assert code(shop, "resolve_ref", {"ref": "--all"}) == "not_found"
    assert code(shop, "resolve_ref", {}) == "invalid_argument"
    assert code(shop, "resolve_ref", {"ref": 11}) == "invalid_argument"


# analyze_changes -----------------------------------------------------------------------------------------------------


def test_analyze_changes_stores_the_change_set_of_the_fixture(shop):
    analysis = call(shop, "analyze_changes")
    assert analysis["base"] == "v1.0" and analysis["candidate"] == "v1.1"
    assert analysis["files"] == CHANGE_SET
    again = call(shop, "analyze_changes")
    assert again["analysis_id"] == analysis["analysis_id"] + 1  # a new analysis each time


def test_analyze_changes_needs_the_session_versions(shop):
    assert code(shop, "analyze_changes", candidate=None) == "invalid_state"
    assert code(shop, "analyze_changes", {"base": "v1.0"}) == "invalid_argument"


# get_diff ------------------------------------------------------------------------------------------------------------


def test_get_diff_of_a_file_of_the_change_set(shop):
    analysis_id = call(shop, "analyze_changes")["analysis_id"]
    result = call(shop, "get_diff", {"path": "src/shop/pricing.py"})
    assert result["analysis_id"] == analysis_id
    assert result["truncated"] is False
    assert result["diff"] == git(shop.path, "diff", "--no-ext-diff", V10, V11, "--", "src/shop/pricing.py")
    assert call(shop, "get_diff", {"path": "src/shop/pricing.py", "analysis_id": analysis_id}) == result


def test_get_diff_errors(shop):
    call(shop, "analyze_changes")
    assert code(shop, "get_diff", {"path": "src/shop/money.py"}) == "not_found"  # not in the change set
    assert code(shop, "get_diff", {"path": "src/shop/pricing.py", "analysis_id": 999}) == "not_found"
    assert code(shop, "get_diff", {"path": "src/shop/pricing.py"}, base="v1.1", candidate="v1.2") == "not_found"
    assert code(shop, "get_diff", {"path": "src/shop/pricing.py"}, candidate=None) == "invalid_state"
    assert code(shop, "get_diff", {"path": "src/shop/pricing.py", "start_line": 0}) == "invalid_argument"
    assert code(shop, "get_diff", {"path": "src/shop/pricing.py", "start_line": 10_000}) == "invalid_argument"


# read_file -----------------------------------------------------------------------------------------------------------


def test_read_file_at_each_version(shop):
    for version, commit in (("base", V10), ("candidate", V11)):
        result = call(shop, "read_file", {"path": "src/shop/pricing.py", "version": version})
        assert result["content"] == git(shop.path, "show", f"{commit}:src/shop/pricing.py")
        assert result["truncated"] is False


def test_read_file_errors(shop):
    assert code(shop, "read_file", {"path": "src/shop/nothing.py", "version": "base"}) == "not_found"
    assert code(shop, "read_file", {"path": "tests/test_history.py", "version": "base"}) == "not_found"
    assert code(shop, "read_file", {"path": "src/shop", "version": "base"}) == "not_found"  # a directory
    assert code(shop, "read_file", {"path": "../outside", "version": "base"}) == "not_found"
    assert code(shop, "read_file", {"path": "README.md", "version": "main"}) == "invalid_argument"
    assert code(shop, "read_file", {"path": "README.md", "version": "candidate"}, candidate=None) == "invalid_state"


# list_files ----------------------------------------------------------------------------------------------------------


def test_list_files_lists_the_direct_children(shop):
    root = call(shop, "list_files", {"version": "base"})
    assert root["path"] == "."
    assert "src/" in root["entries"] and "README.md" in root["entries"] and "docs/" in root["entries"]
    shop_dir = call(shop, "list_files", {"version": "candidate", "path": "src/shop/"})
    assert "pricing.py" in shop_dir["entries"]
    assert shop_dir["entries"] == sorted(git(shop.path, "ls-tree", "--name-only", f"{V11}:src/shop").split())


def test_list_files_errors(shop):
    assert code(shop, "list_files", {"version": "base", "path": "nowhere"}) == "not_found"
    assert code(shop, "list_files", {"version": "base", "path": "README.md"}) == "not_found"  # a file
    assert code(shop, "list_files", {"version": "both"}) == "invalid_argument"
    assert code(shop, "list_files", {"version": "base"}, base=None) == "invalid_state"


# Large output --------------------------------------------------------------------------------------------------------


def pages(shop, tool, arguments, limit):
    found, start = [], 1
    while True:
        result = call(shop, tool, {**arguments, "start_line": start}, limit=limit)
        found.append(result)
        if "next_line" not in result:
            return found
        assert result["truncated"] is True
        start = result["next_line"]


def test_a_file_over_the_result_limit_is_paged_and_its_pages_join_back(shop):
    original = git(shop.path, "show", f"{V11}:src/shop/pricing.py")
    assert len(original) > 3 * 400
    found = pages(shop, "read_file", {"path": "src/shop/pricing.py", "version": "candidate"}, 400)
    assert len(found) >= 3
    assert all(len(page["content"]) <= 400 for page in found)
    assert "".join(page["content"] for page in found) == original


def test_a_diff_over_the_result_limit_is_paged_and_its_pages_join_back(shop):
    shop.client(limit=400).call("git", "analyze_changes")
    original = git(shop.path, "diff", "--no-ext-diff", V10, V11, "--", "src/shop/discounts.py")
    found = pages(shop, "get_diff", {"path": "src/shop/discounts.py"}, 400)
    assert len(found) >= 2
    assert all(len(page["diff"]) <= 400 for page in found)
    assert "".join(page["diff"] for page in found) == original


# The working copy ----------------------------------------------------------------------------------------------------


def snapshot(path: Path) -> dict:
    files = {
        str(file.relative_to(path)): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(path.rglob("*"))
        if file.is_file() and ".git" not in file.relative_to(path).parts[:1] and not file.name.startswith("retro.db")
    }
    return {
        "status": git(path, "status", "--porcelain", "--ignored"),
        "files": files,
        "index": (path / ".git" / "index").read_bytes(),
        "refs": git(path, "show-ref"),
        "worktrees": git(path, "worktree", "list", "--porcelain"),
    }


def test_the_working_copy_and_git_status_are_unchanged(shop):
    shop.client()  # the session exists before the snapshot
    before = snapshot(shop.path)
    call(shop, "resolve_ref", {"ref": "v1.1"})
    call(shop, "analyze_changes")
    call(shop, "get_diff", {"path": "src/shop/cart.py"})
    call(shop, "read_file", {"path": "src/shop/cart.py", "version": "base"})
    call(shop, "list_files", {"version": "candidate", "path": "src"})
    assert snapshot(shop.path) == before


def test_binary_files_are_not_returned_as_text(tmp_path, monkeypatch):
    monkeypatch.setenv("RETRO_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *args: subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # noqa: E731
    run("init", "-q", "-b", "main")
    (repo / "image.bin").write_bytes(b"\x89PNG\0\0\x01binary")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-q", "-m", "one")
    run("tag", "one")
    with Client(repo, open_session(repo, "one", "one")) as client:
        result = client.call("git", "read_file", {"path": "image.bin", "version": "base"})
    assert result == {"path": "image.bin", "version": "base", "binary": True, "size": 13}
