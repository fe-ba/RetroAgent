"""Measure of the fixed part of the context (build-plan.md, Measuring the context; context-loading.md, Limits at
start). Run with ``pytest -s`` to see the figures.

The fixed part of a call is the system context (the bundled steering, the project context of shop-api and the skills
index), the tool definitions of the tool set and the state message, here the snapshot of the reference scenario. A
model command or a step of /cycle also loads its skill into the conversation; its size is printed beside the fixed
part, because every call of the step carries it. The figures are checked against a window of 32,768 tokens with an
output reserve of 4,096, the profile of the presentation (build-plan.md, Models for development).
"""

from pathlib import Path

from fixtures.tool_definitions import DOCUMENTED, existing
from test_context_system import reference_system_context, shop_api_retro_md

from retroagent.context import budget, skills, system, tools
from retroagent.llm.provider import Message, definition_characters
from retroagent.runtime import tools as runtime_tools

STATE_MESSAGE = Path(__file__).parent / "snapshots" / "state_message.md"
BUDGET = budget.Budget(window=32_768, output_reserve=4_096)
STEP_SKILLS = {
    "analyze": "impact-analysis",
    "select": "test-selection",
    "design": "test-design",
    "implement": "test-design",
    "triage": "failure-triage",
    "report": "test-reporting",
}


def tokens(characters: int) -> int:
    return budget.estimate(characters, budget.INITIAL_RATIO)


def row(label: str, characters: int) -> str:
    return (
        f"{label:<22}{characters:>8,} characters{characters // 4:>8,} tokens at /4"
        f"{tokens(characters):>8,} tokens at ratio 1.3"
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


def test_every_documented_tool_has_a_definition():
    servers = {"runtime": runtime_tools.DEFINITIONS, **existing()}
    defined = {tools.exposed_name(server, d.name) for server, found in servers.items() for d in found}
    assert defined == {tools.normalize(name) for name in DOCUMENTED}


def test_the_fixed_part_of_every_tool_set_stays_under_half_of_the_budget():
    """Final figures: every tool exists. Mode default, which exposes the most tools."""
    servers = {"runtime": runtime_tools.DEFINITIONS, **existing()}
    system_context = reference_system_context()
    state = Message(role="user", content=STATE_MESSAGE.read_text(encoding="utf-8"))
    found = skills.discover([skills.bundled_location()]).available
    half = budget.REFUSE_SHARE * BUDGET.tokens
    print()
    print(
        f"Budget {BUDGET.tokens:,} tokens (window {BUDGET.window:,} minus reserve {BUDGET.output_reserve:,});"
        f" half is {half:,.0f}. System context {len(system_context):,} characters; state message"
        f" {len(state.content):,} characters."
    )
    print(
        f"{'Tool set':<14}{'Tools':>6}{'Definitions':>13}{'Fixed part':>12}{'Tokens':>8}{'Share':>8}"
        f"{'Skill':>8}{'+ skill':>9}{'Share':>8}"
    )
    for tool_set in [*tools.TOOL_SETS, None]:
        definitions = tools.tool_definitions(servers, mode="default", tool_set=tool_set)
        definition_size = sum(definition_characters(d) for d in definitions)
        fixed = budget.fixed_characters(system_context, definitions, state)
        skill = len(found[STEP_SKILLS[tool_set]].body) if tool_set else 0
        with_skill = tokens(fixed + skill)
        print(
            f"{tool_set or 'free message':<14}{len(definitions):>6}{definition_size:>13,}{fixed:>12,}"
            f"{tokens(fixed):>8,}{tokens(fixed) / BUDGET.tokens:>8.1%}{skill:>8,}{with_skill:>9,}"
            f"{with_skill / BUDGET.tokens:>8.1%}"
        )
        assert tokens(fixed) < half, tool_set
