"""Server ``test_runner``: executes tests (mcp-tools.md, Server ``test_runner``).

Slice 3 exposes ``run_tests`` only. Run as ``python -m retroagent.servers.test_runner.server --project <dir>
--session <id>``. When the server is stopped during a run, the run ends its process groups and is stored as
``interrupted`` before the server exits (runtime.md, Robustness).
"""

from retroagent.servers.serving import Context, Tool, schema, serve
from retroagent.servers.test_runner import runner


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
    return {"run_id": summary.run_id, "status": summary.status, "counts": summary.counts}


TOOLS = [
    Tool(
        "run_tests",
        "Run tests against the base or candidate version and store the results from the JUnit XML. Scope all runs "
        "every test and discovers the project tests; suite runs the current suite; selected runs test_case_ids. "
        "Returns the run ID, its status and counts.",
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
]


if __name__ == "__main__":
    serve("test_runner", TOOLS)
