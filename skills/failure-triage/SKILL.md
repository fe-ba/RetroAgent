---
name: failure-triage
description: Classify each failed or error execution of a run as regression, expected_change, flaky, environment or test_defect with a justification, and register, link or close defects. Use for /triage, or when asked why tests failed.
---

# Failure triage

Explain every failed or error execution of a run, so that the release decision can be trusted. Exit criterion EC-08 requires every failure of the evaluated run to be triaged, and every `regression` to be linked to a defect.

## Procedure

1. **Run.** The run given by the user, or the latest one (`memory.get_runs` with `limit` 1). If its status is `error`, its executions are `blocked`: there is nothing to classify. Read `test_runner.get_evidence`, report the step that failed, and stop.
2. **Failures.** Call `memory.get_executions` with the run ID and `untriaged` `true`. If there are none, say so.
3. **Evidence**, for each execution:
   - `test_runner.get_evidence` with the run and the test case: failure message of each attempt and the log;
   - `memory.get_test_case_history`: result against the baseline, earlier results, flakiness;
   - `memory.get_test_cases` and `memory.get_requirements`: traced requirements and their documented changes;
   - `git.get_diff` or `git.read_file` for the code the failure points to.
4. **Classify.** Apply the first rule that matches:

   | Order | Classification | When |
   |---|---|---|
   | 1 | `flaky` | The attempts of the execution produced different results, or the history shows the test alternating without a related change. |
   | 2 | `environment` | The failure comes from infrastructure: service not reachable, timeout of an external resource, missing third-party dependency, port or file permission problem. |
   | 3 | `expected_change` | A traced requirement has a `Changed` or `Removed` entry for the candidate, and the failure matches that documented change. |
   | 4 | `test_defect` | The test itself is wrong: its assertion contradicts the requirement, its data is invalid, or it has an error of its own. |
   | 5 | `regression` | The product does not behave as required. |

   - `expected_change` and `test_defect` remove the failure from the product pass rate. Use them only with concrete evidence: a documented requirement change, or a specific error in the test. When in doubt, classify as `regression` and state the doubt.
   - A failure of a project module that was renamed or removed in the candidate is not `environment`.
   - When the test also fails against the baseline and the test is correct, the product already failed before the change: classify as `regression`, and say in the justification that the failure predates the change.
5. **Record.** Call `memory.save_triage` with the execution, the classification and a justification of one to three sentences that cites the evidence: the failure message, the baseline result with its run, the requirement change, the line of the diff.
6. **Defects** for each execution classified `regression`:
   - If an open defect (`memory.get_defects` with status `open`) already describes the same failure of the same test case, call `memory.link_defect`.
   - Otherwise call `memory.register_defect`, grouping the executions with the same cause. Steps come from the steps of the test case.

   | Severity | When |
   |---|---|
   | `critical` | A core function is unusable, data is lost or corrupted, or security is affected, with no workaround. |
   | `high` | A main function gives wrong results, or a `high` priority requirement fails. |
   | `medium` | A secondary function is wrong, or a workaround exists. |
   | `low` | Cosmetic or minor deviation. |

7. **Close.** When the run is against the candidate, compare the open defects with the passed executions of this run (`memory.get_executions` with `result` `passed`). If every test case linked to a defect passed in this run, call `memory.close_defect` with a reason that names the run.
8. **Answer** with:
   - a table: test case, classification, short justification;
   - the defects registered, linked and closed;
   - the follow-up: `expected_change` and `test_defect` test cases must be updated (the decision is at most `release_with_conditions`); `flaky` tests need review; `environment` failures need the environment fixed and a new run.

## Rules

- Classify from evidence, never from the test name alone.
- Never change a result: triage explains a failure, it does not turn it into a pass.
- The probable cause of a regression is a hypothesis; say so.
