"""The context that the reports server is started with, on a temporary project directory, with an open connection
for the checks of the tests.

``ReportSession`` is a ``serving.Context``: the functions of ``retroagent.servers.reports`` take it as the server
does. The configuration is the one of ``shop-api``: ``min_pass_rate`` 0.90.
"""

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

from retroagent.memory import connect
from retroagent.servers.serving import Context

CONFIG = "project:\n  name: shop-api\nexit_criteria:\n  min_pass_rate: 0.90\n"


@dataclass(frozen=True)
class ReportSession(Context):
    conn: object = field(default=None, compare=False)

    def with_id(self, session_id: int) -> "ReportSession":
        return dataclasses.replace(self, session_id=session_id)


def open_project(path: Path) -> ReportSession:
    (path / ".retro").mkdir(parents=True, exist_ok=True)
    (path / ".retro" / "config.yaml").write_text(CONFIG, encoding="utf-8")
    return ReportSession(path.resolve(), 0, connect(path))
