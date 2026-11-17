"""A run against one version: ``test_runner.run_tests`` as a plain function (project-contract.md, Test execution).

Results come only from the JUnit XML of the run (ADR-0010). A step that ends the run before any valid JUnit XML
gives blocked executions with its reason. The first attempt gives the result (INV-04), and reruns never change
the outcome of the run. Evidence is kept in ``.retro/runs/<run_id>/``: ``run.log``, ``service.log`` and one
JUnit XML per round, ``junit-<n>.xml``, where ``n`` is also the number of the attempts of that round.

A generated test that cannot be loaded (project-contract.md, Generated tests): when the JUnit XML of round 1 reports
a generated file as a load error, its test cases get attempt 1 with result ``error`` and the message of the entry,
the file is removed from the worktree for the rest of the run, the XML is kept as ``junit-1.load-error-<k>.xml``, and
the command of round 1 runs once more; at most as many times as there are generated files. Those test cases are not
rerun. A load error of a file that is not generated is never registered as a test case; the ``error`` of the run
names the file.
"""

import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from retroagent.config import Config, ConfigError, PlaceholderError, cache_dir, expand, load_config
from retroagent.memory import connect, design, execution, transaction
from retroagent.memory.db import utc_now
from retroagent.servers.errors import ToolError
from retroagent.servers.test_runner import generated, junit, process, service, worktree

VERSIONS = ("base", "candidate")
SCOPES = ("all", "suite", "selected")


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    counts: dict[str, int]  # executions by status and by result


def run_tests(
    project_dir: str | Path,
    *,
    session_id: int,
    version: str,
    scope: str,
    base_ref: str | None,
    base_commit: str | None,
    candidate_ref: str | None,
    candidate_commit: str | None,
    commands_approved: bool,
    test_case_ids: list[str] | None = None,
) -> RunSummary:
    """Create a run of ``scope`` against the ``base`` or ``candidate`` version and execute it.

    The refs and commits are the session versions; a version that is not set is ``None``. Raises ``ToolError``; a
    failed setup, service or test command gives a run with that status, not an error.
    ``KeyboardInterrupt`` is raised again once the interrupted run is stored.
    """
    if not commands_approved:
        raise ToolError("denied", "the setup, test, selection and service commands and tests.env are not approved")
    if version not in VERSIONS:
        raise ToolError("invalid_argument", f"version must be one of {', '.join(VERSIONS)}")
    if scope not in SCOPES:
        raise ToolError("invalid_argument", f"scope must be one of {', '.join(SCOPES)}")
    if (scope == "selected") != bool(test_case_ids):
        raise ToolError("invalid_argument", "test_case_ids is required with scope selected, and only with it")
    project_dir = Path(project_dir).resolve()
    try:
        config = load_config(project_dir)
    except ConfigError as error:
        raise ToolError("invalid_state", str(error)) from error
    if not config["tests.command"]:
        raise ToolError("invalid_state", "tests.command is not configured")
    _check_placeholders(config)
    ref, commit = (base_ref, base_commit) if version == "base" else (candidate_ref, candidate_commit)
    if commit is None:
        raise ToolError("invalid_state", f"the {version} version of the session is not set")
    if scope == "suite" and None in (base_commit, candidate_commit):
        raise ToolError("invalid_state", "the current suite needs both session versions, and one is not set")

    conn = connect(project_dir)
    try:
        scope_cases, suite_id = _scope(conn, scope, test_case_ids, base_commit, candidate_commit)
        run = _Run(conn, config, session_id=session_id, version=version, scope=scope, ref=ref, commit=commit)
        return run.execute(scope_cases, suite_id)
    finally:
        conn.close()


def _scope(conn, scope, test_case_ids, base_commit, candidate_commit) -> tuple[list[sqlite3.Row] | None, int | None]:
    """The test cases a suite or selected run executes, and the suite. None for a full run."""
    if scope == "all":
        return None, None
    if scope == "suite":
        suite_id = design.current_suite(conn, base_commit, candidate_commit)
        if suite_id is None:
            raise ToolError("invalid_state", "there is no current suite for these versions")
        rows = [row for row in design.suite_test_cases(conn, suite_id) if _active_implemented(row)]
        if not rows:
            raise ToolError("invalid_state", "the current suite has no implemented, active test case")
        return rows, suite_id
    rows = []
    for test_case_id in dict.fromkeys(test_case_ids):
        row = design.get_test_case(conn, test_case_id)
        if row is None:
            raise ToolError("not_found", f"test case {test_case_id} does not exist")
        rows.append(row)
    if not any(_active_implemented(row) for row in rows):
        raise ToolError("invalid_state", "none of the selected test cases is implemented and active")
    refused = [row["id"] for row in rows if not _active_implemented(row)]
    if refused:
        raise ToolError("invalid_argument", f"not implemented and active: {', '.join(refused)}")
    return rows, None


def _why(interruption: KeyboardInterrupt) -> str:
    """The reason of an interruption: its message, such as "the server was stopped", or the user."""
    return str(interruption) or "interrupted by the user"


def _active_implemented(row: sqlite3.Row) -> bool:
    return row["status"] == "implemented" and row["retired_at"] is None


def _revision(row: sqlite3.Row) -> int | None:
    """``test_revision`` of an execution: the revision of a generated test; None for a project test."""
    return row["revision"] if row["origin"] == "designed" else None


def _test_name(row: sqlite3.Row) -> str:
    return (row["test_id"] or row["implementation"]).rpartition("::")[2]


# Placeholders each key may use (configuration.md, Placeholders).
_STEP_PLACEHOLDERS = {
    "tests.setup": (),
    "service.start": (),
    "service.url": (),
    "tests.command": ("junit",),
    "tests.select": ("junit", "names"),
}


def _check_placeholders(config: Config) -> None:
    """Refuse a placeholder that has no value in its command before anything runs, for example ``{names}``."""
    common = {"worktree": "", "run_dir": "", "cache_dir": ""}
    if config["service.start"]:
        common["port"] = ""
    for key, extra in _STEP_PLACEHOLDERS.items():
        if config[key] and (config["service.start"] or not key.startswith("service.")):
            try:
                expand(config[key], {**common, **dict.fromkeys(extra, "")})
            except PlaceholderError as error:
                raise ToolError("invalid_argument", f"{key}: {error}") from error


class _Stop(Exception):
    """A step ended the run before any valid JUnit XML: the status of the run and the reason of its executions."""

    def __init__(self, status: str, reason: str, error: str, exit_code: int | None = None):
        self.status, self.reason, self.error, self.exit_code = status, reason, error, exit_code
        super().__init__(error)


@dataclass
class _Item:
    """A test case of the run, the entry of the first round that reports it, and its attempts."""

    test_case_id: str | None  # None for a test found by this full run: registered when the run is stored
    entry: junit.Entry | None  # None when the JUnit XML does not report it
    test_revision: int | None
    bind_to: str | None = None  # test_id of a generated test reported for the first time
    attempts: list[dict] = field(default_factory=list)


def _attempt(number: int, entry: junit.Entry) -> dict:
    return {"number": number, "result": entry.outcome, "duration": entry.duration, "failure_message": entry.message}


class _Run:
    def __init__(self, conn, config: Config, *, session_id: int, version: str, scope: str, ref: str, commit: str):
        self.conn, self.config = conn, config
        self.project_dir = config.project_dir
        self.session_id, self.version, self.scope, self.ref, self.commit = session_id, version, scope, ref, commit
        self.timeout = config["tests.timeout"]
        self.service: object | None = None
        self.step = "start"
        self.generated_files: dict[str, list[sqlite3.Row]] = {}  # generated files in the worktree, with their rows
        self.broken: dict[str, junit.Entry] = {}  # test case ID -> the load error of its generated file
        self.project_load_errors: dict[str, str] = {}  # module path -> first line of the message

    def execute(self, scope_cases: list[sqlite3.Row] | None, suite_id: int | None) -> RunSummary:
        self.scope_cases = scope_cases
        active = design.active_implemented_test_cases(self.conn)
        self.generated_rows = [row for row in active if row["origin"] == "designed"]
        # A run that ends early blocks the test cases of its scope; a full run, every active implemented one.
        self.blocked_rows = scope_cases if scope_cases is not None else active
        self.first_names = None
        if scope_cases is not None and self.config["tests.select"]:
            self.first_names = [_test_name(row) for row in scope_cases]
        try:
            self.worktree = worktree.create(self.project_dir, self.commit)
        except worktree.WorktreeError as error:
            raise ToolError("execution_failed", str(error)) from error
        try:
            try:
                self._start(suite_id)
                self._steps()
            except BaseException as error:
                self._fail(error)
                raise
            return self._summary()
        finally:
            if self.service is not None:
                service.stop(self.service)
            worktree.remove(self.project_dir, self.worktree)

    def _start(self, suite_id: int | None) -> None:
        values = {"worktree": str(self.worktree)}
        cache = cache_dir(self.project_dir)
        cache.mkdir(parents=True, exist_ok=True)
        values["cache_dir"] = str(cache)
        extra_env = dict(self.config["tests.env"])
        if self.config["service.start"]:
            values["port"] = service.free_port()
            self.base_url = expand(self.config["service.url"], values)
            extra_env["RETRO_BASE_URL"] = self.base_url
        with transaction(self.conn):
            self.run_id = execution.start_run(
                self.conn,
                version_role=self.version,
                ref=self.ref,
                commit=self.commit,
                scope=self.scope,
                command="",
                session_id=self.session_id,
                suite_id=suite_id,
            )
            self.run_dir = self.project_dir / ".retro" / "runs" / self.run_id
            self.values = {**values, "run_dir": str(self.run_dir)}
            execution.set_command(self.conn, self.run_id, self._command(1, self.first_names))
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.log, self.service_log = self.run_dir / "run.log", self.run_dir / "service.log"
        self.log.touch()
        self.service_log.touch()
        extra_env.update(RETRO_RUN_ID=self.run_id, RETRO_VERSION=self.version)
        self.env = process.clean_environment(self.config.credential_env_names, extra_env)

    def _steps(self) -> None:
        try:
            entries, exit_code = self._first_round()
        except _Stop as stop:
            self._store_blocked(stop.status, stop.reason, stop.error, stop.exit_code)
            return
        except KeyboardInterrupt as error:
            self._store_blocked("interrupted", "interrupted", f"{self.step}: {_why(error)}")
            raise
        items = self._match(entries)
        interrupted = self._reruns(items)
        self._store(items, exit_code)
        if interrupted:
            raise KeyboardInterrupt

    def _first_round(self) -> tuple[list[junit.Entry], int | None]:
        if self.config["tests.setup"]:
            self.step = "setup"
            outcome = self._run_command(expand(self.config["tests.setup"], self.values))
            if outcome.timed_out:
                raise _Stop("error", "setup_failed", f"setup: stopped after {self.timeout} seconds")
            if outcome.exit_code != 0:
                raise _Stop("error", "setup_failed", f"setup: exit code {outcome.exit_code}")
        self.step = "copy of generated tests"
        missing = generated.copy_generated(
            self.project_dir,
            self.worktree,
            self.config["tests.generated_dir"],
            [row["implementation"] for row in self.generated_rows],
        )
        for file in missing:
            self._note(f"generated test {file} is missing from .retro/tests/")
        for row in self.generated_rows:
            file = row["implementation"].rpartition("::")[0]
            if file not in missing:
                self.generated_files.setdefault(file, []).append(row)
        if self.config["service.start"]:
            self.step = "service"
            command = expand(self.config["service.start"], self.values)
            self.service = service.start(command, cwd=self.worktree, env=self.env, log=self.service_log)
            url = service.ready_url(self.base_url, self.config["service.ready_path"])
            ready_timeout = self.config["service.ready_timeout"]
            if not service.wait_ready(url, timeout=ready_timeout, service=self.service):
                message = f"service: {url} did not answer within {ready_timeout} seconds"
                raise _Stop("error", "service_not_ready", message)
        self.step = "test command"
        outcome, entries, problem = self._first_round_loading()
        if outcome.timed_out:
            raise _Stop("interrupted", "timeout", f"test command: stopped after {self.timeout} seconds")
        if entries is None:
            raise _Stop("error", "no_junit", f"test command: {problem}", outcome.exit_code)
        return entries, outcome.exit_code

    def _command(self, number: int, names: list[str] | None) -> str:
        values = {**self.values, "junit": str(self.run_dir / f"junit-{number}.xml")}
        if names is None:
            return expand(self.config["tests.command"], values)
        values["names"] = generated.names(names, self.config["tests.select_separator"])
        return expand(self.config["tests.select"], values)

    def _run_command(self, command: str) -> process.Outcome:
        return process.run(command, cwd=self.worktree, env=self.env, timeout=self.timeout, log=self.log)

    def _round(self, number: int, names: list[str] | None):
        """Run the test command of one round: its outcome, and its entries or None and why there are none."""
        pattern = self.config["tests.junit"]
        if pattern != "{junit}":
            for path in self.worktree.glob(pattern):
                if path.is_file():
                    path.unlink()
        outcome = self._run_command(self._command(number, names))
        if outcome.timed_out:
            return outcome, None, f"stopped after {self.timeout} seconds"
        files = [self.run_dir / f"junit-{number}.xml"]
        if pattern != "{junit}":
            files = []
            for path in sorted(self.worktree.glob(pattern)):
                if path.is_file():
                    copy = self.run_dir / f"junit-{number}" / path.relative_to(self.worktree)
                    copy.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, copy)
                    files.append(copy)
        try:
            return outcome, junit.parse(files), None
        except junit.JunitError as error:
            return outcome, None, f"no valid JUnit XML: {error}"

    def _first_round_loading(self):
        """Round 1, run again without each generated test that could not be loaded (project-contract.md, Generated
        tests). Returns what ``_round`` returns for the last command of the round."""
        remaining = dict(self.generated_files)
        repeats = 0
        while True:
            outcome, entries, problem = self._round(1, self.first_names)
            if entries is None:
                return outcome, None, problem
            broken: dict[str, junit.Entry] = {}
            for entry in entries:
                if not entry.is_load_error:
                    continue
                file = generated.load_error_file(entry.name, remaining, self.config["tests.generated_dir"])
                if file is None:
                    self._project_load_error(entry)
                else:
                    broken.setdefault(file, entry)
            if not broken or repeats >= len(self.generated_files):
                return outcome, entries, None
            repeats += 1
            kept = self._keep_junit(1, repeats)
            for file, entry in broken.items():
                generated.remove_generated(self.worktree, self.config["tests.generated_dir"], file)
                cases = [row["id"] for row in remaining.pop(file)]
                for test_case_id in cases:
                    self.broken[test_case_id] = entry
                self._note(
                    f"round 1: generated test {file} ({', '.join(cases)}) could not be loaded; it is removed for the"
                    f" rest of the run, {kept} is kept, and the command runs again"
                )

    def _project_load_error(self, entry: junit.Entry) -> None:
        """Name a test file of the project that could not be loaded, with the line of the message that says why: the
        last exception line of pytest (``E   ImportError: ...``), or else the first line."""
        lines = [line.strip() for line in (entry.message or "no message").splitlines() if line.strip()]
        raised = [line.removeprefix("E").strip() for line in lines if line.startswith("E ")]
        self.project_load_errors.setdefault(entry.name, raised[-1] if raised else lines[0])

    def _keep_junit(self, number: int, repeat: int) -> str:
        """Rename the JUnit XML of round ``number`` before its command runs again; returns the name it is kept as."""
        suffix = ".xml" if self.config["tests.junit"] == "{junit}" else ""
        source = self.run_dir / f"junit-{number}{suffix}"
        target = self.run_dir / f"junit-{number}.load-error-{repeat}{suffix}"
        if source.exists():
            source.rename(target)
        return target.name

    def _match(self, entries: list[junit.Entry]) -> list[_Item]:
        """Test cases of the run and their entries (project-contract.md, Test identity and Discovery). A load-error
        entry is not a test: a generated test case of a file that could not be loaded gets that entry; other load
        errors are named in the ``error`` of the run."""
        for entry in entries:
            if entry.is_load_error:  # the generated files that could not be loaded are no longer in the worktree
                self._project_load_error(entry)
        entries = [entry for entry in entries if not entry.is_load_error]
        known = {row["test_id"]: row for row in self.conn.execute("SELECT * FROM test_case WHERE test_id IS NOT NULL")}
        generated_names = {
            row["implementation"].rpartition("::")[2]
            for row in self.conn.execute("SELECT implementation FROM test_case WHERE origin = 'designed'")
            if row["implementation"]
        }
        unbound = self.generated_rows if self.scope_cases is None else self.scope_cases
        bound: dict[str, sqlite3.Row] = {}
        for row in unbound:
            if row["origin"] == "designed" and row["test_id"] is None:
                entry = generated.bind(entries, row["implementation"])
                if entry is not None and entry.test_id not in known and entry.test_id not in bound:
                    bound[entry.test_id] = row
        bound_ids = {row["id"]: test_id for test_id, row in bound.items()}

        items = []
        if self.scope_cases is not None:
            reported = {entry.test_id: entry for entry in entries}  # entries outside the scope are ignored
            for row in self.scope_cases:
                if row["id"] in self.broken:
                    items.append(_Item(row["id"], self.broken[row["id"]], _revision(row)))
                    continue
                test_id = row["test_id"] or bound_ids.get(row["id"])
                items.append(_Item(row["id"], reported.get(test_id), _revision(row), bound_ids.get(row["id"])))
        else:
            seen = set()
            for entry in entries:
                row = bound.get(entry.test_id) or known.get(entry.test_id)
                if row is None:
                    if entry.name not in generated_names:  # an unbound generated test is never a project test
                        items.append(_Item(None, entry, None))
                    continue
                if row["origin"] == "designed" and row["retired_at"] is not None:
                    continue  # its generated test is no longer run
                items.append(_Item(row["id"], entry, _revision(row), bound_ids.get(row["id"])))
                seen.add(row["id"])
            for row in self.generated_rows:
                if row["id"] not in seen:
                    items.append(_Item(row["id"], self.broken.get(row["id"]), _revision(row)))
        for item in items:
            if item.entry is not None and item.entry.outcome != "skipped":
                item.attempts.append(_attempt(1, item.entry))
        return items

    def _reruns(self, items: list[_Item]) -> bool:
        """Rerun the test cases whose first attempt did not pass. True when the user interrupted a round."""
        # A test case whose file could not be loaded is not rerun: it would give the same error every time.
        rerun = [
            item
            for item in items
            if item.entry is not None
            and item.entry.outcome in ("failed", "error")
            and item.test_case_id not in self.broken
        ]
        if not rerun:
            return False
        names = [item.entry.name for item in rerun] if self.config["tests.select"] else None
        for number in range(2, self.config["tests.reruns"] + 2):
            self.step = f"rerun round {number}"
            try:
                _, entries, problem = self._round(number, names)
            except KeyboardInterrupt as error:
                self._note(f"round {number}: {_why(error)}; the run keeps the attempts stored so far")
                return True
            if entries is None:
                self._note(f"round {number}: {problem}; no attempt is stored for it and no further round runs")
                return False
            for entry in entries:
                if entry.is_load_error:
                    self._project_load_error(entry)
            reported = {entry.test_id: entry for entry in entries if not entry.is_load_error}
            for item in rerun:
                entry = reported.get(item.entry.test_id)
                if entry is not None and entry.outcome != "skipped":
                    item.attempts.append(_attempt(number, entry))
        return False

    def _store(self, items: list[_Item], exit_code: int | None) -> None:
        pattern = self.config["tests.junit"]
        junit_path = f".retro/runs/{self.run_id}/" + ("junit-1.xml" if pattern == "{junit}" else "junit-1/")
        with transaction(self.conn):
            execution.set_junit_path(self.conn, self.run_id, junit_path)
            for item in items:
                test_case_id = item.test_case_id
                if test_case_id is None:
                    test_case_id = design.add_project_suite_test_case(
                        self.conn, test_id=item.entry.test_id, implementation=item.entry.implementation
                    )
                if item.bind_to is not None:
                    design.bind_test_id(self.conn, test_case_id, item.bind_to)
                record = {"run_id": self.run_id, "test_case_id": test_case_id, "test_revision": item.test_revision}
                if item.entry is None:
                    execution.record_test_execution(self.conn, **record, status="blocked", reason="not_reported")
                elif item.entry.outcome == "skipped":
                    execution.record_test_execution(self.conn, **record, status="skipped", reason=item.entry.message)
                else:
                    execution.record_test_execution(
                        self.conn,
                        **record,
                        status="executed",
                        result=item.entry.outcome,
                        duration=item.entry.duration,
                        attempts=item.attempts,
                    )
            execution.finish_run(
                self.conn, self.run_id, status="completed", exit_code=exit_code, error=self._load_errors()
            )

    def _load_errors(self) -> str | None:
        """The ``error`` of a completed run: the test files of the project that could not be loaded."""
        if not self.project_load_errors:
            return None
        return "; ".join(
            f"test file {name} could not be loaded: {line}" for name, line in self.project_load_errors.items()
        )

    def _store_blocked(self, status: str, reason: str, error: str, exit_code: int | None = None) -> None:
        if hasattr(self, "log"):
            self._note(error)
        with transaction(self.conn):
            for row in self.blocked_rows:
                execution.record_test_execution(
                    self.conn,
                    run_id=self.run_id,
                    test_case_id=row["id"],
                    status="blocked",
                    reason=reason,
                    test_revision=_revision(row),
                )
            execution.finish_run(self.conn, self.run_id, status=status, exit_code=exit_code, error=error)

    def _fail(self, error: BaseException) -> None:
        """A run left ``running`` by an unexpected error ends as ``error``, and by an interruption outside the
        rounds as ``interrupted``; it is never left running."""
        run_id = getattr(self, "run_id", None)
        row = execution.get_run(self.conn, run_id) if run_id else None
        if row is None or row["status"] != "running":
            return
        if isinstance(error, KeyboardInterrupt):
            self._store_blocked("interrupted", "interrupted", f"{self.step}: {_why(error)}")
            return
        message = f"{self.step}: {type(error).__name__}: {error}"
        if hasattr(self, "log"):
            self._note(message)
        execution.finish_run(self.conn, run_id, status="error", error=message)

    def _note(self, line: str) -> None:
        process.note(self.log, f"[{utc_now()}] {line}")

    def _summary(self) -> RunSummary:
        counts = execution.execution_counts(self.conn, self.run_id)
        return RunSummary(self.run_id, execution.get_run(self.conn, self.run_id)["status"], counts)
