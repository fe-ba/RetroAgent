"""Measure of the fixed part of the context that exists in this session: the system context, which holds the
bundled steering, the project context of shop-api and the skills index. Tool definitions are added when the
servers exist (build-plan.md, Measuring the context). Run with ``pytest -s`` to see the figures."""

from test_context_system import reference_system_context, shop_api_retro_md

from retroagent.context import budget, skills, system


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
