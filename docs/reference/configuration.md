# Configuration reference

## Levels and precedence

| Level | Location | Purpose |
|---|---|---|
| Defaults | Bundled with RetroAgent | Values used when nothing else is set. |
| User | `~/.retro/config.yaml` | Model profiles and personal preferences. Applies to every project. |
| Project | `<project>/.retro/config.yaml` | How to test this project. Usually versioned with the project. |
| Environment | `RETRO_*` variables | Overrides for CI and scripts. |
| CLI | Flags | Overrides for one session. |

Each level overrides the previous one. Maps are merged key by key; lists are replaced.

`RETRO_HOME` changes the location of the user level (default `~/.retro`).

## Restricted keys

The project configuration belongs to the target project, which may come from an untrusted source (ADR-0014). To prevent a project from taking control of the agent:

- `models` can only be defined at user level. A project can only select a profile by name with `model`.
- `permissions` at project level can only make actions stricter (`allow` to `ask` or `deny`, `ask` to `deny`), never looser.
- The commands a project defines (`tests.setup`, `tests.command`, `tests.select`, `service.start`) and `tests.env` run only after the user approved their exact content. See Project commands.
- MCP servers declared by a project require user approval the first time they are used. Approvals are stored in `~/.retro/approvals.json`.
- Every approval covers the exact content approved: a command, a server declaration, a steering file or a skill that changes is asked again.
- Steering and skills of a project are loaded only after user approval, and never replace bundled or user ones (ADR-0021).
- The permission mode is not a configuration key. It is set only with `--mode` or `/mode`.

## Project commands

`tests.setup`, `tests.command`, `tests.select`, `service.start` and `tests.env` are written in the project and run on the user's machine with the user's privileges. They run only after the user approved them (ADR-0024).

- The approval covers the five values together. It is stored in `~/.retro/approvals.json` as a hash of their content, for the path of the project. When any value changes, the approval is asked again.
- In an interactive session, the first run shows every command and every variable in full, and asks. This is separate from the permission `run_tests`, which decides whether the agent may start a run.
- In non-interactive mode there is no one to ask: without a stored approval, running tests is refused and the session exits with code `4`. `--trust-commands` approves them for that session only; it is meant for CI on a repository of the user's own.
- The mode `auto` never approves commands.
- Commands are read from the configuration in the working copy, never from the versions under test.

RetroAgent is not a sandbox: approved commands and the tests they run are code of the project. To test a repository that is not trusted, run RetroAgent inside a container or a virtual machine.

## Validation

`tests.junit` and `tests.generated_dir` must be relative paths that stay inside the worktree, and the host of `service.url` must be `127.0.0.1` or `localhost`.

Unknown keys, invalid values and restricted keys at the wrong level are errors. RetroAgent reports the key and the level where it was found, and exits with code `2`.

## Keys

### General

| Key | Type | Default | Levels | Description |
|---|---|---|---|---|
| `model` | string | none | user, project | Model profile to use. If none is set, an interactive session asks for one; non-interactive mode exits with code `2`. |
| `language` | string | `en` | user, project | Language of responses and reports. |

### Model profiles

Defined only at user level, under `models.<profile>`.

| Key | Type | Default | Description |
|---|---|---|---|
| `provider` | enum | required | `anthropic`, `openai`, `xai`, `google`, `ollama`, `openai_compatible`. |
| `name` | string | required | Model identifier as the provider expects it. |
| `base_url` | string | provider default | Endpoint. Required for `ollama` and `openai_compatible`. |
| `api_key_env` | string | none | Name of the environment variable that holds the API key. The key itself is never stored in configuration. |
| `tool_calling` | enum | `auto` | `auto` detects support, `native` forces tool calling, `json` forces the JSON fallback mode. |
| `temperature` | number | `0` | Sampling temperature. Low values favor reproducible behavior. |
| `timeout` | integer | `120` | Seconds before a model call is abandoned and retried (`llm-providers.md`). |
| `context_window` | integer | reported by the provider | Context size of the model, in tokens. Required for `ollama` and `openai_compatible`, where it cannot be known reliably. For `ollama` it is also sent with every request as the context size to use, because a local server may otherwise apply a smaller default and drop the beginning of the context without an error (`context-loading.md`). |

### Agent

| Key | Type | Default | Levels | Description |
|---|---|---|---|---|
| `agent.max_iterations` | integer | `50` | user, project | Maximum model calls per turn before the loop stops. Each step of `/cycle` is a turn. |

### Project

| Key | Type | Default | Levels | Description |
|---|---|---|---|---|
| `project.name` | string | directory name | project | Display name in reports. |
| `project.requirements` | list of paths or globs | none | project | Requirement documents. If not set, the project has no requirements; `retro init` proposes a value. See `project-contract.md`. |
| `project.source` | list of paths | `["."]` | project | Source directories considered by impact analysis. |
| `versions.base` | string | none | project | Default baseline ref. |
| `versions.candidate` | string | none | project | Default candidate ref. |

### Tests

| Key | Type | Default | Levels | Description |
|---|---|---|---|---|
| `tests.command` | string | none | project | Command that runs the test suite. Required for execution. |
| `tests.junit` | string | `{junit}` | project | Where the JUnit XML is read from: `{junit}`, a path or a glob, relative to the worktree. |
| `tests.select` | string | none | project | Command that runs only selected tests, using `{names}`. If absent, the full suite runs and only selected test cases are counted. Also used for reruns. |
| `tests.select_separator` | string | `" or "` | project | Separator used to join test names in `{names}`. |
| `tests.setup` | string | none | project | Command run once in each new worktree before tests. Must install dependencies locally to the worktree, never globally. Worktrees are new for every run, so `{cache_dir}` is the place for downloads that should be reused. |
| `tests.env` | map | `{}` | project | Extra environment variables for setup and test commands. |
| `tests.timeout` | integer | `900` | user, project | Seconds before a test command is stopped. |
| `tests.reruns` | integer | `2` | user, project | Reruns of each test case whose first attempt did not pass, to detect flaky tests. All of them always run, and they never change the result (`metrics.md`). |
| `tests.generated_dir` | string | `tests/retro` | project | Path inside each worktree where generated tests from `.retro/tests/` are copied before a run (ADR-0015). |

### Service

For projects whose tests need a running service (e.g. a REST API).

| Key | Type | Default | Levels | Description |
|---|---|---|---|---|
| `service.start` | string | none | project | Command that starts the service, using `{port}`. |
| `service.url` | string | `http://127.0.0.1:{port}` | project | Base URL of the running service. |
| `service.ready_path` | string | `/` | project | Path polled until it answers, to know the service is ready. |
| `service.ready_timeout` | integer | `30` | user, project | Seconds to wait for readiness before the test executions of the run are marked `blocked`. |

### Exit criteria

Thresholds only. Meaning, formulas and which criteria are blocking are defined in `metrics.md`.

| Key | Type | Default | Levels |
|---|---|---|---|
| `exit_criteria.min_pass_rate` | number 0..1 | `0.95` | user, project |
| `exit_criteria.min_high_priority_executed` | number 0..1 | `1.0` | user, project |
| `exit_criteria.min_requirement_coverage` | number 0..1 | `1.0` | user, project |
| `exit_criteria.max_open_defects.critical` | integer | `0` | user, project |
| `exit_criteria.max_open_defects.high` | integer | `0` | user, project |
| `exit_criteria.max_open_defects.medium` | integer or null | `null` | user, project |
| `exit_criteria.max_flaky_rate` | number 0..1 | `0.05` | user, project |
| `exit_criteria.max_new_failures` | integer | `0` | user, project |

`null` means no limit.

### Permissions

Values: `ask`, `allow`, `deny`. In mode `default`, `ask` prompts the user. In mode `auto`, `ask` is treated as `allow`. `deny` is always refused. In mode `plan`, all three actions are refused.

| Key | Default | Levels | Action |
|---|---|---|---|
| `permissions.run_tests` | `ask` | user, project | Run setup and test commands. |
| `permissions.write_tests` | `ask` | user, project | Write test code to `.retro/tests/`. |
| `permissions.start_service` | `ask` | user, project | Start the service of the target project. |

Writes of project memory, run evidence and reports inside `.retro/` do not require permission.

### Reports

| Key | Type | Default | Levels | Description |
|---|---|---|---|---|
| `reports.default_format` | enum | `md` | user, project | `md` or `pdf`. |

## Placeholders

Available in `tests.*` and `service.*` commands.

| Placeholder | Value |
|---|---|
| `{junit}` | Absolute path where the JUnit XML must be written, inside the run directory. |
| `{names}` | Selected test names joined with `tests.select_separator`, as defined under Test identity in `project-contract.md`. |
| `{port}` | Free port assigned to the service of this version. |
| `{worktree}` | Absolute path of the worktree being tested. |
| `{run_dir}` | Absolute path of the run directory (`.retro/runs/<run_id>/`). |
| `{cache_dir}` | Absolute path of a directory kept between runs for this project (`~/.retro/cache/<project-id>/`), for example for a package download cache. |

## Environment variables

### Read by RetroAgent

| Variable | Description |
|---|---|
| `RETRO_HOME` | Location of the user level. Default `~/.retro`. |
| `RETRO_MODEL` | Overrides `model`. |
| `RETRO_LANG` | Overrides `language`. |
| Provider keys | Any variable named in `api_key_env`, e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, `GEMINI_API_KEY`. |

### Provided to test commands

| Variable | Description |
|---|---|
| `RETRO_RUN_ID` | Current run ID. |
| `RETRO_VERSION` | `base` or `candidate`. |
| `RETRO_BASE_URL` | Base URL of the running service, when `service.start` is configured. |

### Environment of subprocesses

Setup, test and service commands, and every MCP server, start with the environment of `retro` without the model credentials: every variable named in an `api_key_env` of the user configuration, and the well-known key variables of the supported providers, are removed. `tests.env`, the variables above and the `env` of an MCP server declaration are then added. Tests and servers never need a model credential (ADR-0020), so none reaches them (NFR-16).

## User level files

```
~/.retro/
├── config.yaml          # User configuration and model profiles
├── mcp.json             # Optional: user MCP servers
├── approvals.json       # Approved project commands, MCP servers, steering and skills (managed by RetroAgent)
├── skills/              # Optional: user skills
├── steering/            # Optional: user steering
├── worktrees/           # Temporary checkouts, per project (managed by RetroAgent)
└── cache/               # Directories kept between runs, per project (managed by RetroAgent)
```

## MCP servers

Additional MCP servers are declared in `~/.retro/mcp.json` (user) or `<project>/.retro/mcp.json` (project), in the common format used by other agents:

```json
{
  "mcpServers": {
    "server-name": {
      "command": "executable",
      "args": ["--option", "value"],
      "env": { "VARIABLE": "value" }
    }
  }
}
```

## Examples

User level, `~/.retro/config.yaml`:

```yaml
model: local
language: en

models:
  local:
    provider: ollama
    name: <model-id>
    base_url: http://localhost:11434
    context_window: 32768
  claude:
    provider: anthropic
    name: <model-id>
    api_key_env: ANTHROPIC_API_KEY
  gpt:
    provider: openai
    name: <model-id>
    api_key_env: OPENAI_API_KEY
```

Project level, `<project>/.retro/config.yaml` (Linux and macOS paths):

```yaml
project:
  name: shop-api
  requirements: [docs/requirements.md]
  source: [src]

versions:
  base: v1.0
  candidate: v1.1

tests:
  setup: python -m venv .venv && .venv/bin/pip install -r requirements.txt
  command: .venv/bin/pytest tests --junitxml={junit}
  select: .venv/bin/pytest tests --junitxml={junit} -k "{names}"

service:
  start: .venv/bin/uvicorn src.main:app --port {port}
  ready_path: /health

exit_criteria:
  min_pass_rate: 0.98
```
