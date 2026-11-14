# ADR-0003: LLM provider interface with LiteLLM

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

Each vendor has its own API and its own tool-calling format. The runtime needs one way to talk to all of them.

## Decision

The runtime depends only on an internal `LLMProvider` interface. The default implementation uses LiteLLM, which normalizes vendors to a single format. Models without tool calling use a fallback mode with validated JSON responses.

## Alternatives considered

- **One adapter per vendor:** full control, but large effort and maintenance.
- **LiteLLM used directly across the code:** less code, but the whole project becomes coupled to the library.

## Consequences

- LiteLLM can be replaced without touching the runtime.
- Minimum model requirement: tool calling, or acceptable JSON output in fallback mode.
- Small local models may perform poorly; this is documented as a limitation.
