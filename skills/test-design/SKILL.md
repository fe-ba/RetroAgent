---
name: test-design
description: Design test cases (objective, preconditions, input data, steps, expected result, priority and traceability) for impacted areas, and implement designed test cases as executable test code. Use for /design, /implement, or when asked to write tests.
---

# Test design

Two tasks: **design** creates test case specifications with status `designed`; **implement** writes their test code and sets them to `implemented`. Do only the task that was asked.

## Design

1. **Suite.** Call `memory.get_suite`. Test cases are added to the current suite when designed; without one, the selection comes first: load the skill `test-selection`.
2. **Scope.** The scope given by the user (requirement IDs, modules or free text), or the impacted requirements and modules that the current suite does not cover. Read them with `memory.get_analysis` and `memory.get_requirements`, and read the code with `git.get_diff` and `git.read_file` at `candidate`.
3. **Avoid duplicates.** Call `memory.get_test_cases` with `requirement_id` for each requirement in scope. Do not design what an existing test case already verifies.
4. **Derive the test cases.** For each requirement or area in scope:
   - the behavior that changed, from the diff and the documented change;
   - the unchanged behavior next to it, which is what a regression would break;
   - boundary values and equivalence classes of each input;
   - combinations of conditions, as a decision table, when rules interact;
   - invalid inputs and error responses that the requirement defines.
5. **Fill the fields.**

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
6. **Record.** Call `memory.design_test_case` for each test case. To correct a design that is still `designed`, use `memory.update_test_case`.
7. **Answer** with a table (test case, title, priority, requirements), stating that they are designed, not implemented, not executed. Next step: `/implement`.

## Implement

1. **Targets.** The IDs given by the user, or every test case of the current suite with status `designed` (`memory.get_suite`, `memory.get_test_cases` with status `designed`).
2. **Conventions.** Read the test conventions in `RETRO.md`, and one or two existing tests of the project (`git.list_files` and `git.read_file` at `candidate`): framework, imports, fixtures, how the service is reached.
3. **Write the code**, one file per test case, with one test function:
   - Name the function `test_req_<NNN>_<description>`, with the number of the first traced requirement and a short description in lowercase with underscores. Without requirements, `test_<description>`. Name the file as the framework requires to discover it.
   - Mention the test case ID in a comment or docstring.
   - Implement the steps and assert the expected result exactly. An assertion that would hold even if the behavior broke is not acceptable.
   - Import the project the way its own tests do. The same file must run unchanged against both versions.
   - When the tests need the running service, read its base URL from `RETRO_BASE_URL`. Never hard-code a host or port.
   - Follow the limits for generated test code in the steering.
4. **Record.** Call `test_runner.write_test` with the test case ID, the file path relative to `.retro/tests/`, the function name and the full content of the file. If the call is refused, stop: the remaining test cases stay `designed`.
5. **Answer** with a table (test case, implementation), stating that they are implemented, not executed. Next step: `/run --on both`.

A test for a new or changed requirement is expected to fail against the baseline. That is not a regression; the comparison shows it as fixed in the candidate.
