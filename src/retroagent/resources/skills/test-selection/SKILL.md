---
name: test-selection
description: Select and prioritize the regression suite for the latest impact analysis, with a justification for every test case, and list the impacted areas left without tests. Use for /select, or when asked which tests to run for a change.
---

# Test selection

Choose the test cases that can reveal whether the change broke something, order them by risk, and justify each one. The selection is measured afterwards: inclusiveness (revealing test cases selected) and precision (unneeded test cases left out).

## Procedure

1. **Analysis.** Call `memory__get_analysis`. If there is none for the session versions, the impact analysis comes first: load the skill `impact-analysis`.
2. **Candidates.** Call `memory__get_test_cases`.
   - If no test case has origin `project_suite` and the project has tests of its own (see `RETRO.md` or `git__list_files`), the project suite has not been discovered yet. Call `test_runner__run_tests` with `version` `base` and `scope` `all`. When the change set adds or modifies test files (`memory__get_analysis`), also run `version` `candidate` with `scope` `all`, so that the tests added by the change are known. Then read the test cases again. If the call is refused, continue with the known test cases and state that the project suite is missing from the selection.
3. **Context.** Call `memory__get_risks`, and `memory__get_requirements` for the impacted requirements. For candidates with doubtful relevance, check their implementation file and their history (`memory__get_test_case_history`).
4. **Select.** Include a test case when at least one applies:
   - it is traced to an impacted requirement;
   - its implementation exercises an impacted module;
   - it verifies a high-priority requirement close to a `high` risk module;
   - it failed or was flaky in a recent run, in an impacted area.

   Leave out test cases unrelated to the change set. Retired test cases cannot be selected. When the relation is uncertain, include the test case: missing a revealing test case costs more than running an unneeded one. Select every test case only when the change touches code that every feature uses, and say so.

   Test cases traced to a requirement with a documented change are included: they may fail as `expected_change` and must be reviewed. Test cases still `designed` from earlier cycles are included only if they are relevant; they count as designed only until implemented.
5. **Order.** Assign positions from 1. Positions order the presentation of the suite; the test framework decides the execution order:
   1. test cases of `high` risk modules and `high` priority requirements;
   2. test cases of requirements with a documented change;
   3. the rest by risk level, then by priority;
   4. within each group, test cases with recent failures first.
6. **Justify.** Each `selection_reason` names the link that justifies it: the requirement, module or risk, and what changed. Example: "Traced to REQ-004; coupon calculation changed in `cart/discounts.py` (high risk)."
7. **Record.** Call `memory__save_suite` with the analysis ID and the items. The suite may be empty when no existing test case relates to the change; designed test cases are added to it later.
8. **Gaps.** List the impacted requirements and modules that no selected test case covers.
9. **Answer** with the suite ID, a table (position, test case, title, priority, status, reason), the number of test cases left out, the gaps, and the next step: `/design` when there are gaps, otherwise `/run --on both`.
