# ADR-0001: Standalone terminal agent

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

The first design kept the system under test inside the agent repository. Checking out another version of the system under test would also change the agent's own code, and the agent would be tied to a single project.

## Decision

RetroAgent is an installable tool that runs on any target project, either from the project directory or by receiving its path. It contains no target project.

## Alternatives considered

- **System under test inside the repository:** version checkouts collide with the agent's code and the agent is not reusable.
- **System under test as a git submodule:** avoids the collision but still couples the agent to one project.

## Consequences

- Steering, skills and templates must ship inside the installed package, because the agent runs from any directory.
- The demonstration project becomes an example that is materialized into its own directory with its own git history.
- The agent must handle unknown projects: detect their type and ask for missing information.
