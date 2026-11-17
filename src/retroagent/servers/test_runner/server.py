"""Server ``test_runner``: writes test code and executes tests (mcp-tools.md, Server ``test_runner``).

Run as ``python -m retroagent.servers.test_runner.server --project <dir> --session <id>``. When the server is
stopped during a run, the run ends its process groups and is stored as ``interrupted`` before the server exits
(runtime.md, Robustness).

``write_test`` writes the code of a generated test to ``.retro/tests/`` and records it in one step: the file is
written inside the transaction that sets the test case ``implemented`` (revision 1) or adds a revision, and a failure
of either leaves the file and the record as they were. ``get_evidence`` returns what a run stored: the attempts of
its executions, read from memory, and its logs, paged (mcp-tools.md, Large output).
"""

import sqlite3

from retroagent.memory import InvariantViolation, design, execution, transaction
from retroagent.servers.errors import ToolError
from retroagent.servers.serving import Context, Tool, page, schema, serve
from retroagent.servers.test_runner import generated, runner

TEXT = {"type": "string", "minLength": 1}


def run_tests(context: Context, version: str, scope: str, test_case_ids: list[str] | None = None) -> dict:
    with context.connection() as conn:
        versions = context.versions(conn)
    base, candidate = versions["base"], versions["candidate"]
    summary = runner.run_tests(
        context.project_dir,
        session_id=context.session_id,
        version=version,
        scope=scope,
        base_ref=base.ref if base else None,
        base_commit=base.commit if base else None,
        candidate_ref=candidate.ref if candidate else None,
        candidate_commit=candidate.commit if candidate else None,
        # The approval of the project commands is enforced by the runtime before dispatch (mcp-tools.md, Mode,
        # permissions and approvals); no other client of this server is supported (ADR-0026).
        commands_approved=True,
        test_case_ids=test_case_ids,
    )
    return {
        "run_id": summary.run_id,
        "status": summary.status,
        "counts": summary.counts,
        "closed_defects": summary.closed_defects,
    }


# write_test ------------------------------------------------------------------------------------------------------


def write_test(
    context: Context, test_case_id: str, file: str, test_name: str, code: str, fields: dict | None = None
) -> dict:
    with context.connection() as conn:
        row = design.get_test_case(conn, test_case_id)
        if row is None:
            raise ToolError("not_found", f"test case {test_case_id!r} does not exist")
        if row["origin"] != "designed":
            raise ToolError(
                "invalid_state", f"{test_case_id} is a test of the project ({row['origin']}): its code is not generated"
            )
        if row["retired_at"] is not None:
            raise ToolError("invalid_state", f"test case {test_case_id} is retired")
        rewrite = row["status"] == "implemented"
        if fields is not None and not rewrite:
            raise ToolError("invalid_argument", "fields is accepted only in a rewrite; the design is still open")
        try:
            relative = generated.normalize_file(file)
            implementation = f"{relative}::{test_name}"
            if rewrite and implementation != row["implementation"]:
                raise generated.GeneratedError(
                    f"a rewrite keeps the file and the test name of {test_case_id}: {row['implementation']} (INV-17)"
                )
            requirement_ids = _traced_after(conn, test_case_id, fields)
            generated.check_test_name(test_name, requirement_ids)
            path = generated.target(context.project_dir, relative)
            if not rewrite:
                _check_unique(conn, test_case_id, relative, test_name)
                if path.exists():
                    raise generated.GeneratedError(
                        f".retro/tests/{relative} already exists and belongs to no test case; choose another file"
                    )
        except generated.GeneratedError as error:
            raise ToolError("invalid_argument", str(error)) from error
        previous = path.read_bytes() if path.exists() else None
        written = False
        try:
            with transaction(conn):
                if rewrite:
                    revision = design.rewrite_generated_test(conn, test_case_id, implementation, fields)
                else:
                    design.mark_implemented(conn, test_case_id, implementation)
                    revision = 1
                generated.write(path, code)
                written = True
        except BaseException as error:
            if written:  # the record was not committed: the file goes back to what it was
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(previous)
            if isinstance(error, InvariantViolation) and str(error).startswith("INV-17"):
                raise ToolError("invalid_argument", str(error)) from error
            raise
    return {"test_case_id": test_case_id, "implementation": implementation, "revision": revision}


def _traced_after(conn: sqlite3.Connection, test_case_id: str, fields: dict | None) -> list[str]:
    """The requirements the test case traces once the call is applied: ``fields.requirement_ids`` replaces the design
    links; links found in the test name stay."""
    links = design.test_case_requirements(conn, test_case_id)
    if fields is None or "requirement_ids" not in fields:
        return [link["requirement_id"] for link in links]
    names = [link["requirement_id"] for link in links if link["link"] == "name"]
    return list(dict.fromkeys([*fields["requirement_ids"], *names]))


def _check_unique(conn: sqlite3.Connection, test_case_id: str, file: str, test_name: str) -> None:
    """INV-17: the file and the test name are not used by another generated test."""
    for other in conn.execute(
        "SELECT id, implementation FROM test_case WHERE origin = 'designed' AND implementation IS NOT NULL AND id != ?",
        (test_case_id,),
    ):
        other_file, _, other_name = other["implementation"].rpartition("::")
        if other_file == file:
            raise generated.GeneratedError(f"the file {file} is used by the generated test of {other['id']} (INV-17)")
        if other_name == test_name:
            raise generated.GeneratedError(f"the test name {test_name} is used by {other['id']} (INV-17)")


# get_evidence ----------------------------------------------------------------------------------------------------


def get_evidence(context: Context, run_id: str, test_case_id: str | None = None, start_line: int = 1) -> dict:
    with context.connection() as conn:
        run = execution.get_run(conn, run_id)
        if run is None:
            raise ToolError("not_found", f"run {run_id!r} does not exist")
        executions = execution.list_executions(conn, run_id)
        if test_case_id is not None:
            if design.get_test_case(conn, test_case_id) is None:
                raise ToolError("not_found", f"test case {test_case_id!r} does not exist")
            executions = [row for row in executions if row["test_case_id"] == test_case_id]
            if not executions:
                raise ToolError("not_found", f"test case {test_case_id} has no execution in {run_id}")
        else:
            executions = [row for row in executions if row["status"] == "blocked" or row["result"] in _FAILED]
        lines = _run_lines(run)
        lines += _execution_lines(conn, executions)
        limit = context.result_limit(conn)
    lines += _log_lines(context, run)
    text, meta = page("\n".join(lines) + "\n", start_line, limit)
    return {"run_id": run_id, "evidence": text, **meta}


_FAILED = ("failed", "error")


def _run_lines(run: sqlite3.Row) -> list[str]:
    lines = [
        f"Run {run['id']} against {run['version_role']} {run['ref']} ({run['commit']}), scope {run['scope']},"
        f" status {run['status']}.",
        f"Test command: {run['command']}",
        f"Exit code: {'none' if run['exit_code'] is None else run['exit_code']}.",
    ]
    if run["error"]:
        lines.append(f"Error: {run['error']}")
    return lines


def _execution_lines(conn: sqlite3.Connection, executions: list[sqlite3.Row]) -> list[str]:
    lines = ["", f"## Executions ({len(executions)})"]
    if not executions:
        lines.append("No execution failed or was blocked.")
    for row in executions:
        test_case = design.get_test_case(conn, row["test_case_id"])
        described = row["status"]
        if row["result"]:
            described += f", result {row['result']}"
        if row["reason"]:
            described += f", reason {row['reason']}"
        if row["test_revision"] is not None:
            described += f", revision {row['test_revision']}"
        lines += ["", f"### {row['test_case_id']} {test_case['implementation'] or test_case['title']}: {described}"]
        for attempt in execution.list_attempts(conn, row["id"]):
            duration = "" if attempt["duration"] is None else f", {attempt['duration']:.3f} s"
            lines.append(f"Attempt {attempt['number']}: {attempt['result']}{duration}")
            if attempt["failure_message"]:
                lines.append(attempt["failure_message"].rstrip("\n"))
    return lines


def _log_lines(context: Context, run: sqlite3.Row) -> list[str]:
    lines = []
    directory = context.project_dir / run["evidence_dir"]
    for name, always in (("run.log", True), ("service.log", False)):
        path = directory / name
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        if text or always:
            lines += ["", f"## {name} ({run['evidence_dir'].rstrip('/')}/{name})", text.rstrip("\n") or "(empty)"]
    return lines


TOOLS = [
    Tool(
        "run_tests",
        "Run tests against the base or candidate version and store the results from the JUnit XML. Scope all runs "
        "every test and discovers the project tests; suite runs the current suite; selected runs test_case_ids. "
        "Returns the run ID, its status, counts and the defects it closed.",
        schema(
            {
                "version": {
                    "type": "string",
                    "enum": ["base", "candidate"],
                    "description": "Which session version to test.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["suite", "all", "selected"],
                    "description": "suite, all or selected.",
                },
                "test_case_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "Only with scope selected: implemented test cases such as TC-004.",
                },
            },
            ("version", "scope"),
        ),
        run_tests,
    ),
    Tool(
        "write_test",
        "Write the code of a designed test case to .retro/tests/ and set it implemented (revision 1). For an "
        "implemented generated test, rewrite its code: same file and test name, a new revision.",
        schema(
            {
                "test_case_id": {**TEXT, "description": "A designed test case, or a generated one to rewrite."},
                "file": {**TEXT, "description": "Path relative to .retro/tests/, named so the framework finds it."},
                "test_name": {
                    **TEXT,
                    "description": "Test function name: test_req_<NNN>_<description> when it traces a requirement.",
                },
                "code": {**TEXT, "description": "Full content of the file: one test function, not parametrized."},
                "fields": {
                    "type": "object",
                    "minProperties": 1,
                    "additionalProperties": False,
                    "description": "Only in a rewrite: design fields that change with the code.",
                    "properties": {
                        "preconditions": {"type": "array", "items": TEXT, "description": "Replaces the preconditions."},
                        "input_data": {
                            "type": "array",
                            "description": "Replaces the input data: each name with a concrete value, as text.",
                            "items": schema(
                                {
                                    "name": {**TEXT, "description": "Input name."},
                                    "value": {**TEXT, "description": "Concrete value, as text."},
                                },
                                ("name", "value"),
                            ),
                        },
                        "steps": {"type": "array", "minItems": 1, "items": TEXT, "description": "Replaces the steps."},
                        "expected_result": {**TEXT, "description": "Exact observable outcome."},
                        "requirement_ids": {
                            "type": "array",
                            "items": TEXT,
                            "description": "Replaces the traced requirements; links found in the test name stay.",
                        },
                    },
                },
            },
            ("test_case_id", "file", "test_name", "code"),
        ),
        write_test,
    ),
    Tool(
        "get_evidence",
        "Get the evidence of a run: each failed or blocked execution with the failure message of every attempt, "
        "then the run log. Long evidence comes in parts: when truncated is true, call again with start_line.",
        schema(
            {
                "run_id": {**TEXT, "description": "Run ID, such as RUN-0002."},
                "test_case_id": {**TEXT, "description": "Only the execution of this test case, whatever its status."},
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "First line to return. Default 1. When a result says truncated, call again with "
                    "its next_line.",
                },
            },
            ("run_id",),
        ),
        get_evidence,
    ),
]


if __name__ == "__main__":
    serve("test_runner", TOOLS)
