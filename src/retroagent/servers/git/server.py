"""Server ``git``: reads the repository of the target project (mcp-tools.md, Server ``git``).

It reads git objects of the session versions and never the working copy, and writes only the change set of an
analysis to project memory. Run as ``python -m retroagent.servers.git.server --project <dir> --session <id>``.
"""

from retroagent.memory import impact
from retroagent.servers.errors import ToolError
from retroagent.servers.git import changes
from retroagent.servers.serving import Context, Tool, page, schema, serve

VERSION = {"type": "string", "enum": ["base", "candidate"], "description": "Which session version: base or candidate."}
START_LINE = {
    "type": "integer",
    "minimum": 1,
    "description": "First line to return. Default 1. When a result says truncated, call again with its next_line.",
}


def resolve_ref(context: Context, ref: str) -> dict:
    commit = changes.resolve(context.project_dir, ref)
    if commit is None:
        raise ToolError("not_found", f"{ref!r} is not a tag, branch or commit of the project")
    return {"ref": ref, "commit": commit, "kind": changes.ref_kind(context.project_dir, ref)}


def analyze_changes(context: Context) -> dict:
    with context.connection() as conn:
        base, candidate = context.both_versions(conn)
        files = changes.change_set(context.project_dir, base.commit, candidate.commit)
        analysis_id = impact.add_analysis(
            conn,
            session_id=context.session_id,
            base_ref=base.ref,
            base_commit=base.commit,
            candidate_ref=candidate.ref,
            candidate_commit=candidate.commit,
            files=[f.as_dict() for f in files],
        )
    return {
        "analysis_id": analysis_id,
        "base": base.ref,
        "candidate": candidate.ref,
        "files": [f.as_dict() for f in files],
    }


def get_diff(context: Context, path: str, analysis_id: int | None = None, start_line: int = 1) -> dict:
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
        changed = impact.get_file(conn, analysis_id, path)
        if changed is None:
            raise ToolError("not_found", f"{path!r} is not in the change set of analysis {analysis_id}")
        limit = context.result_limit(conn)
    text = changes.diff(
        context.project_dir, analysis["base_commit"], analysis["candidate_commit"], path, changed["old_path"]
    )
    content, meta = page(text, start_line, limit)
    return {"analysis_id": analysis_id, "path": path, "diff": content, **meta}


def read_file(context: Context, path: str, version: str, start_line: int = 1) -> dict:
    with context.connection() as conn:
        commit = context.version(conn, version).commit
        limit = context.result_limit(conn)
    kind = changes.object_type(context.project_dir, commit, path)
    if kind is None:
        raise ToolError("not_found", f"{path!r} does not exist in the {version} version")
    if kind != "blob":
        raise ToolError("not_found", f"{path!r} is a directory in the {version} version: use git__list_files")
    data = changes.show(context.project_dir, commit, path)
    if b"\0" in data[:8000]:
        return {"path": path, "version": version, "binary": True, "size": len(data)}
    content, meta = page(data.decode("utf-8", errors="replace"), start_line, limit)
    return {"path": path, "version": version, "content": content, **meta}


def list_files(context: Context, version: str, path: str = "") -> dict:
    path = path.strip("/")
    with context.connection() as conn:
        commit = context.version(conn, version).commit
    if path in ("", "."):
        path = ""
    elif changes.object_type(context.project_dir, commit, path) != "tree":
        raise ToolError("not_found", f"{path!r} is not a directory of the {version} version")
    return {"version": version, "path": path or ".", "entries": changes.list_dir(context.project_dir, commit, path)}


TOOLS = [
    Tool(
        "resolve_ref",
        "Find the commit of a tag, branch or commit hash. Use it to check a ref the user names. "
        "Returns the full commit hash and the kind of ref: tag, branch or commit.",
        schema({"ref": {"type": "string", "description": "Tag, branch or commit hash, e.g. v1.1."}}, ("ref",)),
        resolve_ref,
    ),
    Tool(
        "analyze_changes",
        "Compare the base and candidate versions of the session and start a new analysis. Call it once at the start "
        "of an impact analysis. Returns the analysis ID and every changed file with its kind of change and the "
        "lines added and removed.",
        schema(),
        analyze_changes,
    ),
    Tool(
        "get_diff",
        "Show what changed in one file of the change set, as a unified diff. Use it to read each changed file that "
        "can affect behavior. Long diffs come in parts: when truncated is true, call again with start_line set to "
        "next_line.",
        schema(
            {
                "path": {"type": "string", "description": "A file of the change set, exactly as listed."},
                "analysis_id": {"type": "integer", "description": "Default: the latest analysis of the session."},
                "start_line": START_LINE,
            },
            ("path",),
        ),
        get_diff,
    ),
    Tool(
        "read_file",
        "Read a file of the project as it is in the base or candidate version. Use it when a diff lacks context. "
        "Long files come in parts: when truncated is true, call again with start_line set to next_line.",
        schema(
            {
                "path": {"type": "string", "description": "Path from the repository root, e.g. src/shop/cart.py."},
                "version": VERSION,
                "start_line": START_LINE,
            },
            ("path", "version"),
        ),
        read_file,
    ),
    Tool(
        "list_files",
        "List the files and directories directly inside a directory of the base or candidate version. Use it to "
        "learn the structure of the project. Directory names end with /.",
        schema(
            {
                "version": VERSION,
                "path": {"type": "string", "description": "Directory from the repository root. Default: the root."},
            },
            ("version",),
        ),
        list_files,
    ),
]


if __name__ == "__main__":
    serve("git", TOOLS)
