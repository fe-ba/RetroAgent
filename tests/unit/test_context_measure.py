"""Measure of the fixed part of the context that exists so far: the system context, which holds the bundled
steering, the project context of shop-api and the skills index, and the tool definitions of each tool set as they
exist now (build-plan.md, Measuring the context). Run with ``pytest -s`` to see the figures.

The tool figures are not final: each tool set still lacks the tools of later sessions, and the count of missing
tools is printed with them.
"""

from fixtures.tool_definitions import DOCUMENTED, existing, missing
from test_context_system import reference_system_context, shop_api_retro_md

from retroagent.context import budget, skills, system, tools
from retroagent.llm.provider import definition_characters


def row(label: str, characters: int) -> str:
    return (
        f"{label:<22}{characters:>8,} characters{characters // 4:>8,} tokens at /4"
        f"{budget.estimate(characters, budget.INITIAL_RATIO):>8,} tokens at ratio 1.3"
    )


def test_measure_the_system_context():
    steering = sum(len(f.text.strip()) for f in system.bundled_steering())
    project = len(system.project_context(shop_api_retro_md()))
    index = len(skills.skills_index(skills.discover([skills.bundled_location()])))
    total = len(reference_system_context())
    print()
    print(row("Bundled steering", steering))
    print(row("Project context", project))
    print(row("Skills index", index))
    print(row("System context", total))
    assert steering + project + index < total


def test_measure_the_tool_definitions_of_each_tool_set():
    """Characters of the definitions that exist now, per tool set in mode default; NOT FINAL while tools are missing."""
    servers = existing()
    absent = {tools.normalize(name) for name in missing()}
    documented = [tools.normalize(name) for name in DOCUMENTED if tools.normalize(name) not in tools.USER_ONLY]
    print()
    print(f"Tool definitions as they exist now: {len(documented) - len(absent)} of {len(documented)} tools; NOT FINAL")
    largest = 0
    for tool_set, entries in [*tools.TOOL_SETS.items(), ("free message", None)]:
        definitions = tools.tool_definitions(servers, mode="default", tool_set=None if entries is None else tool_set)
        characters = sum(definition_characters(d) for d in definitions)
        wanted = [n for n in documented if entries is None or tools.in_tool_set(n, entries)]
        still_missing = [n for n in wanted if n in absent]
        print(row(f"{tool_set} ({len(definitions)}/{len(wanted)})", characters), f"  {len(still_missing)} missing")
        assert len(definitions) + len(still_missing) == len(wanted)
        largest = max(largest, characters)
    assert largest > 0
