"""What ``retro init`` detects (project-contract.md, Detection by ``retro init``), and that it never overwrites."""

import os
import subprocess

import pytest

from retroagent.runtime import init

REQUIREMENTS = "# Requirements\n\n## REQ-001: Login\n\nUsers log in.\n\n- Priority: high\n"


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "project"
    path.mkdir()
    git(path, "init", "--quiet", "--initial-branch=main")
    return path


def commit_and_tag(repo, tag, date, annotated=False):
    (repo / "version.txt").write_text(tag)
    git(repo, "add", ".")
    environment = {"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date}
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--quiet", "-m", tag],
        cwd=repo,
        check=True,
        env={**os.environ, **environment},
    )
    git(repo, "tag", *(["-a", "-m", tag] if annotated else []), tag)


@pytest.mark.parametrize(
    "files, marker, command, junit",
    [
        ({"pyproject.toml": "[tool.pytest.ini_options]\n"}, "pyproject.toml", "pytest --junitxml={junit}", "{junit}"),
        ({"pytest.ini": "[pytest]\n"}, "pytest.ini", "pytest --junitxml={junit}", "{junit}"),
        ({"setup.cfg": "[tool:pytest]\n"}, "setup.cfg", "pytest --junitxml={junit}", "{junit}"),
        ({"package.json": '{"devDependencies": {"vitest": "^2"}}'}, "package.json",
         "npx vitest run --reporter=junit --outputFile={junit}", "{junit}"),
        ({"pom.xml": "<project/>"}, "pom.xml", "mvn -q test", "target/surefire-reports/*.xml"),
        ({"build.gradle.kts": ""}, "build.gradle.kts", "./gradlew test", "build/test-results/test/*.xml"),
        ({"go.mod": "module x\n"}, "go.mod", "gotestsum --junitfile {junit}", "{junit}"),
    ],
)  # fmt: skip
def test_each_marker_of_the_table(tmp_path, files, marker, command, junit):
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    assert init.detect_framework(tmp_path) == init.Framework(marker, command, junit)


@pytest.mark.parametrize(
    "files",
    [{"pyproject.toml": "[project]\nname = 'x'\n"}, {"setup.cfg": "[metadata]\n"}, {"package.json": '{"x": 1}'}, {}],
)
def test_no_marker_detects_nothing(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    assert init.detect_framework(tmp_path) is None


def test_requirements_are_markdown_files_with_requirement_ids(tmp_path):
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    (tmp_path / "requirements.txt").write_text("pytest\n")  # a dependency list
    (tmp_path / "requirements-old.md").write_text("# Nothing here\n")  # no requirement ID
    (tmp_path / "requirements.md").write_text(REQUIREMENTS)
    (tmp_path / "docs" / "requirements.md").write_text(REQUIREMENTS)
    (tmp_path / "docs" / "specs" / "requirements-api.md").write_text(REQUIREMENTS)
    (tmp_path / "docs" / "notes.md").write_text(REQUIREMENTS)
    assert init.detect_requirements(tmp_path) == (
        "docs/requirements.md",
        "docs/specs/requirements-api.md",
        "requirements.md",
    )


def test_versions_are_the_two_most_recent_tags(repo):
    assert init.detect_versions(repo) == (None, None)
    commit_and_tag(repo, "v1.0", "2026-01-01T10:00:00+00:00")
    assert init.detect_versions(repo) == (None, None)
    commit_and_tag(repo, "v1.10", "2026-02-01T10:00:00+00:00", annotated=True)
    commit_and_tag(repo, "v1.9", "2026-03-01T10:00:00+00:00")
    assert init.detect_versions(repo) == ("v1.10", "v1.9")  # by date, not by name


def test_tags_of_the_same_commit_are_ordered_by_version(repo):
    commit_and_tag(repo, "v1.0", "2026-01-01T10:00:00+00:00")
    git(repo, "tag", "v1.10")
    git(repo, "tag", "v1.9")
    assert init.detect_versions(repo) == ("v1.9", "v1.10")


def test_the_proposal_without_anything_detected_is_commented(repo):
    proposal = init.propose(repo)
    text = init.config_text(proposal)
    assert 'name: "project"' in text and "# tests:" in text and "# versions:" in text and "# requirements:" in text
    assert "## Running\n\nTo be written" in init.retro_md_text(proposal)


def test_write_never_overwrites(repo):
    (repo / "RETRO.md").write_text("Mine.\n")
    created, kept = init.write(repo, init.propose(repo))
    assert (created, kept) == ([".retro/config.yaml", ".retro/.gitignore"], ["RETRO.md"])
    assert (repo / "RETRO.md").read_text() == "Mine.\n"
    assert (repo / ".retro" / ".gitignore").read_text() == "retro.db\nretro.db-*\nretro.lock\nruns/\n"
    assert init.write(repo, init.propose(repo)) == ([], ["RETRO.md", ".retro/config.yaml", ".retro/.gitignore"])
