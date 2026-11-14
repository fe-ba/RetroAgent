# ADR-0011: Terminal agent conventions

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

Users already know terminal agents such as Claude Code. Following their conventions makes RetroAgent immediate to adopt.

## Decision

RetroAgent follows the same conventions:

- Short command (`retro`) with an interactive session and a non-interactive mode.
- `RETRO.md` as the project context file, created by `/init`.
- `.retro/` at project level and `~/.retro/` at user level.
- Slash commands inside the session.
- Plan mode, in which tests can be designed but not executed.
- Permission prompts before running tests, starting services or writing test code.

## Alternatives considered

- **Custom subcommand-only CLI:** valid, but unfamiliar and without an interactive session.

## Consequences

- Minimal learning curve for users of other terminal agents.
- Plan mode maps to designed tests and approved execution maps to executed tests, reinforcing ADR-0007.
- Final command names and arguments are defined in `docs/reference/cli.md`.
