"""The computed sections of a completion report, for comparison with the expected report of shop-api (SC-11)."""

import difflib
import re
from pathlib import Path

from retroagent.resources import __file__ as resources_file

EXPECTED = Path(resources_file).parent / "examples" / "shop-api" / "expected"
# The rows that SC-11 allows to differ: generation time, model, tool version and the two durations.
VARIABLE_ROWS = ("| Generated |", "| Model |", "| RetroAgent |", "| Run duration |", "| Test time |")


def computed(text: str) -> str:
    """The computed sections of a report: no blockquote (the prototype note and the agent sections), no variable row."""
    lines = [line for line in text.split("\n") if not line.startswith(">") and not line.startswith(VARIABLE_ROWS)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def difference(expected: str, actual: str) -> str:
    return "\n".join(
        difflib.unified_diff(expected.split("\n"), actual.split("\n"), "expected", "generated", lineterm="")
    )


def expected_computed() -> str:
    """The computed sections of ``expected/test-completion-report.md``."""
    return computed((EXPECTED / "test-completion-report.md").read_text(encoding="utf-8"))
