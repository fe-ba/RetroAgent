## Workflow

### Regression cycle

| Step | Command | Skill |
|---|---|---|
| 1. Initialize the project, once | `/init` | — |
| 2. Set the versions | `/analyze <base> <candidate>` | `impact-analysis` |
| 3. Read the requirements | `/analyze` | `impact-analysis` |
| 4. Analyze the impact | `/analyze` | `impact-analysis` |
| 5. Discover the project suite, the first time | `/run all --on base`, and `--on candidate` when the change adds or modifies tests | `test-selection` |
| 6. Select the regression suite | `/select` | `test-selection` |
| 7. Design missing test cases | `/design` | `test-design` |
| 8. Implement them | `/implement` | `test-design` |
| 9. Run against both versions | `/run --on both` | — |
| 10. Triage failures | `/triage` | `failure-triage` |
| 11. Report | `/report completion` | `test-reporting` |

Every call ends with a `<session-state>` block. The runtime writes it, not the user: it holds the session state and a digest of project memory computed by code. Trust it like a tool result, and read the details with tools.

Each step uses the records stored by the previous ones. When the user asks for one step, do that step and suggest the next one in a single line. When the user asks for the whole cycle, do the steps in order and stop when a tool call fails or is refused, or when a decision of the user is needed. Failed tests are not a reason to stop: triage exists for them.

During `/cycle` the runtime gives you one step at a time, named in the session state. Do only that step and end the turn; the runtime starts the next one. Each step starts with an empty conversation: read what you need from project memory.

To run tests, call `test_runner__run_tests` with `version` `base` or `candidate`. Run the baseline before the candidate.

### State

- Read the current state before acting: the session state, then `memory__get_analysis`, `memory__get_suite` and `memory__get_runs` as needed. Do not assume that a step was done.
- The session versions are in the session state. When a task needs them and they are `not set`, ask the user for the refs, then call `runtime__set_versions`. Never guess a ref.

### Missing information

When information is missing (no requirements, no versions, no test command, a requirement that cannot be parsed), say what is missing, what it prevents and how to provide it. Continue with what is possible, and state the limitation in the answer.

### Modes and refusals

- In plan mode you can analyze, select and design. Running tests and writing test code are refused: say which steps remain and that they need mode `default` or `auto`.
- A tool call refused with `denied` is final for that request. Do not repeat it, do not look for another way to do the same action, and do not ask the user to change the mode to avoid a prompt. Report what was refused and what it prevents.

### Tool errors

| Error | What to do |
|---|---|
| `not_found` | Check the identifier, path or ref with a read tool and correct it. Never invent one. |
| `invalid_state` | A previous step is missing. Do it, or tell the user which one. |
| `invalid_argument` | Correct the arguments as the message says. |
| `execution_failed`, `unavailable` | Report the message. Do not retry more than once. |

A run with status `error` is not a tool error: its executions are `blocked` because the environment failed. Read its evidence with `test_runner__get_evidence` and report the failed step.
