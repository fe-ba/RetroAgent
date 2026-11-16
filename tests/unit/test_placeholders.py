"""Placeholders of project commands (configuration.md, Placeholders)."""

import pytest

from retroagent.config import PlaceholderError, expand

VALUES = {
    "junit": "/p/.retro/runs/RUN-0001/junit-1.xml",
    "names": "test_a or test_b",
    "port": 8123,
    "worktree": "/home/u/.retro/worktrees/shop-0123456789ab/wt",
    "run_dir": "/p/.retro/runs/RUN-0001",
    "cache_dir": "/home/u/.retro/cache/shop-0123456789ab",
}


def test_every_placeholder_expands():
    template = "{junit} {names} {port} {worktree} {run_dir} {cache_dir}"
    assert expand(template, VALUES) == " ".join(str(value) for value in VALUES.values())


def test_names_inside_quotes():
    command = '.venv/bin/python -m pytest tests --junitxml={junit} -k "{names}"'
    assert expand(command, VALUES) == (
        '.venv/bin/python -m pytest tests --junitxml=/p/.retro/runs/RUN-0001/junit-1.xml -k "test_a or test_b"'
    )


def test_a_placeholder_can_repeat():
    assert expand("{port}:{port}", {"port": 1}) == "1:1"


def test_other_braces_are_left_as_they_are():
    command = "echo ${HOME} {unknown} && awk '{print $1}' {junit}"
    assert expand(command, {"junit": "j.xml"}) == "echo ${HOME} {unknown} && awk '{print $1}' j.xml"


def test_a_placeholder_without_value_is_an_error():
    with pytest.raises(PlaceholderError, match=r"\{names\}"):
        expand("pytest -k '{names}'", {"junit": "j.xml"})


def test_the_example_setup_expands():
    setup = (
        "python3 -m venv .venv && .venv/bin/python -m pip install --quiet --cache-dir {cache_dir}/pip"
        " -r requirements-dev.txt"
    )
    assert "--cache-dir /home/u/.retro/cache/shop-0123456789ab/pip " in expand(setup, VALUES)
