# Runtime

The runtime runs a session: it loads configuration, builds the context (`context-loading.md`), calls the model through a provider (`llm-providers.md`), dispatches tools (`mcp-tools.md`), enforces modes and permissions, and records every action (`data-model.md`). It is the only component that talks to both the model and the MCP servers.

## Session lifecycle

### Start

1. Parse the command line (`cli.md`).
2. Resolve and validate the configuration (`configuration.md`). An invalid configuration exits with code `2`.
3. Resolve the target project: `-C <path>` or the current directory. A directory that is not a git repository exits with code `2`.
4. Take the session lock `.retro/retro.lock`. If another session holds it, exit with code `2` and name the process that holds it.
5. Open project memory, migrating it if needed, and create the `session` record.
6. Recover from an interrupted previous session: runs left in status `running` become `interrupted`, and leftover worktrees under `.retro/worktrees/` are removed.
7. Resolve the model profile and its credentials (`llm-providers.md`). A missing credential exits with code `2`.
8. Resolve the session versions: `--base` and `--candidate`, then `versions.*` from the configuration. They may stay unset.
9. Resolve approvals for project MCP servers, steering and skills (ADR-0021). In an interactive session, the user is asked once for each item not yet approved. In non-interactive mode, unapproved items are not loaded and a warning is printed. The mode `auto` never approves them.
10. Start the bundled MCP servers and the approved ones, and read their tools.
11. When `tool_calling` is `auto` and the capability is unknown, run the probe call.
12. State the model in use and whether it is hosted or local.

### End

When the user exits, the single prompt is answered, or a fatal error occurs:

1. Stop the MCP servers.
2. Remove leftover worktrees.
3. Set `ended_at` on the session record.
4. Release the session lock.

## Turn

A turn starts with a user message and ends when the model answers without tool calls.

1. Build the system context and the tool definitions for the current mode.
2. Call the model.
3. If the answer has tool calls, process them **one by one, in the order given**:
   1. Record the call in `tool_call`, with secret values replaced.
   2. Check the mode and the permission of the tool (see below). A refused call returns a `denied` error to the model.
   3. If the permission is `ask`, ask the user.
   4. Dispatch the call to its server, passing the session context (ADR-0020).
   5. Record the outcome and add the result to the conversation.
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

When the user is asked, the prompt shows the tool and its main arguments, and offers three answers: allow once, allow for the rest of the session, or deny. A grant for the session is kept in memory only; it is never written to configuration.

In non-interactive mode there is no one to ask: a permission `ask` in mode `default` is refused, and the session exits with code `4` (`cli.md`).

## Session state

Kept by the runtime for the duration of the session, never by the model.

| State | Changed by |
|---|---|
| Versions | `--base`, `--candidate`, `runtime.set_versions`, `/analyze <base> <candidate>` |
| Mode | `--mode`, `/mode`, `Shift+Tab` |
| Model profile | `--model`, `/model`. Changing it keeps the conversation and runs the probe again when needed. |
| Session permission grants | Answers to permission prompts. |
| Conversation and loaded skills | Every turn; emptied by `/clear`. |

## Slash commands

Slash commands are of two kinds. **Direct** commands are executed by the runtime without calling the model, because they need no judgment. **Model** commands become a message to the model built from a fixed template. In both cases, tool calls go through the same permission checks and are recorded in `tool_call`.

### Direct commands

| Command | Action |
|---|---|
| `/run [target] [--on <version>]` | Calls `test_runner.run_tests`: `suite` uses scope `suite`, `all` uses scope `all`, IDs use scope `selected`. `--on both` runs the baseline first, then the candidate. Shows a summary table of each run. |
| `/status` | Shows the session state and the counts from `memory.get_suite` and `memory.get_runs`. |
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
| `/implement [ids]` | "Load the skill `test-design` and implement the designed test cases `<ids>`." Without IDs: "all designed test cases of the current suite." |
| `/triage [run_id]` | "Load the skill `failure-triage` and triage the failed executions of run `<run_id>`." Default: the latest run. |
| `/report <type> [--run <run_id>] [--format <format>]` | "Load the skill `test-reporting` and generate the `<type>` report" followed by the run and format when given. |

The templates are part of the bundled package. A message typed in natural language works the same way; the model follows the workflow in the steering.

## Regression cycle

The full cycle, as the steering describes it to the model:

| Step | Command | Main tools |
|---|---|---|
| 1. Initialize the project, once | `/init` | — |
| 2. Set the versions | `/analyze <base> <candidate>` or flags | `runtime.set_versions` |
| 3. Read the requirements | part of `/analyze` | `memory.sync_requirements` |
| 4. Discover the project suite, the first time | `/run all --on base` | `test_runner.run_tests` |
| 5. Analyze the impact | `/analyze` | `git.analyze_changes`, `git.get_diff`, `memory.save_impact`, `memory.add_risk` |
| 6. Select the regression suite | `/select` | `memory.get_test_cases`, `memory.save_suite` |
| 7. Design missing test cases | `/design` | `memory.design_test_case` |
| 8. Implement them | `/implement` | `test_runner.write_test` |
| 9. Run against both versions | `/run --on both` | `test_runner.run_tests` |
| 10. Triage failures | `/triage` | `memory.get_executions`, `test_runner.get_evidence`, `memory.save_triage`, `memory.register_defect` |
| 11. Report | `/report completion` | `reports.prepare_report`, `reports.render_report` |

For selection quality metrics (FR-34), step 9 can be complemented with `/run all --on both`.

## Non-interactive mode

`retro -p "<prompt>"` runs one turn and exits.

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
- The session lock prevents two sessions from writing the same project memory.
- Model errors are handled as in `llm-providers.md`; a failed turn never leaves partial records.

## Testing

- The turn, modes, permissions and exit codes are tested with `FakeProvider` and the bundled servers on a fixture project.
- Each row of the permission tables has a test, including plan mode refusing tools that the model calls despite their absence from the definitions.
- Recovery is tested by leaving a run `running` and a worktree in place, then starting a session.
