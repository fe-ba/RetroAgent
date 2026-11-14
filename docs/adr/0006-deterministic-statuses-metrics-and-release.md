# ADR-0006: Deterministic statuses, metrics and release decision

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

The agent must never claim a test was executed when it was only designed. Language models can hallucinate results, and weaker models are more likely to.

## Decision

Code, not the model, records test statuses and results, computes metrics, evaluates exit criteria and produces the release decision. The model only writes the narrative interpretation.

## Alternatives considered

- **Rely on steering rules:** necessary but not sufficient; a rule in a prompt can be ignored.
- **Model computes metrics from raw results:** flexible, but arithmetic and judgment become unverifiable.

## Consequences

- A weak model can write worse prose but cannot falsify results.
- Reports visually separate computed sections from agent-written sections.
- Exit criteria and the decision rule must be fully specified in `docs/reference/metrics.md`.
