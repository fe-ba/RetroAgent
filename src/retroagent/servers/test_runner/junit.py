"""JUnit XML, the only source of test results (ADR-0010).

An entry is one ``<testcase>``. Its outcome is ``error`` when it has an ``<error>`` (also together with a
``<failure>``), ``failed`` with a ``<failure>``, ``skipped`` with a ``<skipped>``, and ``passed`` otherwise.
When two entries have the same ``classname`` and ``name``, the first one counts (project-contract.md).
"""

import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


class JunitError(Exception):
    """No valid JUnit XML: the file is missing, empty or not JUnit XML. The run is blocked with ``no_junit``."""


@dataclass(frozen=True)
class Entry:
    classname: str
    name: str
    file: str | None
    outcome: str  # passed, failed, error or skipped
    message: str | None  # failure or error message and details, or the reason of a skip
    duration: float | None  # seconds

    @property
    def test_id(self) -> str:
        """Identity of the test: ``<classname>::<name>`` (project-contract.md, Test identity)."""
        return f"{self.classname}::{self.name}"

    @property
    def is_load_error(self) -> bool:
        """Whether the entry is an error of a file that could not be loaded, not of a test: pytest reports a file it
        cannot collect as an ``error`` entry with an empty ``classname`` and the module path of the file as ``name``
        (project-contract.md, Generated tests). Only the pytest form is recognized; a real pytest test always has a
        classname."""
        return self.outcome == "error" and not self.classname

    @property
    def implementation(self) -> str:
        """For a project test: the ``file`` attribute when there is one, otherwise the classname, ``::<name>``."""
        return f"{self.file or self.classname}::{self.name}"


def parse(paths: Iterable[str | Path]) -> list[Entry]:
    """Entries of one or more JUnit XML files, in document order. Raises ``JunitError``."""
    paths = list(paths)
    if not paths:
        raise JunitError("no JUnit XML file was found")
    entries: dict[tuple[str, str], Entry] = {}
    for path in paths:
        for entry in _parse_file(Path(path)):
            entries.setdefault((entry.classname, entry.name), entry)
    return list(entries.values())


def _parse_file(path: Path) -> list[Entry]:
    if not path.is_file():
        raise JunitError(f"{path} does not exist")
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError as error:
        raise JunitError(f"{path} is not valid XML: {error}") from error
    if root.tag not in ("testsuites", "testsuite"):
        raise JunitError(f"{path} is not JUnit XML: its root element is <{root.tag}>")
    return [_entry(path, element) for element in root.iter("testcase")]


def _entry(path: Path, element: ElementTree.Element) -> Entry:
    name = element.get("name")
    if not name:
        raise JunitError(f"{path} has a <testcase> without a name")
    error, failure, skipped = (element.find(tag) for tag in ("error", "failure", "skipped"))
    if error is not None:
        outcome, message = "error", _details(error)
    elif failure is not None:
        outcome, message = "failed", _details(failure)
    elif skipped is not None:
        outcome, message = "skipped", skipped.get("message") or _text(skipped)
    else:
        outcome, message = "passed", None
    return Entry(
        classname=element.get("classname", ""),
        name=name,
        file=element.get("file") or None,
        outcome=outcome,
        message=message,
        duration=_seconds(element.get("time")),
    )


def _details(element: ElementTree.Element) -> str | None:
    """The ``message`` attribute followed by the text (for example a traceback), without repeating it."""
    message, text = element.get("message"), _text(element)
    if message and text and text.startswith(message):
        return text
    return "\n".join(part for part in (message, text) if part) or None


def _text(element: ElementTree.Element) -> str | None:
    return (element.text or "").strip() or None


def _seconds(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
