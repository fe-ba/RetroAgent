"""Reads the evaluation inputs from project memory and stores the evaluation (metrics.md, Evaluation inputs).

This is the only module of ``retroagent.metrics`` that reads the database; compute, criteria and decision are pure.
"""

import dataclasses
import sqlite3
from dataclasses import dataclass

import retroagent
from retroagent.memory import execution, interpretation, reporting
from retroagent.metrics.compute import Defect, EvaluationInputs, Execution, Run, TestCase, compute_metrics, to_json
from retroagent.metrics.criteria import CriterionResult, Thresholds, evaluate_criteria
from retroagent.metrics.decision import Decision, decide


class EvaluationError(Exception):
    """The inputs of an evaluation cannot be selected; nothing is stored."""


@dataclass(frozen=True)
class Evaluation:
    id: int
    inputs: EvaluationInputs
    metrics: dict
    criteria: list[CriterionResult]
    decision: Decision


def _latest_run(conn: sqlite3.Connection, *, role: str, commit: str, scope: str | None = None) -> sqlite3.Row | None:
    sql = "SELECT * FROM run WHERE status = 'completed' AND version_role = ? AND \"commit\" = ?"
    params = [role, commit]
    if scope is not None:
        sql += " AND scope = ?"
        params.append(scope)
    return conn.execute(sql + " ORDER BY started_at DESC, id DESC LIMIT 1", params).fetchone()


def _load_run(conn: sqlite3.Connection, row: sqlite3.Row | None) -> Run | None:
    if row is None:
        return None
    executions = []
    for e in execution.list_executions(conn, row["id"]):
        attempts = execution.list_attempts(conn, e["id"])
        triage = interpretation.current_triage(conn, e["id"])
        defect_ids = conn.execute(
            "SELECT defect_id FROM defect_execution WHERE execution_id = ?", (e["id"],)
        ).fetchall()
        executions.append(
            Execution(
                test_case_id=e["test_case_id"],
                status=e["status"],
                result=e["result"],
                attempts=tuple(a["result"] for a in attempts),
                triage=triage["classification"] if triage else None,
                defect_ids=frozenset(d[0] for d in defect_ids),
                duration=attempts[0]["duration"] if attempts else None,
            )
        )
    return Run(row["id"], tuple(executions), row["started_at"], row["ended_at"])


def _evaluated_run(conn: sqlite3.Connection, candidate_commit: str, run_id: str | None) -> sqlite3.Row:
    if run_id is None:
        row = _latest_run(conn, role="candidate", commit=candidate_commit, scope="suite")
        if row is None:
            raise EvaluationError(f"there is no completed suite run against the candidate {candidate_commit}")
        return row
    row = execution.get_run(conn, run_id)
    if row is None:
        raise EvaluationError(f"run {run_id} does not exist")
    if (row["status"], row["scope"], row["version_role"], row["commit"]) != (
        "completed",
        "suite",
        "candidate",
        candidate_commit,
    ):
        raise EvaluationError(
            f"run {run_id} is not a completed run with scope suite against the candidate {candidate_commit}"
        )
    return row


def load_inputs(conn: sqlite3.Connection, candidate_commit: str, run_id: str | None = None) -> EvaluationInputs:
    """Select ``R``, ``S``, ``A``, ``R0``, ``F0`` and ``F`` with the default rules of metrics.md.

    ``R`` is ``run_id`` when given. Runs on other commits, or of the other version role, are never used.
    """
    run_row = _evaluated_run(conn, candidate_commit, run_id)
    analysis = conn.execute(
        "SELECT a.* FROM suite s JOIN analysis a ON a.id = s.analysis_id WHERE s.id = ?", (run_row["suite_id"],)
    ).fetchone()
    if analysis["candidate_commit"] != run_row["commit"]:
        raise EvaluationError(
            f"run {run_row['id']} is on {run_row['commit']}, not on the candidate commit of analysis {analysis['id']}"
        )
    suite = []
    for row in conn.execute(
        "SELECT t.id, t.status, t.priority FROM suite_test_case s JOIN test_case t ON t.id = s.test_case_id"
        " WHERE s.suite_id = ? ORDER BY s.position",
        (run_row["suite_id"],),
    ):
        requirement_ids = conn.execute(
            "SELECT DISTINCT requirement_id FROM test_case_requirement WHERE test_case_id = ?", (row["id"],)
        ).fetchall()
        suite.append(TestCase(row["id"], row["status"], row["priority"], frozenset(r[0] for r in requirement_ids)))
    impacted = conn.execute(
        "SELECT requirement_id FROM analysis_requirement WHERE analysis_id = ?", (analysis["id"],)
    ).fetchall()
    has_requirements = conn.execute("SELECT EXISTS (SELECT 1 FROM requirement)").fetchone()[0] == 1
    defects = conn.execute("SELECT id, severity, status FROM defect ORDER BY id").fetchall()
    base, candidate = analysis["base_commit"], analysis["candidate_commit"]
    return EvaluationInputs(
        run=_load_run(conn, run_row),
        suite=tuple(suite),
        baseline=_load_run(conn, _latest_run(conn, role="base", commit=base)),
        full_base=_load_run(conn, _latest_run(conn, role="base", commit=base, scope="all")),
        full_candidate=_load_run(conn, _latest_run(conn, role="candidate", commit=candidate, scope="all")),
        impacted_requirement_ids=frozenset(r[0] for r in impacted),
        has_requirements=has_requirements,
        defects=tuple(Defect(d["id"], d["severity"], d["status"]) for d in defects),
        analysis_id=analysis["id"],
    )


def compute(inputs: EvaluationInputs, thresholds: Thresholds) -> tuple[dict, list[CriterionResult], Decision]:
    """Metrics, criteria and decision of the inputs: a pure function."""
    metrics = compute_metrics(inputs)
    criteria = evaluate_criteria(metrics, thresholds)
    return metrics, criteria, decide(criteria, inputs)


def evaluate(
    conn: sqlite3.Connection,
    candidate_commit: str,
    *,
    run_id: str | None = None,
    thresholds: Thresholds | None = None,
) -> Evaluation:
    """Compute everything for the evaluated run and store the evaluation record."""
    thresholds = thresholds or Thresholds()
    inputs = load_inputs(conn, candidate_commit, run_id)
    metrics, criteria, decision = compute(inputs, thresholds)
    evaluation_id = reporting.add_evaluation(
        conn,
        run_id=inputs.run.id,
        baseline_run_id=inputs.baseline.id if inputs.baseline else None,
        full_base_run_id=inputs.full_base.id if inputs.full_base else None,
        full_candidate_run_id=inputs.full_candidate.id if inputs.full_candidate else None,
        analysis_id=inputs.analysis_id,
        thresholds=dataclasses.asdict(thresholds),
        metrics=to_json(metrics),
        criteria=to_json(criteria),
        decision=decision.outcome,
        decision_details=to_json({"reasons": decision.reasons, "conditions": decision.conditions}),
        tool_version=retroagent.__version__,
    )
    return Evaluation(evaluation_id, inputs, metrics, criteria, decision)
