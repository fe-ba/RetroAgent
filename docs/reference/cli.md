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
| `retro config list` | Show the effective configuration and the level each value comes from. |
| `retro config get <key>` | Show the effective value of `<key>`. |
| `retro config set <key> <value>` | Set `<key>` at user level. With `--project`, set it in the target project. |

## Permission modes

| Mode | Behavior |
|---|---|
| `default` | Asks for permission before running tests, starting services or writing test code. |
| `plan` | Analyzes and designs. Cannot run tests or write test code. Test cases can only reach status `designed`. |
| `auto` | Performs actions allowed by the configuration without asking. Actions not allowed are refused. Intended for CI. |

In non-interactive mode (`-p`) there is no one to ask: with mode `default`, any action that requires permission fails with exit code `4`. Use `--mode auto` for unattended runs.

## Slash commands

Available inside an interactive session. Every slash command is a shortcut: the same task can be requested in natural language.

### Testing workflow

| Command | Description |
|---|---|
| `/analyze [base] [candidate]` | Compute the change set and the impact analysis. Sets the session versions when given. |
| `/select` | Select and prioritize the regression suite for the current change. |
| `/design [scope]` | Design test cases for the impacted areas, or for `scope` (requirement IDs, modules or free text). |
| `/implement [ids]` | Write executable test code for designed test cases (all designed ones by default). Code is stored in `.retro/tests/`. Requires `permissions.write_tests`. |
| `/run [target] [--on <version>]` | Execute tests. `target`: `suite` (default), `all` (every implemented test case; needed for selection quality metrics), or test case IDs. `--on`: `base`, `candidate` (default) or `both`. Test cases with status `designed` are not run; implement them first. |
| `/triage [run_id]` | Classify the failures of a run. Default: last run. |
| `/report <type> [--run <run_id>] [--format <format>]` | Generate a report. `type`: `test-plan`, `test-cases`, `status`, `defects`, `completion`. `format`: `md` or `pdf`; default from `reports.default_format`. |

### Project state

| Command | Description |
|---|---|
| `/status` | Session versions, test cases by status, test executions of the last run by status and result, and current mode. |
| `/history [n]` | Last `n` runs. Default: 10. |
| `/defects [--all]` | Open defects. With `--all`, include closed ones. |

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
| `Esc` | Interrupt the current agent action. |
| `Shift+Tab` | Cycle permission modes. |
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
| `4` | An action required permission that could not be granted. |

## Examples

```
retro                                               # session on the current directory
retro -C ~/projects/shop-api                        # session on another project
retro --base v1.0 --candidate v1.1                  # session with versions preset
retro --mode plan "design tests for REQ-004"        # design only, nothing is executed
retro -p --mode auto --base v1.0 --candidate v1.1 \
  "run the regression cycle and generate the completion report"
retro example shop-api ./demo                       # create the example project
retro config set model local                        # default model at user level
```
