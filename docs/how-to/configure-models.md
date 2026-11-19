# Configure models

How to add a model profile, keep its key out of every file, switch between models, and tune a profile for a rate-limited service or a slow local model. Every key is described in the [configuration reference](../reference/configuration.md#model-profiles).

## Where profiles live

Model profiles are defined only at user level, in `~/.retro/config.yaml`, under `models`. A project cannot define a profile: it can only name one with `model`. A repository you test therefore cannot point the agent at another endpoint, or read your keys.

```yaml
model: gemini          # default profile
models:
  gemini:
    ...
  local:
    ...
```

`retro config list` shows the effective configuration and the level each value comes from.

## Add a hosted model

Each hosted provider needs `provider`, `name` and `api_key_env`:

| Provider | `provider` | Usual key variable |
|---|---|---|
| Google Gemini | `google` | `GEMINI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| xAI | `xai` | `XAI_API_KEY` |

```yaml
models:
  gemini:
    provider: google
    name: gemini-3.1-flash-lite
    api_key_env: GEMINI_API_KEY
    requests_per_minute: 12
```

`name` is the model identifier as the provider expects it.

### Keep the key out of files

`api_key_env` names the variable; the key itself is never written in the configuration. Set the variable in your shell from a file that only you can read:

```
mkdir -p ~/.config/retroagent
nano ~/.config/retroagent/env          # export GEMINI_API_KEY=<your key>
chmod 600 ~/.config/retroagent/env
echo 'source ~/.config/retroagent/env' >> ~/.bashrc
```

Do not pass a key on the command line, where it stays in the shell history, and do not put it in a file of a project. RetroAgent removes every model key from the environment of the test commands and of the MCP servers, so tests never see it.

A session whose profile names a variable that is not set does not start, and exits with code `2`.

### Stay under a rate limit

Free tiers limit calls per minute. `requests_per_minute` makes the runtime wait between calls to stay under the limit. Set it a little below the limit of the service: `12` for a limit of 15. A cycle on the example project makes about 40 to 60 calls, so it takes a few minutes either way.

When the service still answers with a rate limit, the call is retried up to three times with a wait. A daily quota cannot be waited out: the turn stops with a message that names the limit. Project memory keeps the work done, and `/cycle` continues from the step that stopped.

## Add a local model with Ollama

Install [Ollama](https://ollama.com), start it and pull a model that supports tool calls:

```
ollama serve &
ollama pull qwen3.5:4b
```

```yaml
models:
  local:
    provider: ollama
    name: qwen3.5:4b
    base_url: http://localhost:11434
    context_window: 32768
    timeout: 900
    thinking: "off"
```

| Key | Why |
|---|---|
| `base_url` | Required for Ollama. |
| `context_window` | Required for Ollama, and sent with every request as the context size to use. Without it, Ollama may apply a smaller default and silently drop the beginning of the context, which holds the steering. Use 32,768 or more. |
| `timeout` | Seconds per call. A small model on a CPU writes about five tokens per second, so an answer of a few hundred tokens takes minutes. The default of 120 seconds is too short; use 900. |
| `thinking` | For reasoning models. `"off"` asks for answers without a thinking phase, which is much faster on a CPU. Quote it: YAML reads a bare `off` as a boolean. Both forms are accepted. |

No `api_key_env`: a local model needs no key, and the profile is refused if it has one.

Any other server with an OpenAI-compatible API, such as LM Studio or vLLM, uses `provider: openai_compatible` with `base_url` and `context_window`, and `api_key_env` only if it needs a key.

Before a long run with a local model, check that Ollama answers:

```
curl -s http://localhost:11434 && echo
```

If Ollama is down, the model calls fail with a network error, are retried three times and then stop the turn.

## Switch models

| To | Do |
|---|---|
| Use a profile for one session | `retro -m local` |
| Use a profile for one command in a script | `retro -m local -p "/analyze"`, or `RETRO_MODEL=local` |
| Switch inside a session | `/model local` |
| See the profile in use | `/model` |
| Change the default | `retro config set model local` |

The session states the model it uses, and whether it is hosted or local, when it starts. Records written by the agent, such as a test case design or a triage, store the model that wrote them.

## Models without native tool calls

`tool_calling: auto`, the default, uses native tool calls when the provider reports support for them. When support is unknown, the runtime sends one probe call at the start of the session. A model that cannot make tool calls is driven in JSON fallback mode: the tool definitions are written into the context and the model answers with JSON, which the runtime validates. Force either mode with `tool_calling: native` or `tool_calling: json`.

## Other settings

| Key | Default | When to change it |
|---|---|---|
| `temperature` | `0` | Rarely. Low values give more reproducible behavior. |
| `max_output_tokens` | `4096` | When a model's answers are cut off. This space is kept free in the context window. |

Which models work well, and what was measured with each, is in [Model compatibility](../explanation/model-compatibility.md).
