"""SC-04: model credentials stay out of everything RetroAgent starts or writes (NFR-06, NFR-16).

Model credentials are set in the environment of ``retro``: a well-known key variable and the variable named by
``api_key_env`` of a profile of the user configuration. A generated test writes its whole environment to a file,
prints it and fails, so that the environment also reaches the run log, the JUnit XML and the failure messages. Then
the suite runs on both versions and the completion report is generated. The credentials are absent from the files
written by the test, from the run evidence, from ``tool_call`` and from the report; a variable that is not a
credential is present, which shows the environment was really written.
"""

import pytest
from fixtures.agent_session import write_user_config
from fixtures.example_project import project_copy, start
from fixtures.mcp_project import error_of

from retroagent.config import retro_home
from retroagent.memory import design
from retroagent.runtime import commands, permissions, turn

pytestmark = pytest.mark.network

SECRETS = {
    "GEMINI_API_KEY": "sc04-gemini-key-3f9a1c7e",
    "RETRO_SC04_MODEL_KEY": "sc04-profile-key-b2d84e10",
}
VISIBLE = ("RETRO_SC04_VISIBLE", "sc04-visible-value")
HOSTED_PROFILE = "  hosted:\n    provider: google\n    name: test-hosted\n    api_key_env: RETRO_SC04_MODEL_KEY\n"
NAME = "test_req_002_environment_of_the_test"


def dumping_test(directory) -> str:
    return (
        '"""SC-04: write the environment to a file, print it and fail, so that it reaches every piece of evidence."""\n'
        "\n"
        "import json\n"
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        f"def {NAME}():\n"
        "    environment = json.dumps(dict(os.environ), sort_keys=True)\n"
        f"    Path({str(directory)!r}, 'env-' + os.environ['RETRO_VERSION'] + '.json').write_text(environment)\n"
        "    print(environment)\n"
        "    assert False, environment\n"
    )


def files_under(path):
    return [p for p in path.rglob("*") if p.is_file()]


def assert_no_secret(text: str, where: str) -> None:
    for name, value in SECRETS.items():
        assert value not in text, f"{name} found in {where}"


def test_sc04_credentials_are_absent_from_test_files_logs_tool_calls_and_reports(
    tmp_path_factory, pip_cache, shop_after_design, monkeypatch
):
    dumps = tmp_path_factory.mktemp("dumps")
    with project_copy(tmp_path_factory, shop_after_design, pip_cache) as path:
        write_user_config(retro_home(), HOSTED_PROFILE)
        for name, value in [*SECRETS.items(), VISIBLE]:
            monkeypatch.setenv(name, value)
        with start(path, trust_commands=True, mode="auto") as session:
            assert "RETRO_SC04_MODEL_KEY" in session.config.credential_env_names
            (designed,) = [row["id"] for row in design.list_test_cases(session.conn, status="designed")]
            turn.call_tool(
                session,
                "test_runner__write_test",
                {"test_case_id": designed, "file": f"{NAME}.py", "test_name": NAME, "code": dumping_test(dumps)},
                ask=None,
            )
            # A call whose argument carries a credential: tool_call keeps it replaced.
            arguments = {"ids": [SECRETS["GEMINI_API_KEY"]]}
            error = error_of(lambda: turn.call_tool(session, "memory__get_requirements", arguments, ask=None))
            assert error.code == "not_found"

            outcome = commands.run(session, "suite", "both", ask=lambda request: permissions.ONCE)
            assert [run.status for run in outcome.runs] == ["completed", "completed"]
            prepared = turn.call_tool(session, "reports__prepare_report", {"type": "completion"}, ask=None)
            rendered = turn.call_tool(
                session, "reports__render_report", {"report_id": prepared["report_id"], "sections": {}}, ask=None
            )

            rows = [dict(row) for row in session.conn.execute("SELECT * FROM tool_call WHERE session_id = ?",
                                                              (session.id,))]  # fmt: skip
            report_dir = (
                path
                / session.conn.execute("SELECT path FROM report WHERE id = ?", (prepared["report_id"],)).fetchone()[
                    "path"
                ]
            )
            run_dirs = [path / ".retro" / "runs" / run.run_id for run in outcome.runs]

        # The files written by the test: the environment was written, without the credentials.
        written = sorted(p.name for p in dumps.iterdir())
        assert written == ["env-base.json", "env-candidate.json"]
        for dump in dumps.iterdir():
            text = dump.read_text(encoding="utf-8")
            assert VISIBLE[1] in text and '"RETRO_RUN_ID"' in text
            assert_no_secret(text, dump.name)
            assert "GEMINI_API_KEY" not in text and "RETRO_SC04_MODEL_KEY" not in text

        # The run evidence: run log, service log and JUnit XML, which hold the printed environment.
        for run_dir in run_dirs:
            evidence = files_under(run_dir)
            assert {"run.log", "service.log", "junit-1.xml"} <= {p.name for p in evidence}
            assert any(VISIBLE[1] in p.read_text(encoding="utf-8", errors="replace") for p in evidence)
            for file in evidence:
                assert_no_secret(file.read_text(encoding="utf-8", errors="replace"), str(file))

        # tool_call: every column of every row.
        assert any("***" in (row["arguments"] or "") for row in rows)
        for row in rows:
            assert_no_secret(" ".join(str(value) for value in row.values()), f"tool_call {row['id']}")

        # The report.
        assert rendered and files_under(report_dir)
        for file in files_under(report_dir):
            assert_no_secret(file.read_text(encoding="utf-8", errors="replace"), str(file))
