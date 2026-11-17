"""Approval of the project commands (configuration.md, Project commands; ADR-0024).

The approval covers ``tests.setup``, ``tests.command``, ``tests.select``, ``service.start`` and ``tests.env``
together. It is stored in ``<user level>/approvals.json`` as the SHA-256 of their content, for the resolved path of
the project::

    {"project_commands": {"/path/of/project": {"sha256": "<hex>", "approved_at": "<ISO 8601 UTC>"}}}

A new approval of a project replaces its previous one. A file that cannot be read is never overwritten.
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from retroagent.config.loader import Config, retro_home
from retroagent.memory.db import utc_now

COMMAND_KEYS = ("tests.setup", "tests.command", "tests.select", "service.start", "tests.env")
FILE_NAME = "approvals.json"
SECTION = "project_commands"


class ApprovalsError(Exception):
    """``approvals.json`` cannot be read: it is never overwritten, and the run is refused."""


def approvals_path() -> Path:
    return retro_home() / FILE_NAME


def project_commands(config: Config) -> dict[str, object]:
    """The five values the approval covers, as configured; an unset command is None."""
    return {key: config[key] for key in COMMAND_KEYS}


def digest(config: Config) -> str:
    """The SHA-256 of the canonical JSON of the five values."""
    canonical = json.dumps(project_commands(config), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _key(project_dir: str | Path) -> str:
    return str(Path(project_dir).resolve())


def _read() -> dict:
    path = approvals_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ApprovalsError(f"{path} cannot be read ({error}); fix or delete it") from error
    section = data.get(SECTION, {}) if isinstance(data, dict) else None
    if not isinstance(section, dict) or not all(isinstance(entry, dict) for entry in section.values()):
        raise ApprovalsError(f"{path} is not a file of approvals written by RetroAgent; fix or delete it")
    return data


def is_approved(project_dir: str | Path, value: str) -> bool:
    """Whether ``value`` is the stored approval of the project. Raises ``ApprovalsError``."""
    entry = _read().get(SECTION, {}).get(_key(project_dir))
    return entry is not None and entry.get("sha256") == value


def store(project_dir: str | Path, value: str) -> None:
    """Store the approval of the project, replacing its previous one. Raises ``ApprovalsError`` and writes nothing
    when the file cannot be read."""
    data = _read()
    data.setdefault(SECTION, {})[_key(project_dir)] = {"sha256": value, "approved_at": utc_now()}
    path = approvals_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".approvals-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(data, output, indent=2, ensure_ascii=False)
            output.write("\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
