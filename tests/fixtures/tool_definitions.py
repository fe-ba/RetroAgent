"""The definitions of the bundled tools as they exist now, read from the server modules without starting them, and
the tools of mcp-tools.md (Summary) that have no definition yet."""

from retroagent.llm.provider import ToolDefinition
from retroagent.servers.git.server import TOOLS as GIT
from retroagent.servers.memory.server import TOOLS as MEMORY
from retroagent.servers.test_runner.server import TOOLS as TEST_RUNNER

# The tools of mcp-tools.md (Summary), as <server>.<tool>.
DOCUMENTED = """
runtime.load_skill runtime.set_versions
git.resolve_ref git.analyze_changes git.get_diff git.read_file git.list_files
memory.sync_requirements memory.get_requirements memory.get_analysis memory.save_impact memory.add_risk
memory.get_risks memory.save_suite memory.get_suite memory.design_test_case memory.update_test_case
memory.retire_test_case memory.get_test_cases memory.get_runs memory.get_executions memory.get_test_case_history
memory.save_triage memory.register_defect memory.link_defect memory.close_defect memory.get_defects
test_runner.write_test test_runner.run_tests test_runner.get_evidence
reports.evaluate reports.prepare_report reports.render_report reports.get_report
""".split()


def existing() -> dict[str, list[ToolDefinition]]:
    """The definitions that the bundled servers report, with bare names."""
    return {
        server: [ToolDefinition(t.name, t.description, t.parameters) for t in tools]
        for server, tools in (("git", GIT), ("memory", MEMORY), ("test_runner", TEST_RUNNER))
    }


def missing() -> list[str]:
    """Documented tools without a definition yet, as <server>.<tool>."""
    defined = {f"{server}.{d.name}" for server, definitions in existing().items() for d in definitions}
    return [name for name in DOCUMENTED if name not in defined]


def with_placeholders() -> dict[str, list[ToolDefinition]]:
    """Every documented tool: the real definition where it exists, a placeholder otherwise."""
    found = existing()
    for name in missing():
        server, tool = name.split(".")
        found.setdefault(server, []).append(ToolDefinition(tool, f"Description of {tool}.", {"type": "object"}))
    return found
