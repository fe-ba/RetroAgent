# ADR-0016: Test executions per run

- **Status:** Accepted
- **Supersedes:** ADR-0007
- **Date:** 2026-11-14

## Context

ADR-0007 placed both `status` and `result` on the test case. In regression testing the same test case runs against the baseline and the candidate, and again in every later run. A single pair of fields cannot hold "passed on `v1.0`, failed on `v1.1`", which is exactly the evidence of a regression. Each new run would overwrite the previous one, losing the history that ADR-0008 requires and that flaky detection depends on. Being executed is not a property of a test case but of a run.

## Decision

Two entities hold what ADR-0007 kept in one:

- **Test case** `status`: `designed` or `implemented`. Its life cycle, independent of any run.
- **Test execution**: one test case in one run.
  - `status`: `executed`, `blocked` or `skipped`.
  - `result`: `passed`, `failed` or `error`. Exists only when `status` is `executed`.
  - Always belongs to a run with stored evidence. Enforced in the data layer.

Reruns of a failed test case within a run, used for flaky detection, are attempts of the same test execution.

## Alternatives considered

- **Keep status and result on the test case (ADR-0007):** cannot compare versions and loses history.
- **Latest result on the test case plus a history table:** two sources of truth that can disagree.

## Consequences

- Designed, executed and passed are answered at different levels: test case, test execution and its result.
- "Did TC-004 pass?" always requires a run, and therefore a version. Reports always reference runs.
- Metrics are computed per run, and comparisons are made between runs.
- The model cannot set an execution status or result: only the test runner creates test executions, from parsed evidence.
