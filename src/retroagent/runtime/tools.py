"""The tools of the runtime itself: ``runtime.load_skill`` and ``runtime.set_versions`` (mcp-tools.md, Runtime tools).

They are dispatched in-process by the turn, after the same checks as the tools of the MCP servers. Arguments are
validated against the schema of the tool, which accepts no other property.
"""

from collections.abc import Mapping

import jsonschema

from retroagent.context import skills
from retroagent.llm.provider import Message, ToolDefinition
from retroagent.servers.errors import ToolError

DEFINITIONS = (
    ToolDefinition(
        "load_skill",
        "Load the full instructions of a skill listed under Skills. Load it before doing the task it describes. One "
        "skill is loaded at a time: loading another one unloads the previous one.",
        {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Skill name, as listed under Skills."}},
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
    ToolDefinition(
        "set_versions",
        "Set the session versions that every other tool uses: the baseline and the candidate, each a tag, branch or "
        "commit of the project. Returns both refs with their commits.",
        {
            "type": "object",
            "properties": {
                "base": {"type": "string", "description": "Baseline ref: tag, branch or commit."},
                "candidate": {"type": "string", "description": "Candidate ref: tag, branch or commit."},
            },
            "required": ["base", "candidate"],
            "additionalProperties": False,
        },
    ),
)
_BY_NAME = {definition.name: definition for definition in DEFINITIONS}


def call(session, tool: str, arguments: Mapping[str, object], call_id: str) -> str | dict:
    """Run a runtime tool for the tool call ``call_id``. Raises ``ToolError``."""
    definition = _BY_NAME.get(tool)
    if definition is None:
        raise ToolError("not_found", f"the runtime has no tool {tool!r}")
    try:
        jsonschema.validate(dict(arguments), definition.parameters)
    except jsonschema.ValidationError as error:
        where = "/".join(str(part) for part in error.absolute_path)
        raise ToolError("invalid_argument", f"{where + ': ' if where else ''}{error.message}") from None
    if tool == "load_skill":
        return load_skill(session, call_id, **arguments)
    return set_versions(session, **arguments)


def load_skill(session, call_id: str, name: str) -> str:
    """The body of the skill, without its frontmatter. The body of the skill loaded before is replaced in the
    conversation with a note; loading the skill that is already loaded returns a short note."""
    conversation = session.conversation
    try:
        loaded = skills.load_skill(session.skills, name, conversation.loaded_skill)
    except skills.UnknownSkill as error:
        raise ToolError("not_found", str(error)) from None
    if name == conversation.loaded_skill:
        return loaded.content  # the short note
    if loaded.unloaded is not None:
        note = skills.unloaded_note(loaded.unloaded)
        conversation.messages = [
            Message(role="tool", content=note, tool_call_id=m.tool_call_id)
            if m.role == "tool" and m.tool_call_id == conversation.loaded_skill_call
            else m
            for m in conversation.messages
        ]
    conversation.loaded_skill, conversation.loaded_skill_call = name, call_id
    return loaded.content


def set_versions(session, base: str, candidate: str) -> dict:
    """Resolve both refs and write them, with their commits, to the session record. A ref that does not resolve is
    ``not_found`` and nothing is written."""
    from retroagent.runtime import session as session_module  # the session module builds on this one

    try:
        versions = session_module.set_versions(
            session.conn, session.id, session.project_dir, base=base, candidate=candidate
        )
    except session_module.UnknownRef as error:
        raise ToolError("not_found", str(error)) from None
    return {role: {"ref": version.ref, "commit": version.commit} for role, version in versions.items()}
