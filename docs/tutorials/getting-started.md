# Getting started

In this tutorial you install RetroAgent, configure a model, create the bundled example project and open a first session on it. It takes about fifteen minutes. The next tutorial, [Your first regression cycle](first-regression-cycle.md), continues from where this one ends.

## What you need

- Linux or macOS, with Python 3.11 or 3.12 and git.
- Internet access: the example project installs pytest in its own virtual environment the first time its tests run.
- A model. Either:
  - an API key of a hosted provider. This tutorial uses Google Gemini, whose free tier is enough for the example; or
  - [Ollama](https://ollama.com) with a model that supports tool calls. A small model on a CPU works, but a cycle takes about an hour instead of five minutes.

## 1. Install RetroAgent

```
git clone https://github.com/fe-ba/RetroAgent.git     # or git@github.com:fe-ba/RetroAgent.git with an SSH key
cd RetroAgent
python -m venv .venv
source .venv/bin/activate
pip install -e .
retro --version
```

The last command prints the version. Reports are written in Markdown. A PDF is produced only when you ask for it, and needs the Pango library (see the [README](../../README.md#requirements)).

## 2. Configure a model

RetroAgent reads model profiles from `~/.retro/config.yaml`. The folder does not exist on a new machine:

```
mkdir -p ~/.retro
nano ~/.retro/config.yaml
```

Write one profile:

```yaml
model: gemini
models:
  gemini:
    provider: google
    name: gemini-3.1-flash-lite
    api_key_env: GEMINI_API_KEY
    requests_per_minute: 12
```

`api_key_env` names the environment variable that holds the key; the key itself is never written in the configuration. Put the key in a file that only you can read and load it in your shell:

```
mkdir -p ~/.config/retroagent
nano ~/.config/retroagent/env          # write: export GEMINI_API_KEY=<your key>
chmod 600 ~/.config/retroagent/env
echo 'source ~/.config/retroagent/env' >> ~/.bashrc
source ~/.config/retroagent/env
```

The line added to `~/.bashrc` loads the key in every new terminal. In a new terminal, also activate the virtual environment again (`source <RetroAgent folder>/.venv/bin/activate`). A session that does not find the key does not start, and exits with code `2`.

`requests_per_minute: 12` keeps RetroAgent under the limit of the free tier, which is 15 calls per minute.

To use a local model instead, pull it with Ollama and add a second profile:

```
ollama pull qwen3.5:4b
```

```yaml
  local:
    provider: ollama
    name: qwen3.5:4b
    base_url: http://localhost:11434
    thinking: "off"
    context_window: 32768
    timeout: 900
```

A local model on a CPU writes about five tokens per second, so a long answer takes minutes: `timeout: 900` gives it fifteen minutes per call. `context_window` is required for Ollama. Select a profile for one session with `retro -m local`, or make it the default by changing `model:` in the file. [Configure models](../how-to/configure-models.md) covers the other providers.

## 3. Create the example project

```
retro example list
retro example shop-api ~/retro-demo
cd ~/retro-demo
git tag
```

`shop-api` is the back end of a small online shop, in Python and tested with pytest. The tags `v1.0`, `v1.1` and `v1.2` are three releases. Between `v1.0` and `v1.1` there are seeded cases that a regression cycle must find: a real regression in the shipping cost, a test made obsolete by a documented change, a flaky test, a test that always failed, a requirement without tests, and new tests added by the change.

Look around:

| File | What it is |
|---|---|
| `RETRO.md` | The description of the project for the agent: modules, how to run it, test conventions. The agent reads it at every turn. |
| `.retro/config.yaml` | The configuration of the project: requirements, versions, test commands, the service and the exit criteria. |
| `docs/requirements.md` | Requirements REQ-001 to REQ-008, each with an ID that tests and test cases trace to. The working copy is at `v1.2`; REQ-008 was added in `v1.1`. |
| `tests/` | The test suite of the project. |

## 4. Open a session

```
retro --base v1.0 --candidate v1.1
```

The session starts, states the model and whether it is hosted or local, and waits for a prompt. `--base` and `--candidate` set the two versions to compare; `.retro/config.yaml` sets the same ones, so here they are only explicit.

Try the commands that show the state of the project and of the agent:

| Command | Shows |
|---|---|
| `/status` | The session versions, test cases by status, the last run, the mode and the model calls used. Everything is empty for now. |
| `/mcp` | The four bundled MCP servers, `git`, `memory`, `test_runner` and `reports`, and the tools of the runtime, with their tools. `memory` includes `close_defect`, which only you can call, with `/defects close`. |
| `/skills` | The five skills: `impact-analysis`, `test-selection`, `test-design`, `failure-triage` and `test-reporting`. |
| `/model` | The model profile in use. |
| `/help` | Every command. |

Now ask something in plain language:

```
Which requirements does this project have, and which of them changed in v1.1?
```

The agent reads the requirements through its tools and answers. Below the answer, a line says what was recorded in project memory during the turn: if the agent only read files, nothing; if it also stored the requirements in project memory, it names `memory__sync_requirements`. That line is computed from the tool calls themselves, not from the model's text: it is how you check that the agent did what it says.

End the session with `/exit`. Project memory stays in `.retro/retro.db`, so the next session continues from it.

## What you learned

- RetroAgent works on a git project with two versions to compare, set with `--base` and `--candidate` or in `.retro/config.yaml`.
- The model acts only through tools, which `/mcp` lists, and follows procedures, which `/skills` lists.
- The recorded-actions line after each answer shows what the agent actually did.

Next: [Your first regression cycle](first-regression-cycle.md).
