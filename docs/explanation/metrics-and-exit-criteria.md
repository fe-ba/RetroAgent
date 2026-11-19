# Metrics and exit criteria

Why the release decision is computed by code, what each exit criterion protects, and how to read a decision. The formulas, thresholds and sources are in the [metrics reference](../reference/metrics.md); this document explains the choices behind them ([ADR-0006](../adr/0006-deterministic-statuses-metrics-and-release.md), [ADR-0017](../adr/0017-test-metrics-basis.md), [ADR-0022](../adr/0022-release-decision-guards.md)).

## Why code decides

A language model is good at explaining a result and bad at being one. Asked for a pass rate, it can round, miscount or simply state a number that sounds right. Asked whether a version can be released, it can be persuaded by a confident comment in the code. Neither is acceptable in a testing tool.

So the line is drawn sharply. The model judges what needs judgment: which requirements are impacted, which tests to select, why a test failed. Code computes everything that can be computed, from stored records: every metric, every exit criterion and the decision. The model then explains the result, and cannot change it. The same records always give the same decision, which can be reproduced from project memory at any time.

## One evaluated run

Metrics describe one **evaluated run**: the latest completed run of the selected suite on the candidate. It is compared with the latest completed run on the baseline. Both are on the two commits of the impact analysis; runs on other commits are never mixed in.

The result of an execution is the result of its **first attempt**. Reruns reveal flakiness, but never turn a failure into a pass. Otherwise, rerunning until green would always produce a release.

## Two pass rates

`pass_rate` is the plain share of executed tests that passed. It cannot tell a broken product from a test that needs updating after an intended change.

`product_pass_rate` leaves out **excused** failures: those triaged as `expected_change` (a documented requirement change) or `test_defect` (the test is wrong). It is the pass rate the exit criteria use. Excusing a failure is therefore a strong act, and two safeguards apply. `expected_change` is accepted only when code finds a documented change that applies to the comparison. Every excused execution is listed in the report for review.

A `pre_existing` failure, one that the baseline already had, is not excused. It counts against the product pass rate and adds a condition to the decision: the problem is real, even if this change did not cause it.

## The exit criteria

| ID | Criterion | Protects against | Blocking |
|---|---|---|---|
| EC-01 | Product pass rate at or above its threshold | Releasing a product whose tests mostly fail. | Yes |
| EC-02 | Every high-priority test case executed | Leaving the riskiest tests unrun, for example because they were blocked. | Yes |
| EC-03 | Impacted requirements covered by executed tests | Releasing a change that nothing checked. | No |
| EC-04, EC-05 | No open critical or high defects | Releasing with a known serious fault. | Yes |
| EC-06 | Open medium defects within the limit | Accumulating smaller faults. No limit by default. | No |
| EC-07 | Flaky rate within its limit | A suite too unstable to trust. | No |
| EC-08 | Every failure triaged, and every regression linked to a defect | Releasing with failures nobody explained. | Yes |
| EC-09 | No unexcused new failures | Losing a behavior the baseline had. | Yes |

**EC-09 is the heart of regression testing.** A test that passed on the baseline and fails on the candidate, without a documented reason, blocks the release. It does not depend on the severity of any defect, which is a judgment of the model, nor on the pass rate, which a large suite can keep high. In the example project, the decision for `v1.0` to `v1.1` is `do_not_release` whatever severity the model gives to the shipping defect, because EC-09 is not met.

Blocking criteria protect the release; non-blocking ones become conditions that the report lists. Thresholds come from the configuration and can be set per project. Their defaults are common conventions, not values required by a standard.

## A criterion that cannot be evaluated

When a criterion cannot be evaluated, for example because there is no run on the baseline to compare with, it is `not_evaluable`, and a blocking criterion that is `not_evaluable` blocks the release like one that is not met. Nothing is released on missing evidence.

## The decision

The first rule that matches decides:

1. Any blocking criterion not met or not evaluable: **`do_not_release`**.
2. Any non-blocking criterion not met or not evaluable, or any excused, pre-existing or designed-only test case: **`release_with_conditions`**, with one condition per cause.
3. Otherwise: **`release`**.

In the command line, `do_not_release` exits with code `3`, so a pipeline can use the decision as a gate.

## Metrics that do not decide

Some metrics inform without deciding:

- **Selection quality.** Inclusiveness and precision, measured against full runs on both versions, say how well the agent chose the suite. A metric of the agent's own judgment should not be able to block a release.
- **Comparison counts.** New failures, fixed, persistent failures and stable passes describe what the change did.
- **Time.** Run duration and test time.

## Reading the numbers with care

- A high pass rate says only that the executed tests passed. Read it with the execution rate and the requirement coverage.
- The flaky count is a lower bound: two reruns find only part of the flakiness.
- The inputs of the decision remain judgments of the model: the suite, the impacted requirements, priorities, severities and three triage classifications. Code computes the decision from them correctly; it cannot make them right. That is why the report lists what needs review.
- Code coverage is not measured.
