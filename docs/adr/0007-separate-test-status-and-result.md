# ADR-0007: Separate test status and result

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

An early design used one sequence of states (designed, executed, passed). It mixed the life cycle of a test case with its outcome, and nothing prevented storing "passed" without an execution.

## Decision

A test case has two fields:

- `status`: `designed`, `implemented`, `executed`, `blocked`, `skipped`.
- `result`: `passed`, `failed`, `error`. It exists only when `status = executed` and a `run_id` with stored evidence exists.

The constraint is enforced in the data layer.

## Alternatives considered

- **Single status field:** simpler, but cannot enforce that a result requires an execution.

## Consequences

- Distinguishing designed, executed and passed is guaranteed by the data model.
- Every query and report must read both fields.
