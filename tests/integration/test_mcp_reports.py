"""The ``reports`` server through a real server process and the real client, on the records of the reference scenario:
the result of each tool and each error code it can return (mcp-tools.md, Server ``reports``)."""

from fixtures.mcp_project import dump, error_of, reports_server

from retroagent.memory import sessions

SECTIONS = {"conclusions": "Do not release.", "summary": "A summary."}


def code(client, tool: str, arguments: dict) -> str:
    return error_of(lambda: client.call("reports", tool, arguments)).code


def count(session, table: str) -> int:
    return session.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# evaluate ------------------------------------------------------------------------------------------------------------


def test_evaluate_returns_the_values_as_the_report_shows_them_and_stores_the_evaluation(reference):
    session, scenario = reference
    with reports_server(session) as client:
        result = client.call("reports", "evaluate")
    assert (result["run_id"], result["baseline_run_id"]) == (scenario.evaluated_run, scenario.baseline_run)
    assert (result["full_base_run_id"], result["full_candidate_run_id"]) == (
        scenario.full_base_run,
        scenario.full_candidate_run,
    )
    assert result["analysis_id"] == scenario.analysis_id and result["decision"] == "do_not_release"
    assert result["reasons"] == [
        "EC-01 Product pass rate: threshold at least 90.0%, value 88.5%.",
        "EC-05 High defects: threshold at most 0, value 1.",
        "EC-09 New failures: threshold at most 0, value 1.",
    ]
    assert result["conditions"] == []
    criteria = {c["id"]: c for c in result["criteria"]}
    assert len(criteria) == 9
    assert criteria["EC-01"] == {
        "id": "EC-01",
        "name": "Product pass rate",
        "state": "not_met",
        "value": "88.5%",
        "threshold": "at least 90.0%",
        "blocking": True,
    }
    assert criteria["EC-08"]["value"] == "4 of 4 triaged, 1 of 1 regressions linked to a defect"
    metrics = result["metrics"]
    assert (metrics["planned"], metrics["executed"], metrics["passed"], metrics["failed"]) == ("28", "27", "23", "4")
    assert (metrics["pass_rate"], metrics["product_pass_rate"], metrics["flaky_rate"]) == ("85.2%", "88.5%", "3.7%")
    assert (metrics["new_failures"], metrics["unexcused_new_failures"], metrics["stable_passes"]) == ("2", "1", "19")
    assert metrics["open_defects"] == {"critical": "0", "high": "1", "medium": "0", "low": "0"}
    stored = session.conn.execute("SELECT * FROM evaluation WHERE id = ?", (result["evaluation_id"],)).fetchone()
    assert (stored["run_id"], stored["decision"]) == (scenario.evaluated_run, "do_not_release")


def test_evaluate_refuses_an_unknown_run_a_run_it_cannot_evaluate_and_a_session_without_versions(reference):
    session, scenario = reference
    before = dump(session.project_dir)
    with reports_server(session) as client:
        assert code(client, "evaluate", {"run_id": "RUN-9999"}) == "not_found"
        assert code(client, "evaluate", {"run_id": scenario.baseline_run}) == "invalid_state"
        assert code(client, "evaluate", {"run_id": scenario.full_candidate_run}) == "invalid_state"  # scope all
        assert code(client, "evaluate", {"result": "passed"}) == "invalid_argument"
    assert dump(session.project_dir) == before
    no_versions = sessions.start_session(session.conn, model="none", interactive=False, result_char_limit=8000)
    with reports_server(session.with_id(no_versions)) as client:
        assert code(client, "evaluate", {}) == "invalid_state"
    assert count(session, "evaluation") == 0


# prepare_report ------------------------------------------------------------------------------------------------------


def test_prepare_report_returns_the_draft_and_the_sections_to_write(reference):
    session, scenario = reference
    with reports_server(session) as client:
        prepared = client.call("reports", "prepare_report", {"type": "completion", "formats": ["md"]})
    assert prepared["report_id"] == "RPT-0001" and prepared["path"] == ".retro/reports/RPT-0001-completion/"
    assert prepared["formats"] == ["md"] and prepared["truncated"] is False
    assert [s["name"] for s in prepared["sections"]] == [
        "conclusions",
        "summary",
        "deviations",
        "residual_risks",
        "limitations",
    ]
    assert prepared["sections"][0]["purpose"] == "Interpretation of the release decision and the recommended actions."
    folder = session.project_dir / prepared["path"]
    assert (folder / "draft.md").read_text(encoding="utf-8") == prepared["computed"]
    assert f"| Evaluated run | {scenario.evaluated_run} |" in prepared["computed"]
    row = session.conn.execute("SELECT status, evaluation_id FROM report").fetchone()
    assert row["status"] == "draft" and row["evaluation_id"] is not None


def test_prepare_report_cuts_the_computed_data_at_the_result_limit(reference):
    """The test case specification of 28 test cases is longer than the result limit of the session (8,000)."""
    session, _ = reference
    with reports_server(session) as client:
        prepared = client.call("reports", "prepare_report", {"type": "test-cases"})
    draft = (session.project_dir / prepared["path"] / "draft.md").read_text(encoding="utf-8")
    assert prepared["truncated"] is True and "next_line" not in prepared
    assert len(prepared["computed"]) <= 8000 and draft.startswith(prepared["computed"])
    assert prepared["computed"].endswith("\n") and len(draft) > 8000
    assert prepared["sections"] == []


def test_prepare_report_refuses_what_it_cannot_do_and_writes_nothing(reference):
    session, scenario = reference
    before = dump(session.project_dir)
    with reports_server(session) as client:
        assert code(client, "prepare_report", {"type": "nonsense"}) == "invalid_argument"
        assert code(client, "prepare_report", {"type": "test-cases", "run_id": "RUN-0004"}) == "invalid_argument"
        assert code(client, "prepare_report", {"type": "completion", "formats": ["docx"]}) == "invalid_argument"
        for should in ("test-plan", "status", "defects"):
            error = error_of(lambda: client.call("reports", "prepare_report", {"type": should}))  # noqa: B023
            assert (error.code, error.message) == (
                "invalid_argument",
                f"the {should} report is not available in this build",
            )
        assert code(client, "prepare_report", {"type": "completion", "run_id": "RUN-9999"}) == "not_found"
        arguments = {"type": "completion", "run_id": scenario.baseline_run}
        assert code(client, "prepare_report", arguments) == "invalid_state"
    assert dump(session.project_dir) == before
    assert not (session.project_dir / ".retro" / "reports").exists()


# render_report -------------------------------------------------------------------------------------------------------


def test_render_report_adds_the_sections_and_writes_the_files(reference):
    session, _ = reference
    with reports_server(session) as client:
        prepared = client.call("reports", "prepare_report", {"type": "completion", "formats": ["md"]})
        rendered = client.call("reports", "render_report", {"report_id": prepared["report_id"], "sections": SECTIONS})
    assert rendered == {
        "report_id": "RPT-0001",
        "status": "rendered",
        "files": [".retro/reports/RPT-0001-completion/report.md"],
    }
    text = (session.project_dir / rendered["files"][0]).read_text(encoding="utf-8")
    assert "> Do not release." in text and text.count("> Not provided.") == 3


def test_render_report_refuses_what_it_cannot_do(reference):
    session, _ = reference
    with reports_server(session) as client:
        assert code(client, "render_report", {"report_id": "RPT-9999", "sections": {}}) == "not_found"
        assert code(client, "render_report", {"report_id": "RPT-0001"}) == "invalid_argument"  # sections required
        assert code(client, "render_report", {"report_id": "RPT-0001", "sections": {"a": 1}}) == "invalid_argument"
        prepared = client.call("reports", "prepare_report", {"type": "completion", "formats": ["md"]})
        report_id = prepared["report_id"]
        before = dump(session.project_dir)
        arguments = {"report_id": report_id, "sections": {"nonsense": "x"}}
        assert code(client, "render_report", arguments) == "invalid_argument"
        assert code(client, "render_report", {"report_id": report_id, "sections": {"status": "x"}}) == (
            "invalid_argument"
        )  # an agent section of the status report, which this report does not have
        assert dump(session.project_dir) == before
        client.call("reports", "render_report", {"report_id": report_id, "sections": {}})
        assert code(client, "render_report", {"report_id": report_id, "sections": {}}) == "invalid_state"


def test_render_report_without_the_pdf_library_still_renders_the_markdown(reference, tmp_path, monkeypatch):
    """The server process finds a weasyprint that cannot load its system library, as on a machine without Pango."""
    session, _ = reference
    broken = tmp_path / "broken" / "weasyprint"
    broken.mkdir(parents=True)
    (broken / "__init__.py").write_text("raise OSError(\"cannot load library 'libpango-1.0-0'\")\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(broken.parent))
    with reports_server(session) as client:
        prepared = client.call("reports", "prepare_report", {"type": "completion", "formats": ["pdf"]})
        assert prepared["formats"] == ["md", "pdf"]
        arguments = {"report_id": prepared["report_id"], "sections": SECTIONS}
        error = error_of(lambda: client.call("reports", "render_report", arguments))
        report = client.call("reports", "get_report", {"report_id": prepared["report_id"]})
    assert error.code == "unavailable" and "libpango" in error.message and "Pango" in error.message
    assert ".retro/reports/RPT-0001-completion/report.md" in error.message
    folder = session.project_dir / prepared["path"]
    assert (folder / "report.md").is_file() and not (folder / "report.pdf").exists()
    assert (report["status"], report["formats"], report["files"]) == (
        "rendered",
        ["md"],
        [".retro/reports/RPT-0001-completion/report.md"],
    )


# get_report ----------------------------------------------------------------------------------------------------------


def test_get_report_of_a_draft_a_rendered_report_and_a_report_without_evaluation(reference):
    session, scenario = reference
    with reports_server(session) as client:
        prepared = client.call("reports", "prepare_report", {"type": "completion", "formats": ["md"]})
        draft = client.call("reports", "get_report", {"report_id": prepared["report_id"]})
        client.call("reports", "render_report", {"report_id": prepared["report_id"], "sections": {}})
        rendered = client.call("reports", "get_report", {"report_id": prepared["report_id"]})
        cases = client.call("reports", "prepare_report", {"type": "test-cases", "formats": ["md"]})
        client.call("reports", "render_report", {"report_id": cases["report_id"], "sections": {}})
        specification = client.call("reports", "get_report", {"report_id": cases["report_id"]})
        assert code(client, "get_report", {"report_id": "RPT-9999"}) == "not_found"
        assert code(client, "get_report", {}) == "invalid_argument"
    assert (draft["status"], draft["files"], draft["type"]) == ("draft", [], "completion")
    evaluation_id = session.conn.execute("SELECT evaluation_id FROM report WHERE id = 'RPT-0001'").fetchone()[0]
    assert rendered == {
        "report_id": "RPT-0001",
        "type": "completion",
        "status": "rendered",
        "model": "none",
        "created_at": rendered["created_at"],
        "path": ".retro/reports/RPT-0001-completion/",
        "formats": ["md"],
        "files": [".retro/reports/RPT-0001-completion/report.md"],
        "evaluation": {
            "id": evaluation_id,
            "run_id": scenario.evaluated_run,
            "baseline_run_id": scenario.baseline_run,
            "decision": "do_not_release",
        },
    }
    assert specification["type"] == "test-cases" and specification["evaluation"] is None
