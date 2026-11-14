# ADR-0009: Git worktrees for version checkout

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

Comparing baseline and candidate requires both versions on disk. Checking out versions in the user's directory would change their files and could destroy uncommitted work.

## Decision

The agent creates temporary checkouts of each version with `git worktree` under `.retro/worktrees/` and runs tests there.

## Alternatives considered

- **`git checkout` in the working copy:** risks losing uncommitted work.
- **Copy the repository:** safe, but slow and wasteful on large projects.

## Consequences

- The user's working copy is never modified; this is also a rule in `steering/05-safety.md`.
- Target projects must be git repositories; non-git projects cannot be compared by version.
- Worktrees must be cleaned up after runs.
