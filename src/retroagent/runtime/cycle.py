"""``/cycle [base] [candidate]``: the regression cycle driven by code (spec/runtime.md, Cycle command; ADR-0027).

The runtime decides the order of the steps. A model step is a turn of its own: the conversation is emptied before it,
the state message names the step, and only the tools of the step are exposed. A direct step calls
``test_runner.run_tests`` through ``commands.run``, without the model. After each step, code checks its outcome in
project memory; a model step whose outcome is missing runs once more, with a message that states what is missing.

The cycle stops when an outcome is still missing after the retry, when a tool call is refused by the mode, a
permission or the approval of the project commands, when a run of the step ends ``error`` or ``interrupted``, when
the model ends a step with a question, when the user interrupts, and when a turn ends in a runtime error, reaches
``agent.max_iterations`` or stops on repeated calls. ``/cycle`` again continues: a step whose outcome is already in
project memory for the session versions is skipped.

What "done" means for each step, computed from stored records only (``progress``):

- ``analyze``: the latest analysis of the session commits has an impact.
- ``discover``: a completed full run exists on the baseline commit and, when the change set of the analysis has a
  test file (added, modified, deleted or renamed), on the candidate commit. A full run on a commit counts whatever
  its role. The evaluation takes the full baseline run only among runs of role ``base``, so in a cycle whose baseline
  was the candidate of an earlier cycle (v1.1 in cycle 2 of shop-api) the full run of v1.1 skips the baseline
  discovery but is not used as the full baseline run: the selection-quality metrics (FR-34, ``Should``) are then not
  evaluable.
- ``select``: that analysis has a suite.
- ``design`` and ``implement`` have no outcome of their own: they count as done when the ``run`` outcome exists,
  and run again otherwise. Their skills make that safe: design avoids duplicates, implement targets ``designed``
  test cases only.
- ``run``: the latest run of the current suite is ``completed`` against each version. On a resume, only the versions
  without one run again, the baseline first.
- ``triage``: the latest suite run against the candidate has no failed or error execution without triage.
- ``report``: a ``completion`` report of that run is ``rendered``.

In plan mode the cycle runs ``analyze``, ``select`` and ``design``, and stops before ``implement``.
"""

import fnmatch
import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from retroagent.context import state, tools
from retroagent.memory import design, impact
from retroagent.runtime import commands, turn
from retroagent.runtime.session import Session, Version

STEPS = ("analyze", "discover", "select", "design", "implement", "run", "triage", "report")
PLAN_STEPS = ("analyze", "select", "design")
DIRECT_STEPS = frozenset({"discover", "run"})
ROLES = ("base", "candidate")

# A file of the change set is a test file when its path, or its former path for a renamed file, has a folder with one
# of these names, or a file name that matches one of these patterns (runtime.md, Cycle command).
TEST_FOLDERS = frozenset({"test", "tests", "__tests__", "spec"})
TEST_NAMES = ("test_*", "*_test.*", "*.test.*", "*.spec.*", "*Test.java")

# Why a cycle stopped. Every reason but ``refused`` is a runtime error; a refusal gives exit code 4 through the count
# of refused calls of the session (cli.md, Exit codes).
STOP_REASONS = ("missing", "refused", "run_failed", "question", "interrupted", "limit", "error")

RETRY = "This step already ran once, and its outcome is missing: {missing}. Complete the step."
PLAN_END = (
    "Plan mode: the cycle stops before implement. The steps implement, run, triage and report need mode default or"
    " auto."
)


class CycleError(Exception):
    """``/cycle`` cannot start: the session versions are not set. Invalid usage; no model call was made."""


# Test files ---------------------------------------------------------------------------------------------------------


def is_test_file(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts:
        return False
    return any(part in TEST_FOLDERS for part in parts[:-1]) or any(
        fnmatch.fnmatchcase(parts[-1], pattern) for pattern in TEST_NAMES
    )


def has_test_file(files: Sequence[sqlite3.Row | dict]) -> bool:
    """Whether a change set has a test file: its path, or its former path for a renamed file, is a test file. Any
    change counts, a deletion too: the full run on the candidate shows the tests a change adds and those it
    deletes."""
    for changed in files:
        old_path = changed["old_path"] if "old_path" in changed.keys() else None
        if is_test_file(changed["path"]) or (old_path is not None and is_test_file(old_path)):
            return True
    return False


# Progress: what project memory holds for the session versions -------------------------------------------------------


@dataclass(frozen=True)
class Progress:
    base: Version
    candidate: Version
    analysis_id: int | None = None
    impact_recorded: bool = False
    full_runs_missing: tuple[str, ...] = ()  # roles without a completed full run on their commit, base first
    suite_id: int | None = None
    suite_runs: dict[str, sqlite3.Row | None] = field(default_factory=dict)  # latest run of the suite, by role
    untriaged: int = 0  # failed or error executions without triage in the candidate suite run
    report_id: str | None = None  # a rendered completion report of the candidate suite run

    @property
    def candidate_run(self) -> sqlite3.Row | None:
        return self.suite_runs.get("candidate")

    @property
    def suite_runs_not_completed(self) -> tuple[str, ...]:
        """The roles whose latest run of the current suite is missing or not ``completed``, base first."""
        runs = {role: self.suite_runs.get(role) for role in ROLES}
        return tuple(role for role, run in runs.items() if run is None or run["status"] != "completed")

    def version(self, role: str) -> Version:
        return self.base if role == "base" else self.candidate


def progress(conn: sqlite3.Connection, base: Version, candidate: Version) -> Progress:
    """Read the progress of the cycle of these versions from project memory. Only reads."""
    analysis_id = impact.latest_analysis(conn, base.commit, candidate.commit)
    if analysis_id is None:
        return Progress(base, candidate)
    roles = ["base", *(["candidate"] if has_test_file(impact.list_files(conn, analysis_id)) else [])]
    commits = {"base": base.commit, "candidate": candidate.commit}
    full_runs_missing = tuple(role for role in roles if not _full_run_exists(conn, commits[role]))
    suite_id = design.current_suite(conn, base.commit, candidate.commit)
    suite_runs = {role: _suite_run(conn, suite_id, role, commits[role]) for role in ROLES} if suite_id else {}
    untriaged, report_id = 0, None
    candidate_run = suite_runs.get("candidate")
    if candidate_run is not None and candidate_run["status"] == "completed":
        untriaged = _untriaged(conn, candidate_run["id"])
        report_id = _rendered_completion(conn, candidate_run["id"])
    return Progress(
        base,
        candidate,
        analysis_id,
        _impact_recorded(conn, analysis_id),
        full_runs_missing,
        suite_id,
        suite_runs,
        untriaged,
        report_id,
    )


def _impact_recorded(conn: sqlite3.Connection, analysis_id: int) -> bool:
    return any(
        conn.execute(f"SELECT 1 FROM {table} WHERE analysis_id = ? LIMIT 1", (analysis_id,)).fetchone()
        for table in ("analysis_module", "analysis_requirement", "analysis_requirement_not_impacted")
    )


def _full_run_exists(conn: sqlite3.Connection, commit: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM run WHERE scope = 'all' AND status = 'completed' AND \"commit\" = ? LIMIT 1", (commit,)
        ).fetchone()
        is not None
    )


def _suite_run(conn: sqlite3.Connection, suite_id: int, role: str, commit: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM run WHERE suite_id = ? AND scope = 'suite' AND version_role = ? AND \"commit\" = ?"
        " ORDER BY started_at DESC, rowid DESC LIMIT 1",
        (suite_id, role, commit),
    ).fetchone()


def _untriaged(conn: sqlite3.Connection, run_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM test_execution AS e WHERE e.run_id = ? AND e.result IN ('failed', 'error')"
        " AND NOT EXISTS (SELECT 1 FROM triage WHERE execution_id = e.id)",
        (run_id,),
    ).fetchone()[0]


def _rendered_completion(conn: sqlite3.Connection, run_id: str) -> str | None:
    row = conn.execute(
        "SELECT r.id FROM report AS r JOIN evaluation AS e ON e.id = r.evaluation_id"
        " WHERE r.type = 'completion' AND r.status = 'rendered' AND e.run_id = ? ORDER BY r.id DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    return row["id"] if row else None


def _pair(p: Progress) -> str:
    return f"{p.base.ref}..{p.candidate.ref}"


def missing(step: str, p: Progress) -> str | None:
    """What is missing from the outcome of ``step``, or None when it is in project memory. ``design`` and
    ``implement`` have no outcome checked by code."""
    if step in ("design", "implement"):
        return None
    if step == "analyze":
        if p.analysis_id is None:
            return f"there is no analysis of {_pair(p)}: call git__analyze_changes, then memory__save_impact"
        if not p.impact_recorded:
            return f"analysis {p.analysis_id} has no impact recorded: call memory__save_impact with its analysis_id"
        return None
    if p.analysis_id is None:
        return f"there is no analysis of {_pair(p)}"
    if step == "discover":
        if not p.full_runs_missing:
            return None
        return "no completed full run against " + " and ".join(
            f"the {role} {p.version(role).ref}" for role in p.full_runs_missing
        )
    if step == "select":
        if p.suite_id is None:
            return f"analysis {p.analysis_id} has no suite: call memory__save_suite with its analysis_id"
        return None
    if p.suite_id is None:
        return f"analysis {p.analysis_id} has no suite"
    if step == "run":
        not_completed = p.suite_runs_not_completed
        if not not_completed:
            return None
        return f"suite {p.suite_id} has no completed run against " + " and ".join(
            f"the {role} {p.version(role).ref}" for role in not_completed
        )
    run = p.candidate_run
    if run is None or run["status"] != "completed":
        return f"suite {p.suite_id} has no completed run against the candidate {p.candidate.ref}"
    if step == "triage":
        if p.untriaged:
            return (
                f"{run['id']} has {p.untriaged} failed or error executions without triage: read them with"
                f" memory__get_executions (run_id {run['id']}, untriaged true) and record each with memory__save_triage"
            )
        return None
    if step == "report":
        if p.report_id is None:
            return (
                f"no completion report of {run['id']} is rendered: call reports__prepare_report with type completion,"
                " then reports__render_report with its sections"
            )
        return None
    raise ValueError(f"unknown step {step!r}")


def done(step: str, p: Progress) -> str | None:
    """Why ``step`` is already done for the session versions, or None when it must run."""
    if step in ("design", "implement"):
        if missing("run", p) is None:
            runs = ", ".join(p.suite_runs[role]["id"] for role in ROLES)
            return f"the suite {p.suite_id} already ran against both versions ({runs})"
        return None
    if missing(step, p) is not None:
        return None
    if step == "analyze":
        return f"analysis {p.analysis_id} of {_pair(p)} has an impact"
    if step == "discover":
        return f"completed full runs exist for {_pair(p)}"
    if step == "select":
        return f"analysis {p.analysis_id} has the suite {p.suite_id}"
    if step == "run":
        return f"{p.suite_runs['base']['id']} and {p.suite_runs['candidate']['id']} are completed"
    if step == "triage":
        return f"no failure of {p.candidate_run['id']} is left without triage"
    return f"{p.report_id} is rendered for {p.candidate_run['id']}"


def ends_with_question(text: str) -> bool:
    """Whether an answer ends with a question for the user: its last non-empty line ends with ``?``."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(lines) and lines[-1].rstrip("*_`\"' ").endswith("?")


# Events, for the display ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StepStarted:
    name: str
    position: int
    total: int
    retry: bool = False


@dataclass(frozen=True)
class StepSkipped:
    name: str
    position: int
    total: int
    reason: str


@dataclass(frozen=True)
class StepAnswered:
    name: str
    result: turn.TurnResult


@dataclass(frozen=True)
class StepRuns:
    name: str
    outcome: commands.RunOutcome


# Result ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Stop:
    step: str
    reason: str  # one of STOP_REASONS
    message: str
    ends_session: bool = False  # the truncation guard: the session must not continue

    @property
    def runtime_error(self) -> bool:
        return self.reason != "refused"


@dataclass(frozen=True)
class CycleResult:
    steps: tuple[tuple[str, str], ...]  # (step, "ran" or "skipped"), in order
    stop: Stop | None = None
    answer: str | None = None  # the answer of the last model step that ran
    recorded: turn.Recorded | None = None  # every model step of the cycle; None when no model step ran
    plan_end: bool = False  # plan mode: the cycle stopped before implement


Show = Callable[[object], None]


def run_cycle(
    session: Session,
    refs: Sequence[str] = (),
    *,
    ask: turn.Ask | None = None,
    listener: Callable[[object], None] | None = None,
    interrupt: threading.Event | None = None,
    show: Show | None = None,
) -> CycleResult:
    """Run ``/cycle [base] [candidate]``. ``listener`` receives the events of the turns and of the direct runs,
    ``show`` the events of the cycle. Raises ``ToolError`` when the refs do not resolve and ``CycleError`` when the
    session versions are not set; in both cases no step ran."""
    if refs:
        base, candidate = refs
        turn.call_tool(session, "runtime__set_versions", {"base": base, "candidate": candidate}, ask=ask)
    versions = session.versions()
    if versions["base"] is None or versions["candidate"] is None:
        raise CycleError(
            "the session versions are not set: use /cycle <base> <candidate>, or start with --base and --candidate"
        )
    return _Cycle(session, ask, listener, interrupt, show).run()


class _Cycle:
    def __init__(self, session: Session, ask, listener, interrupt, show):
        self.session, self.ask, self.listener, self.interrupt = session, ask, listener, interrupt
        self.show = show or (lambda event: None)
        self.steps: list[tuple[str, str]] = []
        self.answer: str | None = None
        self.counts: dict[str, int] | None = None

    def progress(self) -> Progress:
        versions = self.session.versions()
        return progress(self.session.conn, versions["base"], versions["candidate"])

    def run(self) -> CycleResult:
        plan = self.session.mode == tools.PLAN
        steps = PLAN_STEPS if plan else STEPS
        for position, name in enumerate(steps, start=1):
            if self.interrupt is not None and self.interrupt.is_set():
                return self.result(Stop(name, "interrupted", f"The cycle was interrupted before the step {name}."))
            reason = done(name, self.progress())
            if reason is not None:
                self.steps.append((name, "skipped"))
                self.show(StepSkipped(name, position, len(steps), reason))
                continue
            self.steps.append((name, "ran"))
            self.show(StepStarted(name, position, len(steps)))
            if name in DIRECT_STEPS:
                stop = self.direct_step(name)
            else:
                stop = self.model_step(name, state.CycleStep(name, position, len(steps)))
            if stop is not None:
                return self.result(stop)
        return self.result(None, plan_end=plan)

    def result(self, stop: Stop | None, plan_end: bool = False) -> CycleResult:
        recorded = tuple(self.counts.items()) if self.counts is not None else None
        return CycleResult(tuple(self.steps), stop, self.answer, recorded, plan_end)

    # Model steps ---------------------------------------------------------------------------------------------------

    def message(self, step: str, p: Progress) -> str:
        if step == "analyze":
            return commands.ANALYZE
        if step == "select":
            return commands.SELECT
        if step == "design":
            return commands.design_message(None)
        if step == "implement":
            return commands.implement_message(())
        if step == "triage":
            return commands.TRIAGE.format(run_id=p.candidate_run["id"])
        if step == "report":
            return commands.report_message("completion")
        raise ValueError(f"not a model step: {step}")

    def model_step(self, step: str, cycle_step: state.CycleStep) -> Stop | None:
        session = self.session
        message = self.message(step, self.progress())
        refusals = session.permission_refusals
        last_run = _last_run_rowid(session.conn)
        text = message
        for attempt in (1, 2):
            if attempt == 2:
                self.show(StepStarted(step, cycle_step.position, cycle_step.total, retry=True))
            session.conversation.clear()
            try:
                result = turn.run_turn(
                    session,
                    text,
                    provider=session.provider,
                    client=session.client,
                    ask=self.ask,
                    listener=self.listener,
                    tool_set=step,
                    cycle_step=cycle_step,
                    interrupt=self.interrupt,
                )
            except turn.TurnError as error:
                self.add(error.recorded)
                return Stop(step, "error", str(error), ends_session=error.ends_session)
            self.add(result.recorded)
            self.answer = result.text
            self.show(StepAnswered(step, result))
            if result.interrupted:
                return Stop(step, "interrupted", f"The step {step} was interrupted.")
            if result.limit_reached:
                return Stop(step, "limit", result.text)
            if session.permission_refusals > refusals:
                return Stop(step, "refused", f"A tool call of the step {step} was refused.")
            failed = [(run["id"], run["status"], run["error"]) for run in _failed_runs_since(session.conn, last_run)]
            if failed:
                return Stop(step, "run_failed", _runs_failed_message(step, failed))
            lacking = missing(step, self.progress())
            if ends_with_question(result.text):
                return Stop(step, "question", f"The step {step} ended with a question for the user.")
            if lacking is None:
                return None
            text = f"{message}\n\n{RETRY.format(missing=lacking)}"
        return Stop(step, "missing", f"The outcome of the step {step} is still missing after a retry: {lacking}.")

    def add(self, recorded: turn.Recorded) -> None:
        if self.counts is None:
            self.counts = {}
        for name, count in recorded:
            self.counts[name] = self.counts.get(name, 0) + count

    # Direct steps --------------------------------------------------------------------------------------------------

    def direct_step(self, step: str) -> Stop | None:
        p = self.progress()
        if step == "discover":
            roles, target = p.full_runs_missing, "all"
        else:
            roles = p.suite_runs_not_completed
            target = "suite"
        for role in roles:
            outcome = commands.run(
                self.session, target, role, ask=self.ask, interrupt=self.interrupt, listener=self.listener
            )
            self.show(StepRuns(step, outcome))
            stop = _run_stop(step, outcome)
            if stop is not None:
                return stop
        lacking = missing(step, self.progress())
        if lacking is not None:
            return Stop(step, "missing", f"The outcome of the step {step} is missing: {lacking}.")
        return None


def _run_stop(step: str, outcome: commands.RunOutcome) -> Stop | None:
    if outcome.error is not None:
        reason = "refused" if outcome.error.code == "denied" else "error"
        return Stop(step, reason, f"The run of the step {step} was not started: {outcome.error}")
    if outcome.interrupted:
        return Stop(step, "interrupted", f"The run of the step {step} was interrupted.")
    failed = [(row.run_id, row.status, row.error) for row in outcome.runs if row.status != "completed"]
    if failed:
        return Stop(step, "run_failed", _runs_failed_message(step, failed))
    return None


def _last_run_rowid(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM run").fetchone()[0]


def _failed_runs_since(conn: sqlite3.Connection, rowid: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, status, error FROM run WHERE rowid > ? AND status IN ('error', 'interrupted') ORDER BY rowid",
        (rowid,),
    ).fetchall()


def _runs_failed_message(step: str, runs: Sequence[tuple[str, str, str | None]]) -> str:
    """``runs`` are (ID, status, error) of the runs that did not complete."""
    details = "; ".join(f"{run_id} ended {status}" + (f": {error}" if error else "") for run_id, status, error in runs)
    return f"A run of the step {step} did not complete: {details}."
