"""Tests marked ``model`` run only when the marker expression asks for them.

``addopts`` deselects them with ``-m "not model"``, but a ``-m`` on the command line replaces that one: without this
guard, ``pytest -m "not network"`` would call a real model.
"""

import re

ASKS_FOR_MODEL = re.compile(r"(?<!not )\bmodel\b")


def pytest_collection_modifyitems(config, items):
    if ASKS_FOR_MODEL.search(config.getoption("markexpr") or ""):
        return
    deselected = [item for item in items if item.get_closest_marker("model")]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = [item for item in items if not item.get_closest_marker("model")]
