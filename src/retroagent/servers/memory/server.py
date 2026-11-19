"""Server ``memory``: long-term memory of the target project (mcp-tools.md, Server ``memory``).

The tools of impact analysis, selection and design, the reads of runs and executions, triage and defects.
``close_defect`` is user only: the runtime never exposes it to the model (INV-14).
Run as ``python -m retroagent.servers.memory.server --project <dir> --session <id>``.
"""

import dataclasses
import fnmatch
import json

from retroagent.config import ConfigError, load_config
from retroagent.memory import design, execution, impact, interpretation
from retroagent.memory import requirements as stored
from retroagent.servers.errors import ToolError
from retroagent.servers.git import changes
from retroagent.servers.memory.requirements import Problem, parse_documents
from retroagent.servers.serving import Context, Tool, schema, serve

LEVEL = {"type": "string", "enum": ["high", "medium", "low"]}
TEXT = {"type": "string", "minLength": 1}


def sync_requirements(context: Context) -> dict:
    try:
        config = load_config(context.project_dir)
    except ConfigError as error:
        raise ToolError("invalid_state", str(error)) from error
    entries = config["project.requirements"]
    if not entries:
        raise ToolError("invalid_state", "project.requirements is not configured: the project has no requirements")
    with context.connection() as conn:
        candidate = context.version(conn, "candidate")
    documents, problems = _read_documents(context, candidate, entries)
    requirements, parse_problems = parse_documents(documents)
    problems += parse_problems
    with context.connection() as conn:
        counts = stored.sync_requirements(conn, [dataclasses.asdict(r) for r in requirements])
    return {
        **counts,
        "unparsed": [dataclasses.asdict(problem) for problem in problems],
        "unresolved_versions": _unresolved_versions(context, requirements),
    }


def _read_documents(context: Context, candidate, entries: list[str]) -> tuple[list[tuple[str, str]], list[Problem]]:
    """The documents of ``project.requirements`` in the candidate version, in the order configured."""
    tree = changes.files_at(context.project_dir, candidate.commit)
    present = set(tree)
    paths: list[str] = []
    problems: list[Problem] = []
    for entry in entries:
        pattern = entry.removeprefix("./")
        if any(char in pattern for char in "*?["):
            matched = [path for path in tree if fnmatch.fnmatchcase(path, pattern)]
            if not matched:
                problems.append(Problem(entry, None, f"matches no file in the candidate version {candidate.ref}"))
        elif pattern in present:
            matched = [pattern]
        else:
            problems.append(Problem(entry, None, f"is not a file of the candidate version {candidate.ref}"))
            matched = []
        paths += [path for path in matched if path not in paths]
    documents = []
    for path in paths:
        try:
            documents.append((path, changes.show(context.project_dir, candidate.commit, path).decode("utf-8")))
        except UnicodeDecodeError:
            problems.append(Problem(path, None, "is not a UTF-8 text file"))
    return documents, problems


def _unresolved_versions(context: Context, requirements) -> list[dict]:
    """``Changed`` and ``Removed`` entries whose version is not a git ref: they never apply (project-contract.md)."""
    resolved: dict[str, bool] = {}
    unresolved = []
    for requirement in requirements:
        entries = [("Changed", change.version) for change in requirement.changes]
        if requirement.removed:
            entries.append(("Removed", requirement.removed))
        for field, version in entries:
            if version not in resolved:
                resolved[version] = changes.resolve(context.project_dir, version) is not None
            if not resolved[version]:
                unresolved.append({"requirement_id": requirement.id, "field": field, "version": version})
    return unresolved


def get_requirements(context: Context, ids: list[str] | None = None) -> dict:
    ids = ids or None  # an empty list filters nothing (mcp-tools.md, Empty filters)
    with context.connection() as conn:
        rows = stored.list_requirements(conn, ids)
        if ids is not None:
            unknown = sorted(set(ids) - {row["id"] for row in rows})
            if unknown:
                raise ToolError("not_found", f"unknown requirements: {', '.join(unknown)}")
        found = [
            {**dict(row), "changes": [dict(change) for change in stored.list_changes(conn, row["id"])]} for row in rows
        ]
    return {"requirements": found}


def get_analysis(context: Context, analysis_id: int | None = None) -> dict:
    with context.connection() as conn:
        if analysis_id is None:
            base, candidate = context.both_versions(conn)
            analysis_id = impact.latest_analysis(conn, base.commit, candidate.commit)
            if analysis_id is None:
                raise ToolError(
                    "not_found", f"no analysis of {base.ref}..{candidate.ref}; call git__analyze_changes first"
                )
        analysis = impact.get_analysis(conn, analysis_id)
        if analysis is None:
            raise ToolError("not_found", f"analysis {analysis_id} does not exist")
        files = [_without_nulls(dict(row), "analysis_id") for row in impact.list_files(conn, analysis_id)]
        modules = [
            {**_without_nulls(dict(row), "analysis_id"), "files": json.loads(row["files"])}
            for row in impact.list_modules(conn, analysis_id)
        ]
        impacted = [_without_nulls(dict(row), "analysis_id") for row in impact.list_requirements(conn, analysis_id)]
        not_impacted = [_without_nulls(dict(row), "analysis_id") for row in impact.list_not_impacted(conn, analysis_id)]
    return {
        "analysis_id": analysis_id,
        "base": {"ref": analysis["base_ref"], "commit": analysis["base_commit"]},
        "candidate": {"ref": analysis["candidate_ref"], "commit": analysis["candidate_commit"]},
        "created_at": analysis["created_at"],
        "files": files,
        "modules": modules,
        "requirements": impacted,
        "not_impacted": not_impacted,
    }


def _without_nulls(record: dict, *drop: str) -> dict:
    return {key: value for key, value in record.items() if value is not None and key not in drop}


def save_impact(
    context: Context, analysis_id: int, modules: list[dict], requirements: list[dict], not_impacted: list[dict]
) -> dict:
    with context.connection() as conn:
        analysis = impact.get_analysis(conn, analysis_id)
        if analysis is None:
            raise ToolError("not_found", f"analysis {analysis_id} does not exist")
        applies: dict[str, bool] = {}

        def removal_applies(version: str) -> bool:
            if version not in applies:
                applies[version] = changes.applies(
                    context.project_dir, version, analysis["base_commit"], analysis["candidate_commit"]
                )
            return applies[version]

        impact.record_impact(
            conn,
            analysis_id,
            modules=modules,
            requirements=requirements,
            not_impacted=not_impacted,
            removal_applies=removal_applies,
        )
    return {
        "analysis_id": analysis_id,
        "modules": len(modules),
        "requirements": len(requirements),
        "not_impacted": len(not_impacted),
    }


def add_risk(context: Context, description: str, level: str, requirement_ids: list[str] | None = None) -> dict:
    with context.connection() as conn:
        base, candidate = context.both_versions(conn)
        analysis_id = impact.latest_analysis(conn, base.commit, candidate.commit)
        if analysis_id is None:
            raise ToolError(
                "invalid_state", f"no analysis of {base.ref}..{candidate.ref}; call git__analyze_changes first"
            )
        risk_id = impact.add_risk(
            conn,
            description=description,
            level=level,
            analysis_id=analysis_id,
            requirement_ids=list(dict.fromkeys(requirement_ids or [])),
        )
    return {"risk_id": risk_id, "analysis_id": analysis_id}


def get_risks(context: Context) -> dict:
    with context.connection() as conn:
        return {"risks": impact.list_risks(conn)}


# Selection and design --------------------------------------------------------------------------------------------


def _current_suite(context: Context, conn) -> int | None:
    base, candidate = context.both_versions(conn)
    return design.current_suite(conn, base.commit, candidate.commit)


def save_suite(context: Context, analysis_id: int, items: list[dict], left_out: list[dict]) -> dict:
    with context.connection() as conn:
        if impact.get_analysis(conn, analysis_id) is None:
            raise ToolError("not_found", f"analysis {analysis_id} does not exist")
        base, candidate = context.both_versions(conn)
        latest = impact.latest_analysis(conn, base.commit, candidate.commit)
        if analysis_id != latest:
            raise ToolError(
                "invalid_state",
                f"analysis {analysis_id} is not the latest analysis of {base.ref}..{candidate.ref}"
                f" ({latest if latest is not None else 'there is none'}); a suite is saved for the latest one",
            )
        suite_id = design.save_suite(
            conn, analysis_id=analysis_id, session_id=context.session_id, items=items, left_out=left_out
        )
        uncovered = design.uncovered_requirements(conn, suite_id)
    return {
        "suite_id": suite_id,
        "analysis_id": analysis_id,
        "test_cases": len(items),
        "uncovered_requirements": uncovered,
    }


def get_suite(context: Context, suite_id: int | None = None) -> dict:
    with context.connection() as conn:
        if suite_id is None:
            suite_id = _current_suite(context, conn)
            if suite_id is None:
                raise ToolError("not_found", "there is no current suite for the session versions; select one first")
        suite = design.get_suite(conn, suite_id)
        if suite is None:
            raise ToolError("not_found", f"suite {suite_id} does not exist")
        items = [_without_nulls(dict(row)) for row in design.suite_items(conn, suite_id)]
        left_out = [dict(row) for row in design.suite_left_out(conn, suite_id)]
        uncovered = design.uncovered_requirements(conn, suite_id)
    return {
        "suite_id": suite_id,
        "analysis_id": suite["analysis_id"],
        "created_at": suite["created_at"],
        "items": items,
        "left_out": left_out,
        "uncovered_requirements": uncovered,
    }


def design_test_case(
    context: Context,
    title: str,
    objective: str,
    priority: str,
    preconditions: list[str],
    input_data: list[dict],
    steps: list[str],
    expected_result: str,
    requirement_ids: list[str],
    selection_reason: str,
) -> dict:
    with context.connection() as conn:
        suite_id = _current_suite(context, conn)
        if suite_id is None:
            raise ToolError(
                "invalid_state", "there is no current suite for the session versions; select the suite first"
            )
        test_case_id, position = design.design_test_case(
            conn,
            suite_id=suite_id,
            selection_reason=selection_reason,
            designed_by=context.session(conn)["model"],
            title=title,
            objective=objective,
            priority=priority,
            preconditions=preconditions,
            input_data=input_data,
            steps=steps,
            expected_result=expected_result,
            requirement_ids=list(dict.fromkeys(requirement_ids)),
        )
    return {"test_case_id": test_case_id, "suite_id": suite_id, "position": position}


def update_test_case(context: Context, test_case_id: str, fields: dict) -> dict:
    with context.connection() as conn:
        design.update_test_case(conn, test_case_id, fields)
    return {"test_case_id": test_case_id, "updated": sorted(fields)}


def retire_test_case(context: Context, test_case_id: str, reason: str) -> dict:
    with context.connection() as conn:
        retired_at = design.retire_test_case(
            conn, test_case_id, reason=reason, retired_by=context.session(conn)["model"]
        )
    return {"test_case_id": test_case_id, "retired_at": retired_at}


_JSON_COLUMNS = ("preconditions", "input_data", "steps")


def _test_case(conn, row) -> dict:
    record = _without_nulls(dict(row))
    for column in _JSON_COLUMNS:
        record[column] = json.loads(row[column])
    record["requirements"] = [dict(link) for link in design.test_case_requirements(conn, row["id"])]
    return record


def get_test_cases(
    context: Context,
    ids: list[str] | None = None,
    status: str | None = None,
    requirement_id: str | None = None,
    include_code: bool = False,
    include_retired: bool = False,
) -> dict:
    ids = ids or None  # an empty list filters nothing (mcp-tools.md, Empty filters)
    with context.connection() as conn:
        if ids is not None:
            ids = list(dict.fromkeys(ids))
            known = {row["id"] for row in design.list_test_cases(conn, ids=ids)}
            unknown = [test_case_id for test_case_id in ids if test_case_id not in known]
            if unknown:
                raise ToolError("not_found", f"unknown test cases: {', '.join(unknown)}")
        if requirement_id is not None and stored.get_requirement(conn, requirement_id) is None:
            raise ToolError("not_found", f"requirement {requirement_id!r} does not exist")
        rows = design.list_test_cases(
            conn, ids=ids, status=status, requirement_id=requirement_id, include_retired=include_retired
        )
        found = [_test_case(conn, row) for row in rows]
        limit = context.result_limit(conn)
    result: dict = {"test_cases": found}
    if include_code:
        result["truncated"] = _add_code(context, found, limit)
    return result


def _add_code(context: Context, test_cases: list[dict], limit: int) -> bool:
    """Add the code of each generated test, while the total stays within the result limit (mcp-tools.md, Large
    output). A test case whose code does not fit gets ``code_omitted``; returns whether any did."""
    root = (context.project_dir / ".retro" / "tests").resolve()
    used, omitted = 0, False
    for test_case in test_cases:
        if test_case["origin"] != "designed" or "implementation" not in test_case:
            continue
        path = (root / test_case["implementation"].rpartition("::")[0]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            test_case["code_missing"] = True
            continue
        code = path.read_text(encoding="utf-8", errors="replace")
        if used + len(code) > limit:
            test_case["code_omitted"] = True
            omitted = True
            continue
        test_case["code"] = code
        used += len(code)
    return omitted


# Runs and executions ---------------------------------------------------------------------------------------------


def get_runs(context: Context, limit: int = 10, version_role: str | None = None) -> dict:
    with context.connection() as conn:
        runs = [
            {
                **_without_nulls(
                    {key: run[key] for key in ("id", "version_role", "ref", "commit", "scope", "suite_id", "status")}
                ),
                **_without_nulls({key: run[key] for key in ("started_at", "ended_at", "error")}),
                "counts": execution.execution_counts(conn, run["id"]),
            }
            for run in execution.list_runs(conn, limit, version_role=version_role)
        ]
    return {"runs": runs}


def _attempts(conn, execution_id: int) -> list[dict]:
    return [_without_nulls(dict(row), "execution_id") for row in execution.list_attempts(conn, execution_id)]


def get_executions(context: Context, run_id: str, result: str | None = None, untriaged: bool = False) -> dict:
    with context.connection() as conn:
        if execution.get_run(conn, run_id) is None:
            raise ToolError("not_found", f"run {run_id!r} does not exist")
        found = []
        for row in execution.list_executions(conn, run_id):
            if result is not None and row["result"] != result:
                continue
            triage = interpretation.current_triage(conn, row["id"])
            if untriaged and (row["result"] not in ("failed", "error") or triage is not None):
                continue
            test_case = design.get_test_case(conn, row["test_case_id"])
            record = {
                "execution_id": row["id"],
                "test_case_id": row["test_case_id"],
                "title": test_case["title"],
                **_without_nulls(
                    {key: row[key] for key in ("status", "result", "reason", "duration", "test_revision")}
                ),
                "flaky": execution.is_flaky(conn, row["id"]),
                "attempts": _attempts(conn, row["id"]),
                "triage": None if triage is None else _without_nulls(dict(triage), "execution_id"),
            }
            count = interpretation.triage_count(conn, row["id"])
            if count > 1:
                record["triage_count"] = count
            found.append(record)
    return {"run_id": run_id, "executions": found}


def get_test_case_history(context: Context, test_case_id: str) -> dict:
    with context.connection() as conn:
        if design.get_test_case(conn, test_case_id) is None:
            raise ToolError("not_found", f"test case {test_case_id!r} does not exist")
        history = [
            {
                **_without_nulls(
                    {
                        "run_id": row["run_id"],
                        "version_role": row["version_role"],
                        "ref": row["ref"],
                        "commit": row["commit"],
                        "started_at": row["started_at"],
                        "status": row["status"],
                        "result": row["result"],
                        "reason": row["reason"],
                    }
                ),
                "flaky": execution.is_flaky(conn, row["id"]),
            }
            for row in execution.test_case_history(conn, test_case_id)
        ]
    return {"test_case_id": test_case_id, "executions": history}


# Triage and defects ----------------------------------------------------------------------------------------------


def save_triage(
    context: Context,
    execution_id: int,
    classification: str,
    justification: str,
    replace: bool = False,
    confirm: bool = False,
) -> dict:
    with context.connection() as conn:
        session = context.session(conn)
        base_commit, candidate_commit = session["base_commit"], session["candidate_commit"]
        change_applies = None
        if base_commit is not None and candidate_commit is not None:
            applies: dict[str, bool] = {}

            def change_applies(version: str) -> bool:
                if version not in applies:
                    applies[version] = changes.applies(context.project_dir, version, base_commit, candidate_commit)
                return applies[version]

        previous = interpretation.current_triage(conn, execution_id)
        triage_id = interpretation.add_triage(
            conn,
            execution_id=execution_id,
            classification=classification,
            justification=justification,
            triaged_by=session["model"],
            base_commit=base_commit,
            candidate_commit=candidate_commit,
            change_applies=change_applies,
            replace=replace,
            confirm=confirm,
        )
        row = conn.execute("SELECT test_case_id FROM test_execution WHERE id = ?", (execution_id,)).fetchone()
        test_case_id = row["test_case_id"]
    saved = {
        "triage_id": triage_id,
        "execution_id": execution_id,
        "test_case_id": test_case_id,
        "classification": classification,
    }
    if previous is not None:
        saved["previous"] = previous["classification"]
    return saved


def register_defect(context: Context, title: str, severity: str, execution_ids: list[int], steps: list[str]) -> dict:
    with context.connection() as conn:
        defect_id = interpretation.add_defect(
            conn, title=title, severity=severity, execution_ids=execution_ids, steps=steps
        )
    return {"defect_id": defect_id}


def link_defect(context: Context, defect_id: str, execution_ids: list[int]) -> dict:
    with context.connection() as conn:
        interpretation.link_executions(conn, defect_id, execution_ids)
        linked = [row["execution_id"] for row in interpretation.linked_executions(conn, defect_id)]
    return {"defect_id": defect_id, "execution_ids": linked}


def close_defect(context: Context, defect_id: str, reason: str) -> dict:
    with context.connection() as conn:
        interpretation.close_defect(conn, defect_id, closed_by="user", close_reason=reason)
    return {"defect_id": defect_id, "status": "closed", "closed_by": "user"}


def defect_record(conn, row) -> dict:
    """A defect as ``memory.get_defects`` returns it: its fields, its steps as a list and its linked executions."""
    return {
        **_without_nulls(dict(row)),
        "steps": json.loads(row["steps"]),
        "executions": [dict(e) for e in interpretation.linked_executions(conn, row["id"])],
    }


def get_defects(context: Context, status: str | None = None) -> dict:
    with context.connection() as conn:
        defects = [defect_record(conn, row) for row in interpretation.list_defects(conn, status)]
    return {"defects": defects}


TOOLS = [
    Tool(
        "sync_requirements",
        "Read the requirement documents of the candidate version into memory. Call it before an impact analysis. "
        "Returns how many requirements were read, added and changed, what could not be parsed, and change "
        "entries whose version is not a git ref.",
        schema(),
        sync_requirements,
    ),
    Tool(
        "get_requirements",
        "Get requirements from memory with their priority, versions and documented changes. A Changed entry for "
        "the candidate means a behavior change there may be expected. Returns all requirements, or those of ids.",
        schema(
            {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Requirement IDs such as REQ-004. Default: all.",
                }
            }
        ),
        get_requirements,
    ),
    Tool(
        "get_analysis",
        "Get an impact analysis: its change set, the impacted modules with their risk levels, the impacted "
        "requirements and the requirements judged not impacted, with reasons. Use it to recall an analysis.",
        schema({"analysis_id": {"type": "integer", "description": "Default: the latest analysis of the session."}}),
        get_analysis,
    ),
    Tool(
        "save_impact",
        "Record the impact of an analysis, once: modules with risk level and reason, and every requirement in "
        "effect, either in requirements (impacted) or in not_impacted, each with a reason. Files exactly as in the "
        "change set. A call that leaves a requirement out is refused and names it.",
        schema(
            {
                "analysis_id": {"type": "integer", "description": "ID returned by git__analyze_changes."},
                "modules": {
                    "type": "array",
                    "minItems": 1,
                    "description": "One entry per module of the change set.",
                    "items": schema(
                        {
                            "module": {**TEXT, "description": "Module name, e.g. pricing."},
                            "files": {
                                "type": "array",
                                "minItems": 1,
                                "items": TEXT,
                                "description": "Changed files of the module, as in the change set.",
                            },
                            "risk_level": {**LEVEL, "description": "high, medium or low."},
                            "reason": {**TEXT, "description": "What changed in the diff and why it matters."},
                        },
                        ("module", "files", "risk_level", "reason"),
                    ),
                },
                "requirements": {
                    "type": "array",
                    "description": "Impacted requirements. May be empty.",
                    "items": schema(
                        {
                            "requirement_id": {**TEXT, "description": "Requirement ID, e.g. REQ-004."},
                            "reason": {**TEXT, "description": "Why it is impacted."},
                        },
                        ("requirement_id", "reason"),
                    ),
                },
                "not_impacted": {
                    "type": "array",
                    "description": "Every other requirement in effect, judged not impacted. May be empty.",
                    "items": schema(
                        {
                            "requirement_id": {**TEXT, "description": "Requirement ID, e.g. REQ-001."},
                            "reason": {**TEXT, "description": "Why no changed file takes part in its behavior."},
                        },
                        ("requirement_id", "reason"),
                    ),
                },
            },
            ("analysis_id", "modules", "requirements", "not_impacted"),
        ),
        save_impact,
    ),
    Tool(
        "add_risk",
        "Register one way the change could harm the product, linked to the latest analysis of the session. Use one "
        "risk per failure scenario, not one per file. Returns the new risk ID.",
        schema(
            {
                "description": {**TEXT, "description": "The failure scenario and its effect."},
                "level": {**LEVEL, "description": "high, medium or low."},
                "requirement_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Related requirement IDs. May be empty.",
                },
            },
            ("description", "level"),
        ),
        add_risk,
    ),
    Tool(
        "get_risks",
        "List every registered risk with its level, its analysis and its requirements.",
        schema(),
        get_risks,
    ),
    Tool(
        "save_suite",
        "Save the suite of the latest analysis; it becomes the current suite. Every implemented test case of an "
        "impacted requirement, and every one whose verdict differs between the full runs of the two versions, goes in "
        "items or in left_out. Returns the suite ID and uncovered_requirements.",
        schema(
            {
                "analysis_id": {"type": "integer", "description": "The latest analysis of the session versions."},
                "items": {
                    "type": "array",
                    "description": "The selected test cases. May be empty.",
                    "items": schema(
                        {
                            "test_case_id": {**TEXT, "description": "Test case ID, e.g. TC-014."},
                            "position": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "Priority order from 1, unique; orders the presentation only.",
                            },
                            "selection_reason": {
                                **TEXT,
                                "description": "The requirement, module or risk that justifies it, and what changed.",
                            },
                        },
                        ("test_case_id", "position", "selection_reason"),
                    ),
                },
                "left_out": {
                    "type": "array",
                    "description": "Not selected, with the reason; each of an impacted requirement or changed full-run "
                    "verdict. Never one that passed on base and failed on candidate.",
                    "items": schema(
                        {
                            "test_case_id": {**TEXT, "description": "Test case ID, e.g. TC-013."},
                            "reason": {**TEXT, "description": "Why it is not selected."},
                        },
                        ("test_case_id", "reason"),
                    ),
                },
            },
            ("analysis_id", "items", "left_out"),
        ),
        save_suite,
    ),
    Tool(
        "get_suite",
        "Get a suite: each test case with position, title, priority, status, origin and selection reason; the test "
        "cases left out with their reasons; and uncovered_requirements: impacted requirements no test case of it is "
        "traced to. Default: the current suite.",
        schema({"suite_id": {"type": "integer", "description": "Default: the current suite."}}),
        get_suite,
    ),
    Tool(
        "design_test_case",
        "Create a test case with status designed (not implemented, not executed) and add it to the current suite. "
        "Input data and expected result must be concrete values. Returns the new test case ID.",
        schema(
            {
                "title": {**TEXT, "description": "What is verified, in a few words."},
                "objective": {**TEXT, "description": "One sentence: Verify that ..."},
                "priority": {**LEVEL, "description": "high, medium or low."},
                "preconditions": {
                    "type": "array",
                    "items": TEXT,
                    "description": "State the system and data must be in. May be empty.",
                },
                "input_data": {
                    "type": "array",
                    "description": "Each input with a concrete value. May be empty.",
                    "items": schema(
                        {
                            "name": {**TEXT, "description": "Input name."},
                            "value": {**TEXT, "description": "Concrete value, as text, e.g. 6."},
                        },
                        ("name", "value"),
                    ),
                },
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "items": TEXT,
                    "description": "Observable actions, in order.",
                },
                "expected_result": {**TEXT, "description": "Exact observable outcome: values, status codes, messages."},
                "requirement_ids": {
                    "type": "array",
                    "items": TEXT,
                    "description": "Every requirement verified. Empty only when the project has none.",
                },
                "selection_reason": {**TEXT, "description": "Which gap of the suite it covers."},
            },
            (
                "title",
                "objective",
                "priority",
                "preconditions",
                "input_data",
                "steps",
                "expected_result",
                "requirement_ids",
                "selection_reason",
            ),
        ),
        design_test_case,
    ),
    Tool(
        "update_test_case",
        "Change the description of a test case. A designed test case or a project test can change every design "
        "field; an implemented generated test only title, objective and priority (the rest changes with its code). "
        "requirement_ids replaces the design links.",
        schema(
            {
                "test_case_id": {**TEXT, "description": "Test case ID."},
                "fields": {
                    "type": "object",
                    "minProperties": 1,
                    "additionalProperties": False,
                    "description": "The design fields to change, as in design_test_case.",
                    "properties": {
                        "title": {**TEXT, "description": "What is verified."},
                        "objective": {**TEXT, "description": "One sentence: Verify that ..."},
                        "priority": {**LEVEL, "description": "high, medium or low."},
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
            ("test_case_id", "fields"),
        ),
        update_test_case,
    ),
    Tool(
        "retire_test_case",
        "Take a test case out of use, permanently: an obsolete test, a generated test that cannot be repaired, or one "
        "whose requirement was removed. Its history is kept and it can no longer be selected.",
        schema(
            {
                "test_case_id": {**TEXT, "description": "An active test case."},
                "reason": {**TEXT, "description": "Why it is retired."},
            },
            ("test_case_id", "reason"),
        ),
        retire_test_case,
    ),
    Tool(
        "get_test_cases",
        "Get test cases with their fields, status, origin, implementation and traced requirements. Filters combine. "
        "Retired test cases are left out unless asked for by ID or with include_retired.",
        schema(
            {
                "ids": {"type": "array", "items": TEXT, "description": "Test case IDs. Default: all."},
                "status": {"type": "string", "enum": ["designed", "implemented"], "description": "Test case status."},
                "requirement_id": {**TEXT, "description": "Only test cases traced to this requirement."},
                "include_code": {
                    "type": "boolean",
                    "description": "Also return the code of generated tests. Default: false.",
                },
                "include_retired": {"type": "boolean", "description": "Also return retired ones. Default: false."},
            }
        ),
        get_test_cases,
    ),
    Tool(
        "get_runs",
        "List the latest runs, newest first, with version, scope, status and the counts of execution statuses and "
        "results.",
        schema(
            {
                "limit": {"type": "integer", "minimum": 1, "description": "Default: 10."},
                "version_role": {"type": "string", "enum": ["base", "candidate"], "description": "Only this version."},
            }
        ),
        get_runs,
    ),
    Tool(
        "get_executions",
        "List the executions of a run: test case, status, result, attempts, whether it was flaky, and its current "
        "triage.",
        schema(
            {
                "run_id": {**TEXT, "description": "Run ID, e.g. RUN-0002."},
                "result": {
                    "type": "string",
                    "enum": ["passed", "failed", "error"],
                    "description": "Only executions with this result.",
                },
                "untriaged": {"type": "boolean", "description": "Only failed or error executions without triage."},
            },
            ("run_id",),
        ),
        get_executions,
    ),
    Tool(
        "get_test_case_history",
        "Every execution of a test case, oldest first, with run, version, status, result and whether it was flaky.",
        schema({"test_case_id": {**TEXT, "description": "Test case ID."}}, ("test_case_id",)),
        get_test_case_history,
    ),
    Tool(
        "save_triage",
        "Classify a failed or error execution, with a justification citing the evidence. Code refuses flaky, "
        "expected_change, pre_existing and regression without their evidence, and with the evidence a regression of "
        "a documented change or a pre_existing generated test, unless confirm is true.",
        schema(
            {
                "execution_id": {"type": "integer", "description": "A failed or error execution."},
                "classification": {
                    "type": "string",
                    "enum": ["regression", "expected_change", "flaky", "environment", "test_defect", "pre_existing"],
                    "description": "The classification of the failure.",
                },
                "justification": {**TEXT, "description": "One to three sentences citing the evidence."},
                "replace": {
                    "type": "boolean",
                    "description": "Triage again an execution that already has a triage; the earlier one is kept.",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Keep a classification that a soft check refused, because the evidence shows "
                    "otherwise.",
                },
            },
            ("execution_id", "classification", "justification"),
        ),
        save_triage,
    ),
    Tool(
        "register_defect",
        "Register an open defect for failed executions with the same cause, each already triaged as regression or "
        "pre_existing. Expected and actual results are taken from the first execution. Returns the DEF ID.",
        schema(
            {
                "title": {**TEXT, "description": "Short description of the failure."},
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "critical, high, medium or low.",
                },
                "execution_ids": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "integer"},
                    "description": "Failed or error executions; the first one gives the expected and actual results.",
                },
                "steps": {"type": "array", "items": TEXT, "description": "Steps to reproduce."},
            },
            ("title", "severity", "execution_ids", "steps"),
        ),
        register_defect,
    ),
    Tool(
        "link_defect",
        "Link more failed executions to an open defect, when the same failure appears in a later run.",
        schema(
            {
                "defect_id": {**TEXT, "description": "An open defect, e.g. DEF-001."},
                "execution_ids": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "integer"},
                    "description": "Failed or error executions, each triaged as regression or pre_existing.",
                },
            },
            ("defect_id", "execution_ids"),
        ),
        link_defect,
    ),
    Tool(
        "close_defect",
        "User only. Close a defect by decision of the user.",
        schema(
            {
                "defect_id": {**TEXT, "description": "An open defect."},
                "reason": {**TEXT, "description": "Typed by the user."},
            },
            ("defect_id", "reason"),
        ),
        close_defect,
    ),
    Tool(
        "get_defects",
        "List defects with severity, status, expected and actual results, steps and linked executions.",
        schema({"status": {"type": "string", "enum": ["open", "closed"], "description": "Default: both."}}),
        get_defects,
    ),
]


if __name__ == "__main__":
    serve("memory", TOOLS)
