# ADR-0023: Test case identity and maintenance

- **Status:** Accepted
- **Date:** 2026-11-15

## Context

ADR-0016 separates test cases from test executions, and ADR-0010 makes the JUnit XML the only source of results. A review of the data model and the tools found that several questions about the life of a test case had no answer, or had two:

- The project suite was discovered with a full run, but the run tool refused to run when no test case was known.
- Nothing said how a generated test, stored as a file and a function name, is matched to an entry of the JUnit XML, nor what happens to a test case that the XML does not report.
- A generated test that triage found wrong could not be corrected, an obsolete test case could not be taken out of use, and a wrong triage could not be replaced, although reports list those items "for review".
- The baseline run used for comparison was "the latest", whatever commit it had run on.
- Records were declared immutable, but one tool replaced them.

## Decision

1. **Discovery by execution.** The tests of a project are learned from the JUnit XML of a full run. A run with scope `all` runs the test command as configured and needs no known test case. There is no listing step.
2. **Identity.** A test is its JUnit entry, `<classname>::<name>`; each case of a parametrized test is a test case. A generated test is bound to its test case by its function name and its file, which are unique among generated tests and never change. Generated tests are not parametrized.
3. **Unreported test cases are blocked.** A test case that a run was asked to execute and that the JUnit XML does not report gets an execution with status `blocked` and reason `not_reported`. It is never left without a record and never counted as skipped.
4. **Rewrite.** The code of a generated test can be written again. The test case keeps its identifier, gets a new revision, and each execution records the revision that ran. Design fields that describe the code change only together with the code, in the same call.
5. **Retire.** A test case can be retired with a reason. It keeps its history, cannot be selected, and its generated test is no longer run. Retiring is permanent.
6. **Triage history.** An execution can be triaged again. Every triage is kept, the latest one is current, and executions triaged more than once are listed for review.
7. **Comparisons are tied to commits.** The evaluated run is a suite run on the candidate commit; the baseline run and the full runs are looked up by the commits of the analysis that the suite was selected for.
8. **Append only.** The impact of an analysis is written once. A corrected impact needs a new analysis, which starts a new cycle with its own suite.

## Alternatives considered

- **A listing command per framework (for example `pytest --collect-only`):** discovers tests without running them, also in plan mode, but its output is framework-specific and its names do not match the JUnit XML. It contradicts ADR-0010.
- **Mark unreported test cases as skipped:** a generated test whose file fails to load against the candidate would disappear from the execution rate.
- **A new test case for every correction:** no rewrite tool is needed, but the suite fills with dead test cases and the history of a test is split.
- **Delete obsolete test cases:** contradicts the rule that history is kept.
- **One triage per execution, never replaced:** simplest, but a wrong classification that excuses a failure could not be corrected.
- **Latest run of each role, whatever its commit:** simple, but after a second cycle it compares versions that were never analyzed together.

## Consequences

- The first cycle on a project needs a full run against the baseline before selection. In plan mode, only test cases already known can be selected.
- Tests added by the change are discovered only by a full run against the candidate; the selection skill asks for it when the change set touches test files.
- Generated tests that do not load in a version are visible as `blocked`. In compiled languages a single generated test that does not compile can still block a whole run; this is a limitation of running the same tests on both versions.
- `tests.select` matches by name, so a selection may run more tests than asked; their results are ignored.
- The model can read the code of its own generated tests, which the git tools cannot provide because that code is not in the versions under test.
- Retiring and triaging again are judgments of the model, like selection. They are recorded with the model that made them and listed for review.
