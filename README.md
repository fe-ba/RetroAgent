# RetroAgent

RetroAgent is an AI agent for software regression testing. It runs in the terminal, on a git project of your own, and takes a change between two versions through the whole regression cycle: impact analysis, test selection, test design and implementation, execution, failure triage and a completion report with a release decision.

The model does the work that needs judgment: which requirements a change affects, which tests to select, what new tests to write, why a test failed. Everything that can be computed is computed by code: test results come only from the JUnit XML that the test run produced, and metrics, exit criteria and the release decision are calculated from stored records. The model cannot record a result, change a metric or contradict the decision.

RetroAgent has its own runtime and does not depend on any model vendor. It works with hosted models (Google, Anthropic, OpenAI, xAI) and with local models served by Ollama.

## How it works

```
retro ──> runtime ──> model (hosted or local)
             │
             ├── steering: rules that are always in context
             ├── skills: procedures loaded for each step
             └── MCP servers: git, memory, test_runner, reports
                    │
                    ├── project memory (.retro/retro.db, SQLite)
                    └── test runs in git worktrees, outside the project
```

- **Steering** (6 files) states who the agent is, the workflow, the test states, the quality rules, the safety rules and the output format.
- **Skills** (5) hold the procedure of each step: `impact-analysis`, `test-selection`, `test-design`, `failure-triage` and `test-reporting`.
- **MCP servers** (4) are the only way the model acts on the project. Their tools check what the model records: a triage needs evidence, a suite must include every test that passed on the baseline and failed on the candidate, a defect needs a test that failed for a product fault.
- **Project memory** keeps requirements, test cases, runs, executions, triage, defects and reports between sessions, in the project's `.retro/` folder.

`/cycle` runs the eight steps in order: `analyze`, `discover`, `select`, `design`, `implement`, `run`, `triage` and `report`. Each step gets an empty conversation and only the tools it needs, and code checks its outcome before the next step starts.

## Requirements

- Python 3.11 or 3.12.
- git.
- For PDF reports, which are produced on request: the Pango library (`apt install libpango-1.0-0 libpangoft2-1.0-0` on Debian or Ubuntu, `pacman -S pango` on Arch, `brew install pango` on macOS). Markdown reports work without it.
- A model: an API key for a hosted provider, or Ollama with a model that supports tool calls.

## Install

```
git clone git@github.com:fe-ba/RetroAgent.git        # or https://github.com/fe-ba/RetroAgent.git
cd RetroAgent
python -m venv .venv
source .venv/bin/activate
pip install -e .
retro --version
```

## Configure a model

Model profiles live in `~/.retro/config.yaml`. The API key is never written there: the profile names the environment variable that holds it.

```yaml
model: gemini
models:
  gemini:
    provider: google
    name: gemini-3.1-flash-lite
    api_key_env: GEMINI_API_KEY
    requests_per_minute: 12
  local:
    provider: ollama
    name: qwen3.5:4b
    base_url: http://localhost:11434
    thinking: "off"
    context_window: 32768
    timeout: 900
```

```
export GEMINI_API_KEY=...        # in your shell profile, not in a file of the project
retro -m local                   # use another profile for one session
```

See [Configure models](docs/how-to/configure-models.md) and the [configuration reference](docs/reference/configuration.md).

## Quick start

RetroAgent ships an example project, `shop-api`, with three tagged versions and known regressions.

```
retro example shop-api ~/retro-demo
cd ~/retro-demo
retro --base v1.0 --candidate v1.1
```

In the session:

```
/cycle
```

The first test run asks you to approve the project's commands. Then, in mode `default`, the agent asks before it runs tests, starts the service or writes test code: press `1` to allow once, `2` to allow for the session, `3` or `Esc` to deny. At the end, the completion report is in `.retro/reports/`, and the session shows the release decision. For `v1.0` to `v1.1` it is `do_not_release`: a shipping test reveals a regression, and a defect is registered for it.

The same cycle without a session, for scripts and CI:

```
retro -p --mode auto --trust-commands --base v1.0 --candidate v1.1 "/cycle"
echo $?    # 3: completed with decision do_not_release
```

To use it on your own project, run `retro init` in it. See [Set up a project](docs/how-to/set-up-a-project.md).

## Documentation

The documentation is in [`docs/`](docs/README.md), organized as tutorials, how-to guides, reference and explanation. Good places to start:

- [Getting started](docs/tutorials/getting-started.md) and [Your first regression cycle](docs/tutorials/first-regression-cycle.md).
- [CLI reference](docs/reference/cli.md): commands, options, slash commands and exit codes.
- [MCP, skills and steering](docs/explanation/mcp-skills-steering.md): how the agent is put together.
- [Architecture](docs/explanation/architecture.md) and the [decision records](docs/adr/README.md).
- [Limitations and risks](docs/explanation/limitations-and-risks.md).

The internal specification that the code was built from is in [`spec/`](spec/).

## Development

```
pip install -e ".[dev]"
pytest
ruff check .
```

Automated tests never call a real model: the model is replaced by `FakeProvider`, which replays scripted answers. Scenarios that need a real model are run by hand, and their results are recorded in [`spec/acceptance-scenarios.md`](spec/acceptance-scenarios.md). CI runs ruff, the tests and the package build on Python 3.11 and 3.12.

## Status

RetroAgent was built as the project of the course Seminario de Ingeniería de Software. The whole cycle works with a hosted model (Gemini 3.1 Flash-Lite: about 40 model calls and 5 minutes for the example). A small local model on a CPU (`qwen3.5:4b`) gets the integrity checks right but is slow, about an hour per cycle, and may stop in a step by repeating a call. See [Limitations and risks](docs/explanation/limitations-and-risks.md).

## License

MIT. See [LICENSE](LICENSE).
