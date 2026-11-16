"""Reporting: tables ``evaluation`` and ``report``."""

import json
import sqlite3

from retroagent.memory.db import require_exists, transaction, utc_now
from retroagent.memory.ids import next_id


def add_evaluation(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    thresholds: dict,
    metrics: dict,
    criteria: list,
    decision: str,
    decision_details: dict,
    tool_version: str,
    baseline_run_id: str | None = None,
    full_base_run_id: str | None = None,
    full_candidate_run_id: str | None = None,
    analysis_id: int | None = None,
) -> int:
    """Store an evaluation, with the reasons and conditions of its decision as they are now."""
    with transaction(conn):
        require_exists(conn, "run", "id", run_id, "run")
        cursor = conn.execute(
            "INSERT INTO evaluation (run_id, baseline_run_id, full_base_run_id, full_candidate_run_id, analysis_id,"
            " thresholds, metrics, criteria, decision, decision_details, tool_version, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                baseline_run_id,
                full_base_run_id,
                full_candidate_run_id,
                analysis_id,
                json.dumps(thresholds),
                json.dumps(metrics),
                json.dumps(criteria),
                decision,
                json.dumps(decision_details),
                tool_version,
                utc_now(),
            ),
        )
        return cursor.lastrowid


def add_report(
    conn: sqlite3.Connection,
    *,
    type: str,
    model: str,
    path_template: str = ".retro/reports/{id}-{type}/",
    evaluation_id: int | None = None,
) -> str:
    """Create a ``draft`` report. The path is built from its new identifier."""
    with transaction(conn):
        report_id = next_id(conn, "RPT")
        conn.execute(
            "INSERT INTO report (id, type, status, evaluation_id, model, path, formats, created_at)"
            " VALUES (?, ?, 'draft', ?, ?, ?, '[]', ?)",
            (report_id, type, evaluation_id, model, path_template.format(id=report_id, type=type), utc_now()),
        )
    return report_id


def mark_rendered(conn: sqlite3.Connection, report_id: str, formats: list[str]) -> None:
    """A draft becomes rendered, and then never changes again (INV-10)."""
    with transaction(conn):
        conn.execute(
            "UPDATE report SET status = 'rendered', formats = ? WHERE id = ?", (json.dumps(formats), report_id)
        )
