# Regression strategy

Regression testing asks one question: does the candidate version keep the behavior of the baseline, except where the behavior was meant to change? This document explains how RetroAgent turns a change between two versions into an answer: what it analyzes, what it selects, what it adds, how it runs and how it interprets failures. The step-by-step version is [Your first regression cycle](../tutorials/first-regression-cycle.md).

## Start from the change

Running every test after every change is safe but does not scale, and it says nothing about what the change put at risk. RetroAgent starts from the change instead.

**Impact analysis.** Code computes the change set between the two commits with git: every added, modified, deleted or renamed file, with its lines. The model reads the diffs and decides which modules and requirements the change affects, with a risk level and a reason for each. It must decide every requirement in effect: each one is either impacted, or not impacted with a reason. A requirement cannot be skipped by omission. `RETRO.md` describes which module serves which requirement, which helps the model map files to requirements.

**Documented changes.** A requirement can declare that it changed in a version (`Changed: v1.1 - ...`). Code decides whether that entry applies to the comparison: it does when the commit of its version is reachable from the candidate and not from the baseline. This is what later separates an intended change from a regression.

## Know the tests that exist

RetroAgent learns the project's tests by running them: a full run on the baseline records every test of the JUnit XML as a test case, linked to the requirements named in its test name. When the change adds tests, a full run on the candidate finds them too. A full run is never repeated on a commit that already has one.

Full runs on both versions also answer a question that selection depends on: which tests changed verdict. A test that passed on the baseline and fails on the candidate is the clearest evidence of a regression, or of an intended change.

## Select a suite

The model chooses the test cases that can reveal whether the change broke something, orders them by priority, and gives a reason for each one. Code enforces what a safe selection needs:

- Every test whose verdict differs between the full runs of the two versions must be in the suite, or left out with a reason. A test that passed on the baseline and failed on the candidate must be in it.
- Every test traced to an impacted requirement must be selected, or left out with a reason.
- The impacted requirements left without any test are computed and reported as gaps.

Selection is measured afterwards with the framework of Rothermel and Harrold: **inclusiveness**, the share of revealing tests that were selected (1.0 is a safe selection), and **precision**, the share of non-revealing tests that were left out. These metrics are informative: they say how well the agent selected, and never decide the release.

## Fill the gaps

An impacted requirement without a test is a part of the change that nothing checks. The model designs test cases for it: objective, preconditions, concrete input data, steps and an expected result, traced to the requirement. Then it implements them as code in `.retro/tests/`, following the conventions of the project.

Generated tests run against both versions, like the tests of the project. A correct test for a requirement that did not change passes on both. One that passes on the baseline and fails on the candidate has found something.

Generated tests stay outside the project tree. Adopting them into the project's own suite is a decision for the user.

## Run both versions

The suite runs on the baseline and on the candidate, each in a fresh worktree outside the project, with the project's own setup and test commands. Results come only from the JUnit XML.

Comparing the verdict of each test on the two versions gives four outcomes:

| Baseline | Candidate | Outcome |
|---|---|---|
| passed | not passed | New failure: the candidate lost a behavior. |
| not passed | passed | Fixed. |
| not passed | not passed | Persistent failure: not caused by this change. |
| passed | passed | Stable pass. |

Every test that does not pass at its first attempt is rerun, twice by default. The result stays the one of the first attempt; the reruns only reveal whether the test is flaky. A flaky failure is still a failure: flaky tests can hide real faults, and a new flaky failure still blocks the release.

## Explain every failure

Each failed execution of the candidate run gets one classification:

| Classification | Meaning | Checked by code |
|---|---|---|
| `regression` | The product no longer behaves as required. Needs a defect. | The test did not also fail on the baseline. |
| `expected_change` | A requirement changed on purpose; the test must be updated. | A documented change of a traced requirement applies to this comparison. |
| `pre_existing` | The test already failed on the baseline. | It did fail on the baseline. |
| `flaky` | The result changes across attempts. | At least one rerun passed. |
| `test_defect` | The test itself is wrong. | Judgment of the model, listed for review. |
| `environment` | Infrastructure failed, not the product. | Judgment of the model, listed for review. |

The four classifications that the records can confirm are refused when the records do not support them. The model cannot call a regression an expected change unless the requirement says it changed. Every regression needs a defect, with a severity, steps to reproduce and a probable cause.

## Decide

Metrics, exit criteria and the decision are computed by code from these records ([Metrics and exit criteria](metrics-and-exit-criteria.md)). The most important criterion for a regression cycle is EC-09: a test that passed on the baseline and fails on the candidate, without a documented reason, blocks the release. It does not depend on any severity the model chose.

## What the strategy cannot see

- A behavior that no test checks: selection only chooses among tests that exist or that the agent designs.
- A change that a test observes without asserting on it: verdicts compare pass and fail, not outputs.
- Flakiness that two reruns do not reveal.

[Limitations and risks](limitations-and-risks.md) lists these and the other limits.
