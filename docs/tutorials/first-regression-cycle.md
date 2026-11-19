# Your first regression cycle

In this tutorial you take the example project `shop-api` from `v1.0` to `v1.1` through a whole regression cycle, one step at a time: impact analysis, discovery of the existing tests, selection, design and implementation of a new test, execution on both versions, triage of the failures and the completion report. At the end you know whether `v1.1` can be released, and why.

It continues [Getting started](getting-started.md): you need RetroAgent installed, a model configured and the example created in `~/retro-demo`. With a hosted model it takes about twenty minutes, most of it reading what the agent did.

The example has known answers, written in its oracle. They are given below so that you can check the agent. Figures that depend on choices of the model, such as the number of test cases in the suite, can differ a little from run to run. The decision and its reasons must not.

## 0. Start the session

```
cd ~/retro-demo
retro --base v1.0 --candidate v1.1
```

The session runs in mode `default`: the agent asks before it runs tests, starts the service of the project or writes test code. Answer each question as it comes.

## 1. Analyze the impact

```
/analyze
```

The agent loads the skill `impact-analysis`. It reads the requirements of both versions, computes the change set with git, reads the diff of each changed file, and records which modules and requirements the change affects, with a risk level for each.

What to check in its answer:

- `src/shop/pricing.py` and `src/shop/discounts.py` are impacted, with high risk.
- REQ-004 (coupons) is a documented change: the requirements file says it changed in `v1.1`.
- REQ-005 (shipping) is impacted.
- REQ-008 (order history) is new.
- REQ-002 (stock check) is impacted, because `src/shop/cart.py` changed.

The agent must record a decision for every requirement: impacted, or not impacted with a reason. The `memory` server refuses an impact that leaves one out. This is the first of many checks done by code rather than by the model.

## 2. Discover the existing tests

RetroAgent does not know the tests of the project until it has run them. Run the whole suite on the baseline:

```
/run all --on base
```

The first run asks you to approve the commands of the project: the setup, the test command and the service. Read them: they come from `.retro/config.yaml`, which is part of the project, and RetroAgent runs nothing from a project you have not approved. The approval is stored in `~/.retro/approvals.json` and asked again only if a command changes. Then the agent asks for permission to run tests and to start the service.

Each run happens in a temporary git worktree outside the project, so your working copy is never touched. Expect RUN-0001: 22 tests, 20 passed and 2 failed. Every test becomes a test case, TC-001 to TC-022, linked to its requirement by the number in its name.

The change adds tests in `v1.1`, so run the whole suite on the candidate too:

```
/run all --on candidate
```

Expect RUN-0002: 26 tests, 22 passed and 4 failed. The four new tests become TC-023 to TC-026.

`/history` shows both runs as a table.

## 3. Select the regression suite

```
/select
```

The agent loads `test-selection` and chooses the test cases that can reveal whether the change broke something, each with a reason and a priority. The suite of this example is small, so a good selection takes almost everything.

Two rules are enforced by code. Every test that passed on the baseline and failed on the candidate in the full runs must be in the suite: here, the shipping test. Every test traced to an impacted requirement must be selected or left out with a reason. The answer also lists the impacted requirements that have no test at all: REQ-002 has none.

## 4. Design and implement a test for the gap

```
/design
```

The agent loads `test-design` and designs at least one test case for REQ-002: an objective, preconditions, concrete input data, steps and an expected result. For example, adding a quantity above the stock of a product must be rejected. The test case has status `designed`: it exists as a specification, not as code.

```
/implement
```

The agent writes the test code in `.retro/tests/`, after asking you for permission, and the test case becomes `implemented`. The name follows the convention of `RETRO.md`: `test_req_002_<description>`. Generated tests are kept apart from the tests of the project, which RetroAgent never edits.

## 5. Run the suite on both versions

```
/run --on both
```

The suite runs on `v1.0`, then on `v1.1`. Every test that does not pass at the first attempt is run twice more, so that a flaky test can be told apart from a real failure. Results come only from the JUnit XML that pytest writes: the model has no tool that sets a result.

Expect, on the candidate, four failures among the tests of the project. Your new REQ-002 test passes on both versions.

```
/status
```

shows the test cases by status and the executions of the last run by result.

## 6. Triage the failures

```
/triage
```

The agent loads `failure-triage`, reads the evidence of each failure (the JUnit entry, the log, the history of the test) and classifies it:

| Test | Classification | Why |
|---|---|---|
| Shipping charged when a discount drops below the threshold | `regression` | It passed on `v1.0` and fails on `v1.1`. `pricing.py` now computes shipping on the subtotal before discounts, against REQ-005. |
| Second coupon is rejected | `expected_change` | REQ-004 changed in `v1.1`: two coupons can now be combined. The test still asserts the old rule. |
| Search results are sorted by name | `flaky` | It failed at the first attempt and passed in both reruns. |
| Tax rounds half up | `pre_existing` | It also fails on `v1.0`. |

Each classification is checked against the evidence. Had the agent classified the shipping failure as an expected change, the `memory` server would have refused it, because REQ-005 has no documented change for this version. You can try it: ask the agent to reclassify that failure as `expected_change`. The agent cannot excuse a regression by saying so.

For the regression, the agent registers a defect, DEF-001, with a severity, the steps to reproduce and the probable cause. `/defects` lists it.

## 7. Read the decision and the report

```
/report completion
```

Code computes every metric, the state of each exit criterion and the release decision. The agent writes only the narrative sections, from that data, and the report is rendered in `.retro/reports/` as Markdown, and as PDF when Pango is installed.

The decision is **`do_not_release`**:

- EC-09 is not met: one test that passed on the baseline fails on the candidate and is not excused.
- EC-05 is not met: there is an open defect of severity `high`.
- EC-01 is not met when the product pass rate is under the 90% that the project requires.

The decision is the same whatever severity the model gives to the defect, because EC-09 does not depend on it. The agent can explain the decision, but it cannot change it: the figures, criteria and decision in the report are inserted by code, and the agent's sections are written from them.

End the session with `/exit`.

## 8. The fix, in cycle 2

`v1.2` fixes the shipping cost. Compare it with `v1.1`, this time with the whole cycle in one command:

```
retro --base v1.1 --candidate v1.2
```

```
/cycle
```

`/cycle` runs the same steps you ran by hand, in the same order, and checks the outcome of each one before the next. The shipping test now passes: it is `fixed`, and the run closes DEF-001, because every test linked to it passed. The decision is **`release_with_conditions`**: the tax rounding test still fails, but it already failed on the baseline.

## What you learned

- A regression cycle compares two versions: the change decides what is analyzed, selected and designed.
- The model judges: what is impacted, what to select, which tests are missing, why a test failed. Code decides: results, metrics, exit criteria and the release decision.
- Every judgment that can be checked against evidence is checked, and refused when it does not hold.

To use RetroAgent on a project of your own, see [Set up a project](../how-to/set-up-a-project.md). To run the cycle in a script or in CI, see [Run in CI](../how-to/run-in-ci.md).
