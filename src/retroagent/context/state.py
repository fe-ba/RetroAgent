"""The state message: session state and a digest of project memory, the last message of every call
(spec/context-loading.md, State message; ADR-0028).

It is generated for every call and never stored in the conversation, so the messages before it never change. The
digest has a fixed set of lines and no free text: it is computed by code from stored records, so it cannot state a
result that is not stored.
"""

import datetime
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from retroagent.config.schema import KEYS
from retroagent.llm.provider import Message
from retroagent.memory import design, execution

PERMISSION_KEYS = tuple(key.removeprefix("permissions.") for key in KEYS if key.startswith("permissions."))
SEVERITIES = ("critical", "high", "medium", "low")
SHORT_COMMIT = 7

HEADER = (
    "<session-state>\n"
    "Written by the runtime of RetroAgent, not by the user. Computed by code from the session and from project memory."
)
FOOTER = "</session-state>"


@dataclass(frozen=True)
class Version:
    ref: str
    commit: str


@dataclass(frozen=True)
class CycleStep:
    name: str
    position: int
    total: int


@dataclass(frozen=True)
class SessionState:
    date: datetime.date
    project_name: str
    project_path: str
    base: Version | None
    candidate: Version | None
    mode: str
    permissions: Mapping[str, str]  # effective value of each permission; a session grant is "allow"
    commands_approved: bool  # stored approval, or --trust-commands
    model: str  # <provider>/<model name>
    language: str
    cycle_step: CycleStep | None = None


@dataclass(frozen=True)
class AnalysisDigest:
    id: int
    changed_files: int
    impact_recorded: bool
    impacted_requirements: int


@dataclass(frozen=True)
class SuiteDigest:
    id: int
    test_cases: int
    designed_only: int


@dataclass(frozen=True)
class RunDigest:
    id: str
    scope: str
    status: str
    passed: int
    failed: int
    error: int
    blocked: int


@dataclass(frozen=True)
class TriageDigest:
    run_id: str
    untriaged: int  # failed or error executions without triage


@dataclass(frozen=True)
class EvaluationDigest:
    id: int
    decision: str


@dataclass(frozen=True)
class Digest:
    analysis: AnalysisDigest | None
    suite: SuiteDigest | None
    base_run: RunDigest | None
    candidate_run: RunDigest | None
    triage: TriageDigest | None
    open_defects: Mapping[str, int]  # every severity, project-wide
    evaluation: EvaluationDigest | None


def read_digest(conn: sqlite3.Connection, base_commit: str | None, candidate_commit: str | None) -> Digest:
    """The digest of project memory for the session versions. Only reads."""
    analysis = _analysis(conn, base_commit, candidate_commit) if base_commit and candidate_commit else None
    suite = None
    if analysis is not None:
        suite_id = design.current_suite(conn, base_commit, candidate_commit)
        suite = _suite(conn, suite_id) if suite_id is not None else None
    base_run = _latest_run(conn, "base", base_commit) if base_commit else None
    candidate_run = _latest_run(conn, "candidate", candidate_commit) if candidate_commit else None
    return Digest(
        analysis=analysis,
        suite=suite,
        base_run=base_run,
        candidate_run=candidate_run,
        triage=_triage(conn, candidate_run.id) if candidate_run else None,
        open_defects=_open_defects(conn),
        evaluation=_evaluation(conn, candidate_commit) if candidate_commit else None,
    )


def _analysis(conn: sqlite3.Connection, base_commit: str, candidate_commit: str) -> AnalysisDigest | None:
    row = conn.execute(
        "SELECT a.id,"
        " (SELECT COUNT(*) FROM analysis_file WHERE analysis_id = a.id) AS files,"
        " (SELECT COUNT(*) FROM analysis_module WHERE analysis_id = a.id) AS modules,"
        " (SELECT COUNT(*) FROM analysis_requirement WHERE analysis_id = a.id) AS requirements"
        " FROM analysis AS a WHERE a.base_commit = ? AND a.candidate_commit = ? ORDER BY a.id DESC LIMIT 1",
        (base_commit, candidate_commit),
    ).fetchone()
    if row is None:
        return None
    recorded = row["modules"] + row["requirements"] > 0
    return AnalysisDigest(row["id"], row["files"], recorded, row["requirements"])


def _suite(conn: sqlite3.Connection, suite_id: int) -> SuiteDigest:
    test_cases = design.suite_test_cases(conn, suite_id)
    designed = sum(1 for t in test_cases if t["status"] != "implemented")
    return SuiteDigest(suite_id, len(test_cases), designed)


def _latest_run(conn: sqlite3.Connection, role: str, commit: str) -> RunDigest | None:
    row = conn.execute(
        'SELECT id, scope, status FROM run WHERE version_role = ? AND "commit" = ? ORDER BY started_at DESC, id DESC'
        " LIMIT 1",
        (role, commit),
    ).fetchone()
    if row is None:
        return None
    counts = execution.execution_counts(conn, row["id"])
    return RunDigest(
        row["id"], row["scope"], row["status"], counts["passed"], counts["failed"], counts["error"], counts["blocked"]
    )


def _triage(conn: sqlite3.Connection, run_id: str) -> TriageDigest:
    (untriaged,) = conn.execute(
        "SELECT COUNT(*) FROM test_execution AS e WHERE e.run_id = ? AND e.result IN ('failed', 'error')"
        " AND NOT EXISTS (SELECT 1 FROM triage WHERE execution_id = e.id)",
        (run_id,),
    ).fetchone()
    return TriageDigest(run_id, untriaged)


def _open_defects(conn: sqlite3.Connection) -> dict[str, int]:
    counts = dict.fromkeys(SEVERITIES, 0)
    for row in conn.execute("SELECT severity, COUNT(*) AS n FROM defect WHERE status = 'open' GROUP BY severity"):
        counts[row["severity"]] = row["n"]
    return counts


def _evaluation(conn: sqlite3.Connection, candidate_commit: str) -> EvaluationDigest | None:
    row = conn.execute(
        'SELECT e.id, e.decision FROM evaluation AS e JOIN run AS r ON r.id = e.run_id WHERE r."commit" = ?'
        " ORDER BY e.id DESC LIMIT 1",
        (candidate_commit,),
    ).fetchone()
    return EvaluationDigest(row["id"], row["decision"]) if row else None


def state_message(session: SessionState, digest: Digest) -> Message:
    """The state message, with the user role (``llm-providers.md``, Context size, state message and caching)."""
    lines = [
        f"Date: {session.date.isoformat()}",
        f"Project: {session.project_name} at {session.project_path}",
        f"Versions: {_versions(session.base, session.candidate)}",
        f"Mode: {session.mode}",
        "Permissions: " + ", ".join(f"{key} {session.permissions[key]}" for key in PERMISSION_KEYS),
        f"Project commands: {'approved' if session.commands_approved else 'not approved'}",
    ]
    if session.cycle_step is not None:
        step = session.cycle_step
        lines.append(
            f"Cycle step: {step.name} ({step.position} of {step.total}). Do only this step, then end the turn."
        )
    lines += [
        f"Model: {session.model}",
        f"Language: Write responses and agent sections in `{session.language}`.",
        "",
        f"Analysis: {_analysis_line(digest.analysis)}",
        f"Current suite: {_suite_line(digest.suite)}",
        f"Runs: {_runs_line(digest.base_run, digest.candidate_run)}",
        f"Triage: {_triage_line(digest.triage)}",
        "Defects: open: " + ", ".join(f"{digest.open_defects[s]} {s}" for s in SEVERITIES),
        f"Evaluation: {_evaluation_line(digest.evaluation)}",
    ]
    return Message(role="user", content="\n".join([HEADER, "", *lines, FOOTER]))


def _version(role: str, version: Version | None) -> str:
    if version is None:
        return f"{role} not set"
    return f"{role} {version.ref} ({version.commit[:SHORT_COMMIT]})"


def _versions(base: Version | None, candidate: Version | None) -> str:
    if base is None and candidate is None:
        return "not set"
    return f"{_version('base', base)}, {_version('candidate', candidate)}"


def _analysis_line(analysis: AnalysisDigest | None) -> str:
    if analysis is None:
        return "none"
    impact = "impact recorded" if analysis.impact_recorded else "impact not recorded"
    return (
        f"ID {analysis.id}, {analysis.changed_files} changed files, {impact},"
        f" {analysis.impacted_requirements} impacted requirements"
    )


def _suite_line(suite: SuiteDigest | None) -> str:
    if suite is None:
        return "none"
    return f"ID {suite.id}, {suite.test_cases} test cases, {suite.designed_only} designed only"


def _run(role: str, run: RunDigest | None) -> str:
    if run is None:
        return f"{role} none"
    return (
        f"{role} {run.id} ({run.scope}, {run.status}): {run.passed} passed, {run.failed} failed, {run.error} error,"
        f" {run.blocked} blocked"
    )


def _runs_line(base: RunDigest | None, candidate: RunDigest | None) -> str:
    if base is None and candidate is None:
        return "none"
    return f"{_run('base', base)}; {_run('candidate', candidate)}"


def _triage_line(triage: TriageDigest | None) -> str:
    if triage is None:
        return "none"
    return f"{triage.run_id} has {triage.untriaged} failed or error executions without triage"


def _evaluation_line(evaluation: EvaluationDigest | None) -> str:
    return "none" if evaluation is None else f"ID {evaluation.id}, {evaluation.decision}"


def call_messages(system_context: str, conversation: Sequence[Message], state: Message) -> tuple[Message, ...]:
    """The messages of one call, from stable to volatile: system context, conversation, state message.

    The conversation is not changed: the state message is never stored in it.
    """
    return (Message(role="system", content=system_context), *conversation, state)
