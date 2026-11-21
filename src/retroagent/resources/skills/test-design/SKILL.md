---
name: test-design
description: Design test cases (objective, preconditions, input data, steps, expected result, priority and traceability) for impacted areas, and implement or rewrite them as executable test code. Use for /design, /implement, or when asked to write or fix tests.
---

# Test design

Three tasks: **design** creates test case specifications with status `designed`; **implement** writes their test code and sets them to `implemented`; **rewrite** corrects the code of a generated test that is already `implemented`. Do only the task that was asked.

## Design

1. **Suite.** Call `memory__get_suite`. Test cases are added to the current suite when designed; without one, the selection comes first: load the skill `test-selection`.
2. **Scope.** The scope given by the user (requirement IDs, modules or free text). Without one, the `uncovered_requirements` of the current suite, which every one needs at least one test case, and then the impacted modules that no test case of the suite exercises. Read them with `memory__get_analysis` and `memory__get_requirements`.
3. **Read the code and the test data.** Before designing, read with `git__read_file` at `base` the code that implements each requirement in scope, the data the tests start from (fixtures, seeded records, catalogs) and one existing test of the same area, found with `git__list_files`. Input data must use values that exist in the project: identifiers, stock, prices. Any exact value the requirement does not give, such as a status code or an error message, is taken from the baseline code and stated as such. Never invent one.
4. **Avoid duplicates.** Call `memory__get_test_cases` with `requirement_id` for each requirement in scope. Do not design what an existing test case already verifies. A test case left out of the suite because the change deleted its test is not a gap: the change removed it on purpose, often because the rule it checked changed. `memory__design_test_case` refuses a title that an existing test case already has.
5. **Derive the test cases.** For each requirement or area in scope:
   - the behavior that changed, from the diff and the documented change;
   - the unchanged behavior next to it, which is what a regression would break;
   - boundary values and equivalence classes of each input;
   - combinations of conditions, as a decision table, when rules interact;
   - invalid inputs and error responses that the requirement defines.
6. **Fill the fields.**

   | Field | Content |
   |---|---|
   | `title` | What is verified, in a few words. |
   | `objective` | One sentence: "Verify that ...". |
   | `priority` | `high` when it verifies a `high` priority requirement or a `high` risk module; `low` for minor behavior; otherwise `medium`. |
   | `preconditions` | State the system and data must be in before the steps. |
   | `input_data` | Each input with a concrete value. |
   | `steps` | Actions in order, each one observable. |
   | `expected_result` | Exact observable outcome: values, status codes, messages. From the requirement; without one, from the baseline behavior, stated as an assumption. |
   | `requirement_ids` | Every requirement verified. Empty only when the project has none. |
   | `selection_reason` | Which gap of the suite it covers. |

   When a requirement is ambiguous, state the interpretation used in the objective and tell the user.
7. **Record.** Call `memory__design_test_case` for each test case. To correct a design that is still `designed`, use `memory__update_test_case`.
8. **Answer** with a table (test case, title, priority, requirements), stating that they are designed, not implemented, not executed. Next step: `/implement`.

## Implement

1. **Targets.** The IDs given by the user, or every test case of the current suite with status `designed` (`memory__get_suite`, `memory__get_test_cases` with status `designed`).
2. **Conventions.** Read the test conventions in `RETRO.md`, and one or two existing tests of the project (`git__list_files` and `git__read_file` at `candidate`): framework, imports, fixtures, how the service is reached. Then read, at `base` and at `candidate`, every module the test will import: each function, class and exception it uses must exist with that name in both versions. Never guess a name; a test that imports a name that does not exist fails before it runs.
3. **Write the code**, one file per test case, with one test function:
   - Name the function `test_req_<NNN>_<description>`, with the number of the first traced requirement and a short description in lowercase with underscores. Without requirements, `test_<description>`. Name the file as the framework requires to discover it, without directories: generated tests are copied into the test folder of the project.
   - Mention the test case ID in a comment or docstring.
   - One test function per test case, never parametrized. Its name and its file must not be used by another generated test.
   - Implement the steps and assert the expected result exactly. An assertion that would hold even if the behavior broke is not acceptable.
   - Import the project the way its own tests do. The same file must run unchanged against both versions.
   - When the tests need the running service, read its base URL from `RETRO_BASE_URL`. Never hard-code a host or port.
   - Follow the limits for generated test code in the steering.
4. **Record.** Call `test_runner__write_test` with the test case ID, the file path relative to `.retro/tests/`, the function name and the full content of the file. If the call is refused, stop: the remaining test cases stay `designed`.
5. **Answer** with a table (test case, implementation), stating that they are implemented, not executed. Next step: `/run --on both`.

## Rewrite

For a generated test that is wrong (triage `test_defect`) or that verifies a requirement that changed (triage `expected_change`), and when the user asks to fix a test. A test case that is already `implemented` is rewritten, not designed again.

1. **Read.** Call `memory__get_test_cases` with the ID and `include_code` `true`: the design, the current code and the origin. Read the triage and the evidence of the failure (`memory__get_executions`, `test_runner__get_evidence`).
2. **Origin.** A `project_suite` test belongs to the project: do not rewrite it. Say what must change in it and why.
3. **Write.** Call `test_runner__write_test` with the same test case ID, the same file and the same test name, and the full corrected code. When the steps, the input data, the expected result or the traced requirements change, pass them in `fields` in the same call, so that the design and the code never disagree.
4. **Retire.** When the test cannot be repaired, or its requirement was removed, call `memory__retire_test_case` with the reason and tell the user. A replacement is designed as a new test case.
5. **Answer** with a table (test case, revision or retired, what changed), stating that rewritten test cases are implemented, not executed. Next step: `/run --on both`.

A test for a new or changed requirement is expected to fail against the baseline. That is not a regression; the comparison shows it as fixed in the candidate.
