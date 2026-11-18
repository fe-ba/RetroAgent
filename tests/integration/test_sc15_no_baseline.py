"""SC-15: no baseline, no release (FR-35).

On a new copy of the example, the tests are discovered and the suite is run only against the candidate: no run
against the baseline exists. The impact and the suite come from the reference scripts; every result comes from a
real run. The evaluation and the completion report go through the reports server, as the model reaches them.
"""

import pytest
from fixtures.agent_session import Scripted, analyze_script, select_script
from fixtures.example_project import project_copy, start

from retroagent.runtime import commands, turn

pytestmark = pytest.mark.network

COMPARISON = ("new_failures", "fixed", "persistent_failures", "stable_passes", "not_comparable")


def test_sc15_without_a_baseline_run_the_comparison_and_ec_09_are_not_evaluable(
    tmp_path_factory, pristine_example, pip_cache
):
    with project_copy(tmp_path_factory, pristine_example, pip_cache) as path:
        script = Scripted([*analyze_script(), *select_script()])
        with start(path, script, trust_commands=True, mode="auto") as session:
            discovery = commands.run(session, "all", "candidate")
            commands.analyze(session)
            commands.select(session)
            suite = commands.run(session, "suite", "candidate")
            assert [r.status for r in (*discovery.runs, *suite.runs)] == ["completed", "completed"]
            assert session.conn.execute("SELECT COUNT(*) FROM run WHERE version_role = 'base'").fetchone()[0] == 0

            evaluation = turn.call_tool(session, "reports__evaluate", {}, ask=None)
            prepared = turn.call_tool(
                session, "reports__prepare_report", {"type": "completion", "formats": ["md"]}, ask=None
            )
            turn.call_tool(
                session, "reports__render_report", {"report_id": prepared["report_id"], "sections": {}}, ask=None
            )
            assert commands.session_outcome(session).decision == "do_not_release"
        assert script.remaining == 0

    assert evaluation["run_id"] == suite.runs[0].run_id and evaluation["baseline_run_id"] is None
    assert all(evaluation["metrics"][name] == "not evaluable" for name in COMPARISON)
    assert evaluation["metrics"]["unexcused_new_failures"] == "not evaluable"
    ec_09 = next(c for c in evaluation["criteria"] if c["id"] == "EC-09")
    assert (ec_09["state"], ec_09["value"], ec_09["blocking"]) == ("not_evaluable", "not evaluable", True)
    assert evaluation["decision"] == "do_not_release"
    assert any(line.startswith("EC-09 New failures: threshold at most 0, value not evaluable") for line in
               evaluation["reasons"])  # fmt: skip

    text = (path / prepared["path"] / "report.md").read_text(encoding="utf-8")
    limitations = text.split("## 10. Limitations", 1)[1].split("\n## ", 1)[0]
    assert "**Release decision: `do_not_release`**" in text
    assert f"- Criterion EC-09 New failures is not evaluable: {ec_09['reason']}." in limitations
    for name in COMPARISON:
        assert f"- Metric `{name}` is not evaluable:" in limitations
    assert "| Baseline run | none |" in text
