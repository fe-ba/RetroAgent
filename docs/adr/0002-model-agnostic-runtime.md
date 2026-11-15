# ADR-0002: Model-agnostic runtime

- **Status:** Superseded by ADR-0026
- **Date:** 2026-11-14

## Context

RetroAgent must work with local models and with hosted models from different vendors (Anthropic, OpenAI, xAI, Google). Existing agent hosts such as Claude Code or Kiro only run their own models, and their extension formats are read only by them.

## Decision

RetroAgent implements its own runtime in Python: it builds the context, calls the model, dispatches tools and repeats until the task is done.

## Alternatives considered

- **Run inside Claude Code:** native skills and MCP, but limited to Anthropic models.
- **Run inside Kiro:** native steering, but same vendor lock-in.
- **Agent framework (e.g. LangChain):** less code to write, but heavy abstractions and less control over the loop, which the test-state guarantees depend on.

## Consequences

- RetroAgent must provide what agent hosts already include: the loop, permissions, plan mode and skill loading.
- Behavior can be compared across models, which becomes part of the evaluation.
- Runtime quality depends entirely on this project.
