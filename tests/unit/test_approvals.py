"""The approval of the project commands (configuration.md, Project commands): its digest covers exactly the five
values, it is stored at user level for the path of the project, and a file that cannot be read is never
overwritten."""

import json

import pytest

from retroagent.config import approvals, load_config

COMMANDS = """\
tests:
  setup: python -m venv .venv
  command: .venv/bin/pytest --junitxml={junit}
  select: .venv/bin/pytest --junitxml={junit} -k "{names}"
  env:
    SHOP_MODE: test
service:
  start: .venv/bin/uvicorn app:app --port {port}
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    monkeypatch.setenv("RETRO_HOME", str(path))
    return path


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "shop"
    (path / ".retro").mkdir(parents=True)
    return path


def configured(project, text=COMMANDS):
    (project / ".retro" / "config.yaml").write_text(text, encoding="utf-8")
    return load_config(project)


def test_the_digest_is_stable_and_covers_the_five_values(home, project):
    config = configured(project)
    assert approvals.project_commands(config) == {
        "tests.setup": "python -m venv .venv",
        "tests.command": ".venv/bin/pytest --junitxml={junit}",
        "tests.select": '.venv/bin/pytest --junitxml={junit} -k "{names}"',
        "service.start": ".venv/bin/uvicorn app:app --port {port}",
        "tests.env": {"SHOP_MODE": "test"},
    }
    assert approvals.digest(config) == approvals.digest(configured(project))
    assert len(approvals.digest(config)) == 64


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("setup: python -m venv .venv", "setup: python3 -m venv .venv"),
        ("command: .venv/bin/pytest --junitxml={junit}", "command: .venv/bin/pytest -x --junitxml={junit}"),
        ('-k "{names}"', '-x -k "{names}"'),
        ("SHOP_MODE: test", "SHOP_MODE: prod"),
        ("--port {port}", "--port {port} --reload"),
    ],
)
def test_a_change_of_any_of_the_five_values_changes_the_digest(home, project, old, new):
    before = approvals.digest(configured(project))
    assert approvals.digest(configured(project, COMMANDS.replace(old, new))) != before


def test_other_keys_do_not_change_the_digest(home, project):
    before = approvals.digest(configured(project))
    after = configured(project, COMMANDS + "  ready_path: /health\nexit_criteria:\n  min_pass_rate: 0.5\n")
    assert approvals.digest(after) == before


def test_an_approval_is_stored_at_user_level_for_the_path_of_the_project(home, project):
    value = approvals.digest(configured(project))
    assert not approvals.is_approved(project, value)
    approvals.store(project, value)
    assert approvals.is_approved(project, value)
    assert approvals.approvals_path() == home / "approvals.json"
    stored = json.loads((home / "approvals.json").read_text(encoding="utf-8"))
    entry = stored["project_commands"][str(project.resolve())]
    assert entry["sha256"] == value and entry["approved_at"]
    assert sorted(path.name for path in (project / ".retro").iterdir()) == ["config.yaml"]


def test_a_new_approval_replaces_the_previous_one_and_keeps_other_projects(home, project, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    approvals.store(other, "a" * 64)
    approvals.store(project, "b" * 64)
    approvals.store(project, "c" * 64)
    assert not approvals.is_approved(project, "b" * 64)
    assert approvals.is_approved(project, "c" * 64)
    assert approvals.is_approved(other, "a" * 64)
    assert sorted(p.name for p in home.iterdir()) == ["approvals.json"]  # no temporary file is left


@pytest.mark.parametrize("content", ["{not json", '["a list"]', '{"project_commands": {"/x": "text"}}'])
def test_a_file_that_cannot_be_read_is_reported_and_never_overwritten(home, project, content):
    home.mkdir()
    (home / "approvals.json").write_text(content, encoding="utf-8")
    with pytest.raises(approvals.ApprovalsError, match=r"approvals\.json"):
        approvals.is_approved(project, "a" * 64)
    with pytest.raises(approvals.ApprovalsError, match="fix or delete it"):
        approvals.store(project, "a" * 64)
    assert (home / "approvals.json").read_text(encoding="utf-8") == content
