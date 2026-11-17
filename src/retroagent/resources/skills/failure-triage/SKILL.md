---
name: failure-triage
description: Classify each failed or error execution of a run as flaky, environment, expected_change, test_defect, pre_existing or regression with a justification, and register or link defects. Use for /triage, or when asked why tests failed.
---

# Failure triage

Explain every failed or error execution of a run, so that the release decision can be trusted. Exit criterion EC-08 requires every failure of the evaluated run to be triaged, and every `regression` to be linked to a defect. EC-09 blocks release when a test case that passed against the baseline fails against the candidate, unless the failure is `expected_change` or `test_defect`.

## Procedure

1. **Run.** The run given by the user, or the latest one (`memory__get_runs` with `limit` 1). If its status is `error`, its executions are `blocked`: there is nothing to classify. Read `test_runner__get_evidence`, report the step that failed, and stop.
2. **Failures.** Call `memory__get_executions` with the run ID and `untriaged` `true`. If there are none, say so.
3. **Evidence**, for each execution:
   - `test_runner__get_evidence` with the run and the test case: failure message of each attempt and the log;
   - `memory__get_test_case_history`: result against the baseline, earlier results, flakiness;
   - `memory__get_test_cases` and `memory__get_requirements`: traced requirements and their documented changes;
   - `git__get_diff` or `git__read_file` for the code the failure points to.
4. **Classify.** Apply the first rule that matches:

   | Order | Classification | When |
   |---|---|---|
   | 1 | `flaky` | At least one rerun of the execution passed, or an earlier execution of the test case against the same commit had a different verdict. |
   | 2 | `environment` | The failure comes from infrastructure: service not reachable, timeout of an external resource, missing third-party dependency, port or file permission problem. |
   | 3 | `expected_change` | A traced requirement has a `Changed` or `Removed` entry that applies to the change between the session versions, and the failure matches that documented change. |
   | 4 | `test_defect` | The test itself is wrong: its assertion contradicts the requirement, its data is invalid, or it has an error of its own. |
   | 5 | `pre_existing` | The test is correct and it also failed against the baseline: the failure predates the change. |
   | 6 | `regression` | The product does not behave as required, and no rule above applies. |

   - `expected_change` and `test_defect` remove the failure from the product pass rate. Use them only with concrete evidence: a documented requirement change, or a specific error in the test. When in doubt, classify as `regression` and state the doubt.
   - A failure of a project module that was renamed or removed in the candidate is not `environment`.
   - Code checks the evidence of `flaky`, `expected_change` and `pre_existing`. When `memory__save_triage` answers `invalid_state` because the evidence is missing, do not insist and do not reword the call: read the message, and classify with the next rule that matches.
   - A flaky execution has the result of its first attempt, so it is always a failure to classify. `flaky` and `environment` do not excuse it: when the test case passed against the baseline, it still blocks release until a new run passes.
   - `pre_existing` needs a baseline run that executed the test case. Without one, say that the baseline must be run, and classify as `regression`.
5. **Record.** Call `memory__save_triage` with the execution, the classification and a justification of one to three sentences that cites the evidence: the failure message, the baseline result with its run, the requirement change, the line of the diff.
6. **Defects** for each execution classified `regression`:
   - If an open defect (`memory__get_defects` with status `open`) already describes the same failure of the same test case, call `memory__link_defect`.
   - Otherwise call `memory__register_defect`, grouping the executions with the same cause. Steps come from the steps of the test case.
   - A `pre_existing` failure needs no defect. Register one only when the user asks for it.

   | Severity | When |
   |---|---|
   | `critical` | A core function is unusable, data is lost or corrupted, or security is affected, with no workaround. |
   | `high` | A main function gives wrong results, or a `high` priority requirement fails. |
   | `medium` | A secondary function is wrong, or a workaround exists. |
   | `low` | Cosmetic or minor deviation. |

7. **Answer** with:
   - a table: test case, classification, short justification;
   - the defects registered and linked, and the defects that the run closed (`memory__get_defects` with status `closed`, those closed by this run);
   - the follow-up: `expected_change` and `test_defect` test cases must be updated, generated tests with `/implement <id>` and project tests by the user (the decision is at most `release_with_conditions`); `pre_existing` failures were already in the baseline (the decision is at most `release_with_conditions`); `flaky` tests need review and a new run; `environment` failures need the environment fixed and a new run.

## Rules

- Classify from evidence, never from the test name alone.
- Never change a result: triage explains a failure, it does not turn it into a pass.
- Triage an execution again (`replace` `true`) only when the user asks, or when new evidence exists, such as a baseline run made after the first triage. State the previous classification in the justification.
- Triage one execution at a time: read its evidence (step 3), record its triage, and for a `regression` register or link its defect at once, before reading the next one.
- Name in the answer only the triages and defects that a tool call of this turn recorded, with the IDs the tools returned. The runtime shows the user what was recorded.
- You cannot close a defect. A run closes it when every linked test case passes; the user can close it with `/defects close`.
- The probable cause of a regression is a hypothesis; say so.
