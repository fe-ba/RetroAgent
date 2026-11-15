# ADR-0022: Release decision guards

- **Status:** Accepted
- **Date:** 2026-11-15

## Context

ADR-0006 states that code, not the model, produces the release decision, and ADR-0017 defines the metrics behind it. A review of the decision rule found four ways in which the decision could be wrong while every rule was followed:

- No exit criterion looked at the comparison with the baseline. A confirmed regression with a `medium` defect, in a run with a pass rate above the threshold, produced `release`.
- The result of a test execution was the result of its last attempt. A test that failed and then passed on a rerun was stored as `passed`, so an intermittent failure introduced by the change was invisible to the pass rate and could not be triaged.
- The model could close a defect with a tool call, and the classifications that excuse a failure were not checked. The model could therefore move the decision, which ADR-0006 meant to prevent.
- A failure that already existed in the baseline had to be classified as `regression`, which forced a defect for something the change did not break.

## Decision

1. **New failures block release.** A new exit criterion, EC-09, is blocking: `unexcused_new_failures <= max_new_failures` (default `0`). A new failure is a test case that passed against the baseline and did not pass against the candidate; it is excused only when triaged as `expected_change` or `test_defect`. Without a baseline run the criterion is not evaluable, and the decision is `do_not_release`.
2. **The first attempt gives the result.** A test case whose first attempt did not pass is rerun `tests.reruns` times, always all of them. Reruns only tell whether the execution is flaky; they never change its result. A flaky execution is therefore a failure, and it is triaged.
3. **The model cannot close a defect.** A defect is closed by code when a run against the candidate completes and every test case linked to the defect passed in it, or by the user with `/defects close`. The tool `memory.close_defect` is user only.
4. **Pre-existing failures have their own classification.** `pre_existing` means that the test is correct and already failed against the baseline. It needs no defect, it is not excused from the product pass rate, and it limits the decision to `release_with_conditions` at most.
5. **Code validates the classifications that depend on recorded facts.** `expected_change` needs a documented requirement change that applies to the change between the versions; `flaky` needs attempts or history with different verdicts; `pre_existing` needs a failed execution against the baseline. A triage without its evidence is rejected.

## Alternatives considered

- **Keep the last attempt as the result and add a condition when any execution is flaky:** smaller change, but the failure never reaches triage and a real intermittent regression still counts as a pass.
- **Make every open defect blocking, whatever its severity:** blocks release on cosmetic defects and still depends on a defect being registered.
- **Let the model close defects and require a justification:** a justification is text; it does not make the closing true.
- **Count pre-existing failures as excused:** hides from the pass rate a product that is failing.
- **Validate `test_defect` and `environment` by code:** no recorded fact can prove that a test is wrong or that the environment failed; they remain judgments of the model.

## Consequences

- A release decision always needs a run against the baseline. `/run --on both` is the normal way to run.
- `flaky` and `environment` failures of test cases that passed against the baseline block release until a new run passes. This is deliberately conservative.
- Reruns always run in full for a failed test case, which costs time when many tests fail.
- The data layer needs git access to check that a requirement change applies to a version pair.
- A stale defect whose test cases are no longer run can only be closed by the user.
- What remains a judgment of the model, and can still shape the decision: the selected suite, the impacted requirements, test case priorities, defect severities, and the classifications `regression`, `environment` and `test_defect`. Reports list them so that they can be reviewed; `metrics.md` states it as a limit of the metrics.
- ADR-0006 and ADR-0017 stay in force. This ADR adds guards to them; it replaces the rule that the last attempt gives the result.
