## Test states

A test case can be designed, implemented, executed and passed. These are different facts, and each one needs its own evidence.

| Fact | Only true when |
|---|---|
| Designed | A test case exists in project memory with status `designed` or `implemented`. |
| Implemented | The test case has status `implemented`: its code exists in `.retro/tests/` or in the project suite. |
| Executed | A run created a test execution with status `executed` for it. |
| Passed, failed or error | That test execution has that `result`. |

### Rules

- Designing a test case is not implementing it. Writing test code is not running it. An expected result is not an actual result.
- Never say that a test ran, passed or failed unless a tool result shows that test execution in a run. If you have not seen it, the outcome is unknown: say so and offer to run the test.
- State every result with its run and version: "TC-004 passed in RUN-0002 against `v1.1`", never "TC-004 passes".
- After designing, say "designed, not implemented, not executed". After implementing, say "implemented, not executed".
- `blocked` means the test could not run. It says nothing about the product and is never a pass or a failure.
- `skipped` means the test did not run on purpose. It is not a pass.
- A pass proves only what the test checks, and a single pass can hide a flaky test.
- Counts of statuses and results are read from tools, never counted from memory of the conversation.
