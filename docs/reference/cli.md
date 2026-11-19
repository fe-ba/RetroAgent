# CLI reference

## Synopsis

```
retro [options] [prompt]
retro <command> [arguments]
```

Without a command, `retro` starts an interactive session on the target project. An optional `prompt` is sent as the first message of the session.

## Global options

| Option | Description |
|---|---|
| `-C <path>` | Use `<path>` as the target project instead of the current directory. |
| `-p`, `--print` | Non-interactive mode: run `prompt`, print the result and exit. |
| `-m`, `--model <name>` | Model profile to use for this session. Overrides the configured default. |
| `--mode <mode>` | Permission mode: `default`, `plan` or `auto`. Default: `default`. |
| `--trust-commands` | Approve the test commands of the project for this session without asking. For non-interactive runs on a repository of your own. Does not approve project MCP servers, steering or skills. |
| `--base <ref>` | Baseline version: tag, branch or commit. |
| `--candidate <ref>` | Candidate version: tag, branch or commit. |
| `--lang <code>` | Language of responses and reports (e.g. `en`, `es`). Overrides configuration. |
| `--output-format <format>` | Output of non-interactive mode: `text` or `json`. Default: `text`. |
| `-v`, `--verbose` | Show tool calls and their results in detail. |
| `--version` | Print the version and exit. |
| `-h`, `--help` | Print help and exit. |

## Commands

| Command | Description |
|---|---|
| `retro init` | Initialize the target project: detect its type and create `RETRO.md`, `.retro/config.yaml` and `.retro/.gitignore`. Does not overwrite existing files. |
| `retro example list` | List bundled example projects. |
| `retro example <name> <dir>` | Create example `<name>` in `<dir>` with its git history and version tags. `<dir>` must not exist or must be empty. |
| `retro config list` | Show the effective configuration and the level each value comes from. Not in this version (FR-39). |
| `retro config get <key>` | Show the effective value of `<key>`. Not in this version (FR-39). |
| `retro config set <key> <value>` | Set `<key>` at user level. With `--project`, set it in the target project. Not in this version (FR-39). |
| `retro defects close <id> --reason <text>` | Close a defect without starting a session, for scripts and CI. Takes the session lock while it writes. |

## Permission modes

| Mode | Behavior |
|---|---|
| `default` | Asks for permission before running tests, starting services or writing test code. |
| `plan` | Analyzes and designs. Cannot run tests or write test code. Test cases can only reach status `designed`. |
| `auto` | Performs actions allowed by the configuration without asking. Actions not allowed are refused. Intended for CI. |

In non-interactive mode (`-p`) there is no one to ask: with mode `default`, any action that requires permission fails with exit code `4`. Use `--mode auto` for unattended runs. The test commands of the project must also be approved: either stored from an interactive session, or with `--trust-commands`.

## Slash commands

Available inside an interactive session. Every slash command is a shortcut: the same task can be requested in natural language.

### Testing workflow

| Command | Description |
|---|---|
| `/cycle [base] [candidate]` | Run the whole regression cycle, from the impact analysis to the completion report, one step at a time. Stops when a step fails, is refused or needs a decision of the user. |
| `/analyze [base] [candidate]` | Compute the change set and the impact analysis. Sets the session versions when given. |
| `/select` | Select and prioritize the regression suite for the current change. |
| `/design [scope]` | Design test cases for the impacted areas, or for `scope` (requirement IDs, modules or free text). |
| `/implement [ids]` | Write executable test code for designed test cases (all designed ones by default). With the ID of a generated test that is already `implemented`, rewrites its code, for example after a `test_defect` triage. Code is stored in `.retro/tests/`. Requires `permissions.write_tests`. |
| `/run [target] [--on <version>]` | Execute tests. `target`: `suite` (default), `all` (the whole test command; discovers the project suite and is needed for selection quality metrics), or test case IDs. `--on`: `base`, `candidate` (default) or `both`. Test cases with status `designed` are not run; implement them first. |
| `/triage [run_id]` | Classify the failures of a run. Default: last run. |
| `/report <type> [--run <run_id>] [--format <format>]` | Generate a report. `type`: `test-plan`, `test-cases`, `status`, `defects`, `completion`. `format`: `md` or `pdf`; default from `reports.default_format`. |

### Project state

| Command | Description |
|---|---|
| `/status` | Session versions, test cases by status, test executions of the last run by status and result, current mode, and the model calls and tokens used in the session. |
| `/history [n]` | Last `n` runs. Default: 10. |
| `/defects [--all]` | Open defects. With `--all`, include closed ones. |
| `/defects close <id> <reason>` | Close a defect by decision of the user, for example when it was fixed outside the tested scope or no longer applies. Otherwise defects are closed only by a run against the candidate in which every linked test case passes. |

### Session

| Command | Description |
|---|---|
| `/init` | Same as `retro init`. |
| `/model [name]` | Show the current model, or switch to profile `name`. |
| `/mode [mode]` | Show the current permission mode, or switch to `default`, `plan` or `auto`. |
| `/skills` | List available skills and their source (bundled, user, project). |
| `/mcp` | List connected MCP servers and their tools. |
| `/clear` | Clear the conversation. Project memory is not affected. |
| `/help [command]` | Show help. |
| `/exit` | End the session. |

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Esc` | Interrupt the current agent action. `Ctrl+C` does the same while a turn is running. At a permission prompt, it denies. |
| `Shift+Tab` | Cycle permission modes at the prompt: `default`, `plan`, `auto`. |
| `Ctrl+C` twice | Exit. |
| `Ctrl+D` | Exit. |

## Exit codes

Apply to commands and to non-interactive mode.

| Code | Meaning |
|---|---|
| `0` | Completed. If a release decision was produced, it is `release` or `release_with_conditions`. |
| `1` | Runtime error: model, tool or unexpected failure. |
| `2` | Invalid usage or invalid configuration. |
| `3` | Completed with release decision `do_not_release`. |
| `4` | An action required a permission or an approval that could not be granted. |

Code `4` counts the calls refused by the mode, by a permission or by a missing approval. A call refused because the tool is user only or outside the tools of the step does not count: the model can correct it, and the session may still complete. When several codes apply, the order is `1`, `4`, `3`, `0`.

A direct command that starts a run exits with `1` when the run ends with status `error` or `interrupted`. Failed tests in a completed run are not an error: without a release decision the exit code is `0`.

## Examples

```
retro                                               # session on the current directory
retro -C ~/projects/shop-api                        # session on another project
retro --base v1.0 --candidate v1.1                  # session with versions preset
retro --mode plan "design tests for REQ-004"        # design only, nothing is executed
retro -p --mode auto --trust-commands --base v1.0 --candidate v1.1 \
  "/cycle"
retro example shop-api ./demo                       # create the example project
```
