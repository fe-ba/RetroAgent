# ADR-0015: Generated tests stored in .retro

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

RetroAgent writes test code for the test cases it designs. Writing it into the project tree would modify the user's working copy, contradicting ADR-0009. It would also not work: runs happen in worktrees of the baseline and the candidate, where files added to the working copy do not exist.

## Decision

Generated tests are stored in `.retro/tests/`. Before each run, they are copied into the worktree at `tests.generated_dir`, so they run with the project's own test setup against every version.

## Alternatives considered

- **Write into the project tree (e.g. `tests/retro/`):** modifies the working copy and the tests are missing from version worktrees.
- **Commit generated tests to a branch:** visible in git history, but alters the user's repository.

## Consequences

- The user's working copy is never modified. During runs, the only write outside `.retro/` is the worktree metadata git keeps in `.git/worktrees/`, removed after each run.
- The same generated tests run against baseline and candidate, which is what a regression comparison needs.
- Generated tests can be versioned and reviewed in `.retro/tests/`. Adopting them into the project's own suite is a manual decision.
- A new command, `/implement`, makes the transition from `designed` to `implemented` explicit.
