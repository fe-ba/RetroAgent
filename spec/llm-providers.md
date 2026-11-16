# LLM providers

How the runtime talks to models. The runtime depends only on the `LLMProvider` interface (ADR-0003); LiteLLM is the default implementation behind it. Model profiles are configured as described in `configuration.md`.

## Implementations

| Implementation | Use |
|---|---|
| `LiteLLMProvider` | Default. Reaches every supported provider through LiteLLM. |
| `FakeProvider` | Tests. Returns scripted responses in order and records every request, so the runtime can be tested without a model and with reproducible results. |

## Interface

### `complete(request) -> response`

One model call. The runtime never calls a provider library directly.

**Request**

| Field | Type | Description |
|---|---|---|
| `messages` | list | Messages with role `system`, `user`, `assistant` or `tool`. Assistant messages may carry tool calls; tool messages carry the ID of the call they answer. |
| `tools` | list | Tool definitions: `name`, `description` and a JSON schema for the arguments. Empty in JSON fallback mode. |
| `temperature` | number | From the model profile. |
| `max_output_tokens` | integer | Limit for the response, from the model profile. It is also the output reserve of the context budget. |
| `context_window` | integer | Context size to use, sent to the providers that accept one. |
| `thinking` | string | `default`, `on` or `off`, from the model profile, for the providers that accept it. |
| `timeout` | number | Seconds, from the model profile. |

**Response**

| Field | Type | Description |
|---|---|---|
| `text` | string | Text of the response. May be empty when there are tool calls. |
| `tool_calls` | list | Each: `id`, `name`, `arguments` (an object). Empty when there are none. |
| `finish_reason` | string | `stop`, `tool_calls` or `length`. |
| `thinking` | string or null | Reasoning text of a reasoning model. Shown in verbose mode; never kept in the conversation. |
| `usage` | object | `input_tokens` and `output_tokens`, or null when the provider does not report them. |

### `capabilities() -> capabilities`

| Field | Type | Description |
|---|---|---|
| `tool_calling` | boolean or null | Whether the model supports tool calling; null when unknown. |
| `context_window` | integer or null | Maximum context size in tokens; null when unknown. The `context_window` of the model profile takes precedence. |

### Streaming

Optional. A provider may stream the text of a response for display. Tool calls are always delivered complete, never streamed.

## Providers

| `provider` | LiteLLM model | Credentials | `base_url` |
|---|---|---|---|
| `anthropic` | `anthropic/<name>` | `api_key_env` | Optional |
| `openai` | `openai/<name>` | `api_key_env` | Optional |
| `xai` | `xai/<name>` | `api_key_env` | Optional |
| `google` | `gemini/<name>` | `api_key_env` | Optional |
| `ollama` | `ollama_chat/<name>` | None | Required |
| `openai_compatible` | `openai/<name>` | `api_key_env`, optional | Required. For LM Studio, vLLM, llama.cpp server and similar. |

API keys are read from the variable named in `api_key_env` at the time of each call. They are never written to files, logs, tool call records or reports (NFR-06). A profile whose variable is not set stops the session at start with exit code `2`, naming the variable but not its value.

## Tool calling

The `tool_calling` setting of the model profile selects how tools are offered.

| Value | Behavior |
|---|---|
| `native` | Tools are sent as tool definitions and the model answers with tool calls. |
| `json` | JSON fallback mode, described below. |
| `auto` | Uses `capabilities().tool_calling` when known. When unknown, the runtime sends one probe call at the start of the session, with a trivial tool and an instruction to call it, and uses `native` if the response contains a valid call to that tool, `json` otherwise. |

## JSON fallback mode

For models that cannot call tools natively.

**Tools.** Tool definitions are written into the system context, after the skills index, in a `# Tools` section: name, description and JSON schema of each tool, with the instruction to answer only in the format below.

**Answer format.** Every model answer is exactly one JSON object, in one of two shapes:

```json
{"type": "tool_calls", "tool_calls": [{"name": "memory__get_suite", "arguments": {}}]}
```

```json
{"type": "message", "content": "Text for the user."}
```

**Validation.** The runtime:

1. Removes a surrounding Markdown code fence, if present.
2. Parses the JSON.
3. Checks the shape, that every tool name exists, and that the arguments match the schema of the tool.
4. Assigns an ID to each call.

An invalid answer is returned to the model as a user message with the validation error and the expected format. After two invalid answers in a row, the turn fails with a runtime error.

**Tool results.** Each result is returned as a user message that starts with `Tool result for <name> (<id>):`, followed by the result as JSON.

## Errors and retries

| Error | Retries | Behavior |
|---|---|---|
| Rate limit | Up to 3 | Waits the time the provider indicates, or 2, 4 and 8 seconds. |
| Network error, server error or timeout | Up to 3 | Waits 2, 4 and 8 seconds. |
| Authentication rejected | None | Runtime error that names the variable of the profile, not its value. |
| Context window exceeded | 1 | The runtime frees context and retries once (`context-loading.md`); then a runtime error. |
| Invalid request | None | Runtime error with the provider message. |
| Response cut by `length` with tool calls | 1 | Retried once with an instruction to answer more briefly; then a runtime error. |
| Response cut by `length` without tool calls | None | The text is kept and marked as incomplete. |

A runtime error ends the current turn; in non-interactive mode it exits with code `1`. Every retry is shown in verbose mode.

## Usage

Token usage is added up per session and shown in verbose mode. It is not stored in project memory. The runtime also uses the input tokens of each call to calibrate its size estimates and to detect a server that dropped part of the context (`context-loading.md`).

## Context size, state message and caching

- **`ollama`** is reached through its native chat API, which accepts a context size. The adapter sends the `context_window` of the profile with every request. Without it, the server applies its own default and drops the beginning of a longer context without an error.
- **`openai_compatible`** servers cannot be told a context size by the request. The server must be configured with at least the `context_window` of the profile; the truncation guard is the only protection when it is not.
- **State message.** The last message of every request is generated by the runtime with the user role. When a provider requires roles to alternate, the adapter merges it with the preceding message of the same role.
- **Caching.** The context is ordered from stable to volatile. Where a provider caches a repeated beginning by itself, nothing else is needed. Where it needs explicit markers, the adapter marks the end of the tool definitions and of the system context.

## Privacy

With a hosted provider, the context of every call leaves the machine: steering, `RETRO.md`, and the files, diffs and logs returned by tools. With `ollama` or a local `openai_compatible` server, nothing leaves the machine (NFR-10). `retro` states which kind of provider is in use when a session starts.

## Adding a provider

A provider supported by LiteLLM is added with a new row in the providers table and a new `provider` value in `configuration.md`. A provider that LiteLLM does not support is added with a new implementation of `LLMProvider` (NFR-09). Neither change touches the runtime.

## Testing

- The runtime is tested with `FakeProvider`.
- Each provider in the table has a contract test that sends one tool call and one message. Contract tests run only when the credentials or the local server are available, and are skipped otherwise.
- The JSON fallback validation is tested with valid, fenced, malformed and schema-violating answers.
