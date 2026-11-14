# ADR-0008: Project-local SQLite memory

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

Regression testing depends on history: baselines, previous runs, flaky test detection and open defects. The model itself remembers nothing between sessions.

## Decision

Each target project stores its long-term memory in `.retro/retro.db` (SQLite), next to its runs and reports, in the same way git stores history in `.git/`.

## Alternatives considered

- **Central database under `~/.retro/`:** mixes projects and does not travel with the project.
- **Database server:** unnecessary installation and operation cost.

## Consequences

- Memory travels with the project and requires no extra software.
- `/init` creates `.retro/.gitignore`: configuration, custom skills and reports can be versioned; the database, run evidence and worktrees cannot.
- Concurrent sessions on the same project need care; documented as a limitation.
