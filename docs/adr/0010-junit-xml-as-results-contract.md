# ADR-0010: JUnit XML as results contract

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

RetroAgent must work with projects in any language and test framework. Parsing each framework's console output is fragile and endless.

## Decision

The test runner executes a configured command and reads its results only from JUnit XML, a format produced by pytest, Jest, Maven, Gradle, Go and most other frameworks.

## Alternatives considered

- **One parser per framework:** precise, but unbounded effort.
- **Let the model read console output:** contradicts ADR-0006.

## Consequences

- The runner is generic: only the command and the report path are configured.
- Projects that cannot produce JUnit XML are not supported; documented as a limitation.
