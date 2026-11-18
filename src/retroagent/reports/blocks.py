"""Values, blocks and items of the reports (reports.md). Every figure comes from the data layer and from
``retroagent.metrics``; nothing here computes a result."""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction

from retroagent.memory import design, execution
from retroagent.metrics import NotEvaluable, Ratio
from retroagent.metrics.compute import Run, TestCase, scope_metrics
from retroagent.metrics.evaluation import Evaluation
from retroagent.reports.render import Scope

NOT_EVALUABLE, NONE = "not evaluable", "none"
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2}
AT_LEAST = ("EC-01", "EC-02", "EC-03")  # the criteria whose threshold is a minimum

# The agent sections of the Must reports (reports.md, Agent sections): name -> purpose.
AGENT_SECTIONS = {
    "conclusions": "Interpretation of the release decision and the recommended actions.",
    "summary": "What was tested and what the results mean.",
    "deviations": "Why planned testing deviated, and its effect on the conclusions.",
    "residual_risks": "Risks that remain after testing, and their potential impact.",
    "limitations": "What the results cannot show, beyond the computed limitations.",
}

# Formatting (reports.md, Formatting)


def percent(ratio: Fraction) -> str:
    """A ratio as a percentage with one decimal, rounded half up."""
    tenths = int(ratio * 1000 + Fraction(1, 2))
    return f"{tenths // 10}.{tenths % 10}%"


def one_line(text) -> str:
    """A value on a single line: line breaks become spaces and ``|`` is escaped. A comment opener is escaped too,
    so that stored text never reads as the marker of an agent section."""
    return " ".join(str(text).split()).replace("|", "\\|").replace("<!--", "&lt;!--")


def code(text) -> str:
    return f"`{text}`"


def timestamp(iso: str | None) -> str:
    """ISO 8601 in the local time zone, with its UTC offset, to the minute."""
    return datetime.fromisoformat(iso).astimezone().isoformat(timespec="minutes") if iso else NONE


def commit(value: str | None) -> str:
    return value[:7] if value else NONE


def fmt(value) -> str:
    """A metric: not evaluable, a ratio, a count or a duration in seconds."""
    if value is None or isinstance(value, NotEvaluable):
        return NOT_EVALUABLE
    if isinstance(value, Ratio):
        return percent(value.value)
    if isinstance(value, float):
        return f"{value:.1f} s"
    return str(value)


def table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(one_line(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def bullets(items: list[str]) -> str:
    return "\n".join(f"- {one_line(item)}" for item in items)


def joined(items) -> str:
    return ", ".join(items) if items else NONE


# Context of a report


@dataclass(frozen=True)
class Context:
    conn: sqlite3.Connection
    report_id: str
    created_at: str
    model: str
    tool_version: str
    project_name: str
    base: tuple[str, str] | None  # ref, commit
    candidate: tuple[str, str] | None
    evaluation: Evaluation | None = None


def _suite(conn: sqlite3.Connection, suite_id: int | None) -> list[sqlite3.Row]:
    return design.suite_test_cases(conn, suite_id) if suite_id is not None else []


def _current_suite_id(ctx: Context) -> int | None:
    if ctx.base is None or ctx.candidate is None:
        return None
    return design.current_suite(ctx.conn, ctx.base[1], ctx.candidate[1])


def _requirements_of(conn: sqlite3.Connection, test_case_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT requirement_id FROM test_case_requirement WHERE test_case_id = ? ORDER BY requirement_id",
        (test_case_id,),
    )
    return [r[0] for r in rows]


# Values


def _metric_values(prefix: str, metrics: dict) -> dict[str, str]:
    values = {}
    for name, value in metrics.items():
        if isinstance(value, dict):
            values.update(_metric_values(f"{prefix}{name}.", value))
        else:
            values[f"{prefix}{name}"] = fmt(value)
    return values


def values(ctx: Context) -> dict[str, str]:
    """Every value outside items. A missing metric is ``not evaluable``; any other missing value is ``none``."""
    evaluation = ctx.evaluation
    base, candidate = ctx.base or (None, None), ctx.candidate or (None, None)
    result = {
        "project.name": ctx.project_name,
        "report.id": ctx.report_id,
        "report.generated_at": timestamp(ctx.created_at),
        "report.tool_version": ctx.tool_version,
        "model": ctx.model,
        "versions.base.ref": base[0] or NONE,
        "versions.base.commit": commit(base[1]),
        "versions.candidate.ref": candidate[0] or NONE,
        "versions.candidate.commit": commit(candidate[1]),
        "run.id": NONE,
        "run.version": NONE,
        "run.started_at": NONE,
        "run.ended_at": NONE,
        "baseline_run.id": NONE,
        "decision.value": NOT_EVALUABLE,
        "criteria.met": NOT_EVALUABLE,
        "criteria.not_met": NOT_EVALUABLE,
        "criteria.not_evaluable": NOT_EVALUABLE,
    }
    if evaluation is not None:
        run = ctx.conn.execute("SELECT * FROM run WHERE id = ?", (evaluation.inputs.run.id,)).fetchone()
        baseline = evaluation.inputs.baseline
        states = [c.state for c in evaluation.criteria]
        result |= {
            "run.id": run["id"],
            "run.version": run["ref"],
            "run.started_at": timestamp(run["started_at"]),
            "run.ended_at": timestamp(run["ended_at"]),
            "baseline_run.id": baseline.id if baseline else NONE,
            "decision.value": evaluation.decision.outcome,
            "criteria.met": str(states.count("met")),
            "criteria.not_met": str(states.count("not_met")),
            "criteria.not_evaluable": str(states.count("not_evaluable")),
        }
        result |= _metric_values("metrics.", evaluation.metrics)
    suite = [TestCase(t["id"], t["status"], t["priority"]) for t in _suite(ctx.conn, _current_suite_id(ctx))]
    planned = scope_metrics(tuple(suite), Run("", ()))
    result |= {
        "suite.planned": str(planned["planned"]),
        "suite.implemented": str(planned["implemented"]),
        "suite.designed_only": str(planned["designed_only"]),
        "suite.high_priority_planned": str(sum(1 for t in suite if t.priority == "high")),
    }
    return result


# Blocks of the completion report


def _threshold(criterion) -> str:
    threshold = criterion.threshold
    if threshold is None:
        return NONE
    bound = "at least" if criterion.id in AT_LEAST else "at most"
    return f"{bound} {percent(Fraction(str(threshold))) if isinstance(threshold, float) else threshold}"


def _criterion_value(criterion) -> str:
    value = criterion.value
    if isinstance(value, dict):  # EC-08: the four counts it compares
        return (
            f"{value['triaged_failures']} of {value['failures']} triaged, "
            f"{value['regressions_with_defect']} of {value['regressions']} regressions linked to a defect"
        )
    return fmt(value)


def decision_reasons(ctx: Context) -> str:
    return bullets(decision_lines(ctx.evaluation))


def decision_lines(evaluation: Evaluation | None) -> list[str]:
    """The items of ``list:decision_reasons`` (reports.md, Decision reasons)."""
    decision = evaluation.decision if evaluation else None
    if decision is None:
        return ["Exit criteria are only evaluated for runs against the candidate."]
    if decision.outcome == "do_not_release":
        return [_criterion_line(c) for c in decision.reasons]
    if decision.outcome == "release":
        return ["All exit criteria are met."]
    lines = []
    for condition in decision.conditions:
        ids = ", ".join(t["test_case_id"] for t in condition.test_cases)
        if condition.kind == "criterion_not_met":
            lines.append(_criterion_line(condition.criterion))
        elif condition.kind == "criterion_not_evaluable":
            c = condition.criterion
            lines.append(f"{c.id} {c.name}: not evaluable ({c.reason}).")
        elif condition.kind == "excused":
            classified = ", ".join(f"{t['test_case_id']} (`{t['classification']}`)" for t in condition.test_cases)
            lines.append(f"Test cases to update: {classified}.")
        elif condition.kind == "pre_existing":
            lines.append(f"Test cases that already failed against the baseline {condition.baseline_run_id}: {ids}.")
        else:
            lines.append(f"Planned test cases never implemented: {ids}.")
    return lines


def criterion_view(criterion) -> dict:
    """A criterion with its value and threshold as the report shows them (``reports.evaluate``)."""
    view = {
        "id": criterion.id,
        "name": criterion.name,
        "state": criterion.state,
        "value": _criterion_value(criterion),
        "threshold": _threshold(criterion),
        "blocking": criterion.blocking,
    }
    if criterion.reason:
        view["reason"] = criterion.reason
    return view


def metric_views(metrics: dict) -> dict:
    """Every metric as the report shows it: ``88.9%``, ``12``, ``42.3 s`` or ``not evaluable``."""
    return {name: metric_views(value) if isinstance(value, dict) else fmt(value) for name, value in metrics.items()}


def _criterion_line(criterion) -> str:
    return f"{criterion.id} {criterion.name}: threshold {_threshold(criterion)}, value {_criterion_value(criterion)}."


def criteria_table(ctx: Context) -> str:
    rows = [
        [c.id, c.name, _threshold(c), _criterion_value(c), code(c.state), "Yes" if c.blocking else "No"]
        for c in ctx.evaluation.criteria
    ]
    return table(["ID", "Criterion", "Threshold", "Value", "State", "Blocking"], rows)


def deviations_table(ctx: Context) -> str:
    inputs = ctx.evaluation.inputs
    rows = [
        [t.id, "Designed only", "The test case was designed and never implemented, so it was not executed."]
        for t in sorted((t for t in inputs.suite if t.status != "implemented"), key=lambda t: t.id)
    ]
    for e in execution.list_executions(ctx.conn, inputs.run.id):
        if e["status"] != "executed":
            rows.append([e["test_case_id"], e["status"].capitalize(), e["reason"] or NONE])
    if not rows:
        return "No deviations: every planned test case was implemented and executed."
    return table(["Test case", "Deviation", "Reason"], rows)


def review_items_table(ctx: Context) -> str:
    inputs = ctx.evaluation.inputs
    baseline = inputs.baseline.executed() if inputs.baseline else {}
    triage = {}  # test case -> classifications in order, and the justification of the current one
    for e in sorted(inputs.run.executions, key=lambda e: e.test_case_id):
        row = ctx.conn.execute(
            "SELECT t.classification, t.justification FROM triage t JOIN test_execution x ON x.id = t.execution_id"
            " WHERE x.run_id = ? AND x.test_case_id = ? ORDER BY t.id",
            (inputs.run.id, e.test_case_id),
        ).fetchall()
        triage[e.test_case_id] = row
    executions = sorted(inputs.run.executions, key=lambda e: e.test_case_id)
    rows = []
    for e in executions:
        if e.excused:
            rows.append([e.test_case_id, f"Excused: `{e.triage}`", triage[e.test_case_id][-1]["justification"]])
    for e in executions:
        if e.flaky:
            rows.append([e.test_case_id, "Flaky", "Attempts: " + ", ".join(e.attempts) + "."])
    for e in executions:
        if e.failure and e.triage == "pre_existing":
            before = baseline.get(e.test_case_id)
            detail = (
                f"{before.result.capitalize()} against the baseline in {inputs.baseline.id}."
                if before
                else "Classified as pre_existing."
            )
            rows.append([e.test_case_id, "Pre-existing failure", detail])
    for e in executions:
        history = triage[e.test_case_id]
        if len(history) > 1:
            detail = f"Previous: `{history[-2]['classification']}`. Current: `{history[-1]['classification']}`."
            rows.append([e.test_case_id, "Triaged more than once", detail])
    if not rows:
        return "Nothing requires review."
    return table(["Test case", "Reason for review", "Detail"], rows)


def open_defects_table(ctx: Context) -> str:
    rows = sorted(
        ctx.conn.execute("SELECT id, title, severity FROM defect WHERE status = 'open'"),
        key=lambda d: (SEVERITY_ORDER[d["severity"]], d["id"]),
    )
    if not rows:
        return "No open defects."
    cases = {
        d["id"]: [
            r[0]
            for r in ctx.conn.execute(
                "SELECT DISTINCT x.test_case_id FROM defect_execution e JOIN test_execution x ON x.id = e.execution_id"
                " WHERE e.defect_id = ? ORDER BY x.test_case_id",
                (d["id"],),
            )
        ]
        for d in rows
    }
    return table(
        ["ID", "Severity", "Title", "Test cases"],
        [[d["id"], code(d["severity"]), d["title"], joined(cases[d["id"]])] for d in rows],
    )


def risks_table(ctx: Context) -> str:
    risks = sorted(
        ctx.conn.execute("SELECT * FROM risk WHERE analysis_id = ?", (ctx.evaluation.inputs.analysis_id,)),
        key=lambda r: (LEVEL_ORDER[r["level"]], r["id"]),
    )
    if not risks:
        return "No risks registered."
    rows = []
    for r in risks:
        requirements = [
            x[0]
            for x in ctx.conn.execute(
                "SELECT requirement_id FROM risk_requirement WHERE risk_id = ? ORDER BY requirement_id", (r["id"],)
            )
        ]
        rows.append([r["id"], r["description"], code(r["level"]), joined(requirements)])
    return table(["ID", "Risk", "Level", "Requirements"], rows)


def deliverables_table(ctx: Context) -> str:
    inputs = ctx.evaluation.inputs
    rows, seen = [], set()
    for label, run in (
        ("the full run against the baseline", inputs.full_base),
        ("the full run against the candidate", inputs.full_candidate),
        ("the baseline run", inputs.baseline),
        ("the evaluated run", inputs.run),
    ):
        if run is not None and run.id not in seen:
            seen.add(run.id)
            rows.append([f"Evidence of {label} ({run.id})", code(f".retro/runs/{run.id}/")])
    rows.append(["Generated tests", code(".retro/tests/")])
    rows.append(["This report", code(f".retro/reports/{ctx.report_id}-completion/")])
    return table(["Deliverable", "Location"], rows)


def limitations_list(ctx: Context) -> str:
    lines = []
    for name, value in ctx.evaluation.metrics.items():
        if isinstance(value, NotEvaluable):
            lines.append(f"Metric `{name}` is not evaluable: {value.reason}.")
    for c in ctx.evaluation.criteria:
        if c.state == "not_evaluable":
            lines.append(f"Criterion {c.id} {c.name} is not evaluable: {c.reason}.")
    lines += [
        "The number of flaky executions is a lower bound: a few reruns find only part of the flakiness.",
        "Code coverage is not measured.",
    ]
    return bullets(lines)


# Blocks and items of the test case specification


def _sorted_suite(ctx: Context) -> list[sqlite3.Row]:
    """The test cases of the current suite: priority (high first), then identifier."""
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(_suite(ctx.conn, _current_suite_id(ctx)), key=lambda t: (order[t["priority"]], t["id"]))


def cases_table(ctx: Context) -> str:
    suite = _sorted_suite(ctx)
    if not suite:
        return "The suite is empty."
    rows = [
        [t["id"], t["title"], code(t["priority"]), code(t["status"]), joined(_requirements_of(ctx.conn, t["id"]))]
        for t in suite
    ]
    return table(["Test case", "Title", "Priority", "Status", "Requirements"], rows)


def traceability_table(ctx: Context) -> str:
    requirements = [r[0] for r in ctx.conn.execute("SELECT id FROM requirement ORDER BY id")]
    if not requirements:
        return "No documented requirements."
    traced: dict[str, list[str]] = {r: [] for r in requirements}
    for t in sorted(_suite(ctx.conn, _current_suite_id(ctx)), key=lambda t: t["id"]):
        for requirement in _requirements_of(ctx.conn, t["id"]):
            traced[requirement].append(t["id"])
    return table(["Requirement", "Test cases"], [[r, joined(cases)] for r, cases in traced.items()])


def _last_execution(conn: sqlite3.Connection, test_case_id: str) -> str:
    row = conn.execute(
        "SELECT r.id, r.ref, x.status, x.result FROM test_execution x JOIN run r ON r.id = x.run_id"
        " WHERE x.test_case_id = ? ORDER BY r.started_at DESC, r.id DESC LIMIT 1",
        (test_case_id,),
    ).fetchone()
    return f"{row['id']} against {row['ref']}: {row['result'] or row['status']}" if row else NONE


def _text(value) -> str:
    return one_line(value) if value not in (None, "") else NONE


def case_scope(ctx: Context, t: sqlite3.Row) -> Scope:
    preconditions = json.loads(t["preconditions"])
    inputs = json.loads(t["input_data"])
    steps = json.loads(t["steps"])
    origin = "project suite" if t["origin"] == "project_suite" else f"designed by {t['designed_by']}"
    return Scope(
        values={
            "test_case.id": t["id"],
            "test_case.title": _text(t["title"]),
            "test_case.objective": _text(t["objective"]),
            "test_case.priority": t["priority"],
            "test_case.status": t["status"],
            "test_case.requirements": joined(_requirements_of(ctx.conn, t["id"])),
            "test_case.origin": origin,
            "test_case.implementation": _text(t["implementation"]),
            "test_case.last_execution": _last_execution(ctx.conn, t["id"]),
            "test_case.expected_result": _text(t["expected_result"]),
        },
        blocks={
            "list:preconditions": lambda: bullets(preconditions) if preconditions else "No preconditions.",
            "table:input_data": lambda: (
                table(["Name", "Value"], [[i["name"], i["value"]] for i in inputs]) if inputs else "No input data."
            ),
            "list:steps": lambda: (
                "\n".join(f"{n}. {one_line(s)}" for n, s in enumerate(steps, start=1))
                if steps
                else "No steps recorded."
            ),
        },
    )


# Registries: a report type uses the blocks and items of its template.

COMPLETION_BLOCKS: dict[str, Callable[[Context], str]] = {
    "list:decision_reasons": decision_reasons,
    "table:criteria": criteria_table,
    "table:deviations": deviations_table,
    "table:review_items": review_items_table,
    "table:open_defects": open_defects_table,
    "table:risks": risks_table,
    "table:deliverables": deliverables_table,
    "list:limitations": limitations_list,
}
TEST_CASE_BLOCKS: dict[str, Callable[[Context], str]] = {
    "table:test_cases": cases_table,
    "table:traceability": traceability_table,
}


def scope(ctx: Context, blocks: dict[str, Callable[[Context], str]], *, with_test_cases: bool = False) -> Scope:
    """The top-level scope of a report. ``with_test_cases`` adds the ``items:test_case`` elements."""
    items = {}
    if with_test_cases:
        items["test_case"] = [case_scope(ctx, t) for t in _sorted_suite(ctx)]
    return Scope(
        values=values(ctx),
        blocks={name: (lambda fn=fn: fn(ctx)) for name, fn in blocks.items()},
        items=items,
    )
