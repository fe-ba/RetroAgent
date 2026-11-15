# ADR-0019: Item templates

- **Status:** Accepted
- **Date:** 2026-11-15

## Context

ADR-0018 defines templates as Markdown without logic, where variable-length data is inserted as blocks built by code. Two reports repeat a detailed section for every element: the test case specification (objective, preconditions, input data, steps, expected result) and the defect report (expected and actual result, steps to reproduce, evidence). Built as blocks, their layout would live in code and could not be edited, although it is the most important content of those reports.

## Decision

A fourth marker extends ADR-0018:

| Marker | Form | Replaced by |
|---|---|---|
| Items | `{{ items:test_case }}`, alone on its line | The item template rendered once per element. |

- The item template for `{{ items:<name> }}` is `templates/items/<name>.md`, with underscores written as hyphens (`items:test_case` uses `items/test-case.md`).
- Item templates are Markdown without logic, like every other template. Inside them, values refer to the current element (`{{ test_case.id }}`), and blocks and agent sections are scoped to it.
- Item templates cannot contain `items` markers: there is no nesting.
- Item templates follow the same language lookup as other templates.

## Alternatives considered

- **Blocks built by code:** consistent with ADR-0018, but the layout of a test case or a defect could not be edited.
- **One document per element:** no new marker, but a specification with dozens of test cases becomes dozens of files.
- **Loops in a template language:** rejected in ADR-0018.

## Consequences

- The layout of test cases and defects is editable Markdown.
- An agent section inside an item template costs one model call per element; item templates should contain few of them.
- Report generation validates that every `items` marker has its item template.
