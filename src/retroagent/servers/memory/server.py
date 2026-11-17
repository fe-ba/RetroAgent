"""Server ``memory``: long-term memory of the target project (mcp-tools.md, Server ``memory``).

Slice 3 registers the tools of impact analysis only: ``sync_requirements``, ``get_requirements``,
``get_analysis``, ``save_impact``, ``add_risk`` and ``get_risks``. Run as
``python -m retroagent.servers.memory.server --project <dir> --session <id>``.
"""

import dataclasses
import fnmatch
import json

from retroagent.config import ConfigError, load_config
from retroagent.memory import impact
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
    return {
        "analysis_id": analysis_id,
        "base": {"ref": analysis["base_ref"], "commit": analysis["base_commit"]},
        "candidate": {"ref": analysis["candidate_ref"], "commit": analysis["candidate_commit"]},
        "created_at": analysis["created_at"],
        "files": files,
        "modules": modules,
        "requirements": impacted,
    }


def _without_nulls(record: dict, *drop: str) -> dict:
    return {key: value for key, value in record.items() if value is not None and key not in drop}


def save_impact(context: Context, analysis_id: int, modules: list[dict], requirements: list[dict]) -> dict:
    with context.connection() as conn:
        impact.record_impact(conn, analysis_id, modules=modules, requirements=requirements)
    return {"analysis_id": analysis_id, "modules": len(modules), "requirements": len(requirements)}


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
        "Get an impact analysis: its change set, the impacted modules with their risk levels, and the impacted "
        "requirements. Use it to recall an analysis already recorded.",
        schema({"analysis_id": {"type": "integer", "description": "Default: the latest analysis of the session."}}),
        get_analysis,
    ),
    Tool(
        "save_impact",
        "Record the impact of an analysis, once: the changed modules with risk level and reason, and the impacted "
        "requirements with reasons. Files must be written exactly as in the change set. Returns how many modules "
        "and requirements were recorded.",
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
            },
            ("analysis_id", "modules", "requirements"),
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
]


if __name__ == "__main__":
    serve("memory", TOOLS)
