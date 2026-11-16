# Runtime

The runtime runs a session: it loads configuration, builds the context (`context-loading.md`), calls the model through a provider (`llm-providers.md`), dispatches tools (`mcp-tools.md`), enforces modes and permissions, and records every action (`data-model.md`). It is the only component that talks to both the model and the MCP servers.

## Session lifecycle

### Start

1. Parse the command line (`cli.md`).
2. Resolve the target project: `-C <path>` or the current directory. It must be the top level of a git repository; any other directory exits with code `2`, and a subdirectory of a repository names its top level. The directory `.retro/` is created when it is missing.
3. Resolve and validate the configuration (`configuration.md`). An invalid configuration exits with code `2`.
4. Take the session lock: an operating-system file lock on `.retro/retro.lock`. If another running session holds it, exit with code `2` and name the process that holds it. A lock file left by a session that crashed is not held by any process and is taken over.
5. Open project memory, migrating it if needed, and create the `session` record.
6. Recover from an interrupted previous session: runs left in status `running` become `interrupted`, with the reason in `error` and without new executions, and leftover worktrees of this project under `~/.retro/worktrees/<project-id>/` are removed, together with their metadata in `.git/worktrees/`.
7. Resolve the model profile and its credentials (`llm-providers.md`). A missing credential exits with code `2`.
8. Resolve the session versions: `--base` and `--candidate`, then `versions.*` from the configuration. Each ref is resolved to its commit here, and both are written to the `session` record; a ref that does not resolve exits with code `2`. A version may stay unset; a command that needs it then fails with `invalid_state`.
9. Resolve approvals for project MCP servers, steering and skills (ADR-0021). In an interactive session, the user is asked once for each item not yet approved. In non-interactive mode, unapproved items are not loaded and a warning is printed. The mode `auto` never approves them. Project commands are approved at the first run, not here (see Project commands).
10. Start the bundled MCP servers and the approved ones, with the cleaned environment of `configuration.md`, and read their tools.
11. When `tool_calling` is `auto` and the capability is unknown, run the probe call.
12. Check the context budget: the context window must be known and large enough for the fixed part of the context (`context-loading.md`). Otherwise exit with code `2`.
13. State the model in use and whether it is hosted or local.

### End

When the user exits, the single prompt is answered, or a fatal error occurs:

1. Stop the MCP servers.
2. Remove leftover worktrees.
3. Set `ended_at` on the session record.
4. Release the session lock.

## Turn

A turn starts with a user message and ends when the model answers without tool calls.

1. Build the system context and the tool definitions for the current mode and tool set, free context when the budget requires it, and append the state message (`context-loading.md`).
2. Call the model.
3. If the answer has tool calls, process them **one by one, in the order given**:
   1. Record the call in `tool_call`, with secret values replaced.
   2. Check the mode and the permission of the tool (see below). A refused call returns a `denied` error to the model.
   3. If the permission is `ask`, ask the user.
   4. Dispatch the call to its server. Bundled servers read the session context from the `session` record, which only the runtime writes (ADR-0026).
   5. Record the outcome and add the result to the conversation. When the results of this model message already fill their share of the context, the remaining calls are not executed and return `deferred`.
4. Go back to step 1 until the model answers without tool calls, then show the answer.

**Iteration limit.** A turn makes at most `agent.max_iterations` model calls. When the limit is reached, the turn stops with a message; in non-interactive mode this is a runtime error.

**Interruption.** `Esc` cancels the current model call or tool call. A cancelled run ends with status `interrupted`. Results of completed tool calls stay in the conversation.

## Modes and permissions

| Tool | Permission |
|---|---|
| `test_runner.write_test` | `write_tests` |
| `test_runner.run_tests` | `run_tests`, and `start_service` when `service.start` is configured |

Every other tool needs no permission. The effective value of each permission follows `configuration.md`.

| Mode | `allow` | `ask` | `deny` |
|---|---|---|---|
| `default` | Runs | Asks the user | Refused |
| `auto` | Runs | Runs | Refused |
| `plan` | Refused | Refused | Refused |

In plan mode, tools that need a permission are also left out of the tool definitions (`context-loading.md`).

When the user is asked, the prompt shows what will happen, not only the name of the tool. For `test_runner.write_test`: the full code, or the difference with the current code in a rewrite. For `test_runner.run_tests`: the version, the scope, the number of test cases and the commands that will run. It offers three answers: allow once, allow for the rest of the session, or deny. A grant for the session is kept in memory only; it is never written to configuration.

In non-interactive mode there is no one to ask: a permission `ask` in mode `default` is refused, and the session exits with code `4` (`cli.md`).

### Project commands

Before the first `test_runner.run_tests` of a session, the runtime checks that the project commands are approved in their current content (`configuration.md`, ADR-0024). This check does not depend on the mode or on `permissions.*`.

| Situation | Behavior |
|---|---|
| Approved | The call continues to the permission check. |
| Not approved, interactive session | The runtime shows every command and variable in full and asks. An approval is stored; a refusal returns `denied`. |
| Not approved, non-interactive mode | `denied`, and the session exits with code `4`. |
| `--trust-commands` | Approved for this session only; nothing is stored. |

## Session state

Kept by the runtime for the duration of the session, never by the model. The versions and the model are also written to the `session` record, where the bundled servers read them.

| State | Changed by |
|---|---|
| Versions | `--base`, `--candidate`, `runtime.set_versions`, `/analyze <base> <candidate>` |
| Mode | `--mode`, `/mode`, `Shift+Tab` |
| Model profile | `--model`, `/model`. Changing it keeps the conversation and runs the probe again when needed. |
| Session permission grants | Answers to permission prompts. |
| Conversation and loaded skill | Every turn; emptied by `/clear`, by every model command and by every step of `/cycle`. |

## Slash commands

Slash commands are of three kinds: direct commands, model commands and the cycle command (see Cycle command). **Direct** commands are executed by the runtime without calling the model, because they need no judgment. **Model** commands become a message to the model built from a fixed template. In both cases, tool calls go through the same permission checks and are recorded in `tool_call`.

### Direct commands

| Command | Action |
|---|---|
| `/run [target] [--on <version>]` | Calls `test_runner.run_tests`: `suite` uses scope `suite`, `all` uses scope `all`, IDs use scope `selected`. IDs are separated by spaces. `--on both` runs the baseline first, then the candidate only when the baseline run is `completed`. Shows a summary table of each run. |
| `/status` | Shows the session state, the active test cases by status, the size of the current suite, and the executions of the latest run by status and result. |
| `/history [n]` | Shows `memory.get_runs` as a table. |
| `/defects [--all]` | Shows `memory.get_defects` as a table. |
| `/defects close <id> <reason>` | Calls the user-only tool `memory.close_defect`. The model has no way to close a defect. |
| `/init` | Same as `retro init`. |
| `/model`, `/mode` | Show or change the session state. |
| `/skills`, `/mcp` | List skills and MCP servers with their tools. |
| `/clear` | Empties the conversation and the loaded skills. |
| `/help`, `/exit` | Help and end of session. |

### Model commands

| Command | Message sent to the model |
|---|---|
| `/analyze [base] [candidate]` | When refs are given, the runtime first calls `runtime.set_versions`. Then: "Load the skill `impact-analysis` and analyze the impact of the change between the session versions." |
| `/select` | "Load the skill `test-selection` and select and prioritize the regression suite for the latest impact analysis." |
| `/design [scope]` | "Load the skill `test-design` and design test cases for `<scope>`." Without scope: "for the impacted areas not covered by the current suite." |
| `/implement [ids]` | "Load the skill `test-design` and implement the test cases `<ids>`; rewrite those that are already `implemented`." Without IDs: "all designed test cases of the current suite." |
| `/triage [run_id]` | "Load the skill `failure-triage` and triage the failed executions of run `<run_id>`." Default: the latest run. |
| `/report <type> [--run <run_id>] [--format <format>]` | "Load the skill `test-reporting` and generate the `<type>` report" followed by the run and format when given. |

Every model command starts with an empty conversation and exposes only the tools of its skill (see Cycle command). The state message tells the model where the project stands, and project memory holds the details. A free message typed afterwards continues that conversation.

The templates are part of the bundled package. A message typed in natural language works the same way; the model follows the workflow in the steering.

## Regression cycle

The full cycle, as the steering describes it to the model:

| Step | Command | Main tools |
|---|---|---|
| 1. Initialize the project, once | `/init` | — |
| 2. Set the versions | `/analyze <base> <candidate>` or flags | `runtime.set_versions` |
| 3. Read the requirements | part of `/analyze` | `memory.sync_requirements` |
| 4. Analyze the impact | part of `/analyze` | `git.analyze_changes`, `git.get_diff`, `memory.save_impact`, `memory.add_risk` |
| 5. Discover the project suite, the first time | `/run all --on base`, and `--on candidate` when the change adds or modifies tests | `test_runner.run_tests` |
| 6. Select the regression suite | `/select` | `memory.get_test_cases`, `memory.save_suite` |
| 7. Design missing test cases | `/design` | `memory.design_test_case` |
| 8. Implement them | `/implement` | `test_runner.write_test` |
| 9. Run against both versions | `/run --on both` | `test_runner.run_tests` |
| 10. Triage failures | `/triage` | `memory.get_executions`, `test_runner.get_evidence`, `memory.save_triage`, `memory.register_defect` |
| 11. Report | `/report completion` | `reports.prepare_report`, `reports.render_report` |

For selection quality metrics (FR-34), step 9 can be complemented with `/run all --on both`.

## Cycle command

`/cycle [base] [candidate]` runs the regression cycle from step 2 to step 11 (FR-40, ADR-0027). The runtime, not the model, decides the order. Each model step is a turn of its own: the conversation is emptied before it, the state message names the step, and only the tools of the step are exposed. Project memory carries the state from one step to the next. After each step, code checks its outcome in project memory.

| Step | Kind | Tools exposed | Outcome checked by code |
|---|---|---|---|
| `analyze` | Model, skill `impact-analysis` | `runtime`, `git`, `memory` | An analysis of the session versions has an impact. |
| `discover` | Direct: full run against the baseline | — | The run is `completed`. Skipped when project tests are already known. |
| `select` | Model, skill `test-selection` | `runtime`, `git`, `memory`, `test_runner__run_tests` | The analysis has a suite. |
| `design` | Model, skill `test-design` | `runtime`, `git`, `memory` | None: gaps may remain, and the step says so. |
| `implement` | Model, skill `test-design` | `runtime`, `git`, `memory`, `test_runner__write_test`, `test_runner__get_evidence` | None: test cases left `designed` become a condition of the decision. |
| `run` | Direct: the suite against the baseline, then against the candidate | — | Both runs are `completed`. |
| `triage` | Model, skill `failure-triage` | `runtime`, `git`, `memory`, `test_runner__get_evidence` | No failed execution of the candidate run is left without triage. |
| `report` | Model, skill `test-reporting` | `runtime`, `memory`, `reports` | A `completion` report is `rendered`. |

- When the outcome of a step is missing, the step runs once more with a message that states what is missing. If it is still missing, the cycle stops with a runtime error that names the step.
- The cycle also stops when a tool call is refused, when a run ends with status `error` or `interrupted`, and when the model ends a step with a question for the user. In an interactive session the user can answer and continue with `/cycle`; steps whose outcome is already in project memory for the session versions are not repeated.
- In plan mode the cycle runs `analyze`, `select` and `design`, and stops before `implement`.
- `agent.max_iterations` applies to each step.
- The same tool sets apply to the model commands of the same skill (`/analyze`, `/select`, `/design`, `/implement`, `/triage`, `/report`).

## Non-interactive mode

`retro -p "<prompt>"` runs one turn and exits. A prompt that is a slash command runs that command: `retro -p "/cycle"` runs the whole cycle, one turn per step.

- Output `text` prints the final answer. Output `json` prints one object:

| Field | Content |
|---|---|
| `result` | Final answer of the model. |
| `session_id` | Session record. |
| `runs` | IDs of the runs created in the session. |
| `reports` | IDs and paths of the reports rendered in the session. |
| `decision` | Decision of the latest evaluation of the session, or null. |
| `denied` | Number of tool calls refused. |
| `exit_code` | Exit code of the session. |

- Exit code, by precedence: `1` if a runtime error occurred; otherwise `4` if a tool call was refused for lack of permission; otherwise `3` if the latest evaluation of the session decided `do_not_release`; otherwise `0`. Configuration errors before the session starts exit with `2`.

## Display

- Answers of the model are rendered as Markdown in the terminal.
- Runs, status, history and defects are shown as tables (FR-30).
- Verbose mode also shows each tool call with its arguments, outcome and duration, each model call with its token usage, and each retry.

## Robustness

- Every tool call that writes project memory runs in a single transaction: it is applied completely or not at all (NFR-07).
- The session lock prevents two sessions from writing the same project memory. The operating system releases it when the process ends, however it ends, so a crashed session never blocks the next one.
- A server that reads fewer tokens than it was sent is detected after the call, and the session stops instead of continuing with a model that lost its instructions (`context-loading.md`).
- Setup, test and service commands run in their own process group. A timeout, an interruption or the end of the session terminates the whole group, so no process of the target project outlives its run.
- Model errors are handled as in `llm-providers.md`; a failed turn never leaves partial records.

## Testing

- The turn, modes, permissions and exit codes are tested with `FakeProvider` and the bundled servers on a fixture project.
- Each row of the permission tables has a test, including plan mode refusing tools that the model calls despite their absence from the definitions.
- The cycle command is tested with `FakeProvider`: the order of the steps, the tools exposed in each one, the retry of a step whose outcome is missing, and every stop condition.
- Recovery is tested by leaving a run `running`, a worktree and a lock file in place, then starting a session.
- The approval of project commands is tested for each row of its table, and for a command changed after its approval.
- The environment of subprocesses is tested: a model credential set in the environment of `retro` must not be visible to a test command.
