"""The definitions of the bundled tools as they exist now, read from the server modules without starting them, and
the tools of mcp-tools.md (Summary) that have no definition yet."""

from retroagent.llm.provider import ToolDefinition
from retroagent.servers.git.server import TOOLS as GIT
from retroagent.servers.memory.server import TOOLS as MEMORY
from retroagent.servers.reports.server import TOOLS as REPORTS
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
        for server, tools in (("git", GIT), ("memory", MEMORY), ("test_runner", TEST_RUNNER), ("reports", REPORTS))
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


# The read tools that every step exposes (runtime.md, Cycle command): runtime, and the read tools of git and memory.
STEP_READ_TOOLS = (
    "runtime__load_skill", "runtime__set_versions",
    "git__get_diff", "git__list_files", "git__read_file", "git__resolve_ref",
    "memory__get_analysis", "memory__get_defects", "memory__get_executions", "memory__get_requirements",
    "memory__get_risks", "memory__get_runs", "memory__get_suite", "memory__get_test_case_history",
    "memory__get_test_cases",
)  # fmt: skip

# The tools of each step besides the read tools (runtime.md, Cycle command).
STEP_OWN_TOOLS = {
    "analyze": ("git__analyze_changes", "memory__add_risk", "memory__save_impact", "memory__sync_requirements"),
    "select": ("memory__save_suite", "test_runner__run_tests"),
    "design": ("memory__design_test_case", "memory__retire_test_case", "memory__update_test_case"),
    "implement": ("memory__retire_test_case", "memory__update_test_case", "test_runner__get_evidence",
                  "test_runner__write_test"),
    "triage": ("memory__link_defect", "memory__register_defect", "memory__save_triage", "test_runner__get_evidence"),
    "report": ("reports__evaluate", "reports__get_report", "reports__prepare_report", "reports__render_report"),
}  # fmt: skip


def step_tool_names(known, step: str) -> list[str]:
    """The exposed names of the tools of ``step`` among ``known``, sorted, in mode default."""
    wanted = {*STEP_READ_TOOLS, *STEP_OWN_TOOLS[step]}
    return sorted(name for name in known if name in wanted)
