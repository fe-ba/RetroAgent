# ADR-0013: Diataxis documentation and spec split

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

The documentation serves three audiences: users of `retro`, whoever builds RetroAgent, and course evaluators. Mixing them produces documents that serve none well and duplicate information.

## Decision

- `docs/` follows Diataxis: `tutorials/`, `how-to/`, `reference/` and `explanation/`, for users.
- `spec/` contains only internal specification: build plan, requirements, acceptance scenarios, runtime, providers, context loading and data model.
- Public interfaces (CLI, configuration, project contract, MCP tools, metrics, reports, glossary) live only in `docs/reference/`; builders read them there.
- `docs/adr/` records decisions and sits outside the four Diataxis quadrants.

## Alternatives considered

- **Numbered topic documents:** mixes audiences.
- **Reference duplicated in `spec/`:** two sources of truth that drift apart.

## Consequences

- Each fact lives in one place. If `docs/` and `spec/` conflict, `spec/` wins and the conflict is reported.
- Tutorials and how-to guides are written after the code works, to avoid documenting invented behavior.
