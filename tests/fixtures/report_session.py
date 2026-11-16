"""A stand-in for the session that the reports server uses, on a temporary project directory.

It has what ``retroagent.servers.reports`` reads from ``runtime.session.Session``: the project directory, the
configuration, the connection, the session id and the session versions. The configuration is the one of
``shop-api``: ``min_pass_rate`` 0.90.
"""

from dataclasses import dataclass
from pathlib import Path

from retroagent.config import Config, load_config
from retroagent.memory import connect
from retroagent.runtime.session import Session

CONFIG = "project:\n  name: shop-api\nexit_criteria:\n  min_pass_rate: 0.90\n"


@dataclass
class ReportSession:
    project_dir: Path
    config: Config
    conn: object
    id: int

    versions = Session.versions

    def with_id(self, session_id: int) -> "ReportSession":
        return ReportSession(self.project_dir, self.config, self.conn, session_id)


def open_project(path: Path) -> ReportSession:
    (path / ".retro").mkdir(parents=True, exist_ok=True)
    (path / ".retro" / "config.yaml").write_text(CONFIG, encoding="utf-8")
    return ReportSession(path, load_config(path), connect(path), 0)
