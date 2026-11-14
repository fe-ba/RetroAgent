# ADR-0012: English as project language

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

The project mixed Spanish and English names. Text in Spanish consumes more tokens for the coding agent that builds the project and for the models that read steering and skills.

## Decision

Everything in the project is written in English: names, code, documentation, steering, skills and templates. Translations are created separately only when needed. The language of the agent's responses and reports is a configuration setting.

## Alternatives considered

- **Spanish documentation, English code:** breaks internal consistency.
- **Bilingual files:** doubles maintenance and context size.

## Consequences

- Lower token usage and better instruction following, especially for small local models.
- Course deliverables in Spanish require translating the relevant documents.
