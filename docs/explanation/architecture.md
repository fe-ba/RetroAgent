# Architecture

How RetroAgent is built: its components, the processes they run in, who owns each piece of data, and what happens during a tool call and during a regression cycle. The decisions behind it are in the ADRs named in each section.

## Diagrams

The diagrams are PlantUML sources in `docs/diagrams/`:

| Diagram | File | Shows |
|---|---|---|
| Components | `components.puml` | Components, interfaces, artifacts and their dependencies. |
| One turn | `tool-call-sequence.puml` | A turn of the agent loop with a tool call. |
| Cycle | `cycle-sequence.puml` | The steps of `/cycle` and the checks between them. |

## Components

| Component | Package | Responsibility | Decisions |
|---|---|---|---|
| CLI | `retroagent.cli` | Options, commands outside a session, the interactive prompt and terminal tables. | ADR-0011 |
| Runtime | `retroagent.runtime` | Session, turn loop, slash commands, cycle command, modes, permissions and approvals. | ADR-0026, ADR-0027 |
| Context builder | `retroagent.context` | System context, tool sets, state message and context budget. | ADR-0005, ADR-0021, ADR-0028 |
| Provider adapter | `retroagent.llm` | The only component that talks to a model. One interface, one adapter over LiteLLM, and `FakeProvider` for tests. | ADR-0003 |
| MCP client | `retroagent.mcp_client` | Starts the servers, lists their tools and dispatches calls. | ADR-0004 |
| Bundled MCP servers | `retroagent.servers` | `git`, `memory`, `test_runner` and `reports`: every action on the project. Thin layers over the components below. | ADR-0004, ADR-0020 |
| Data layer | `retroagent.memory` | The only writer of the database. Schema, migrations, invariants and identifiers. | ADR-0008, ADR-0016 |
| Metrics and decision | `retroagent.metrics` | Pure functions from stored records to metrics, exit criteria and the release decision. | ADR-0006, ADR-0017, ADR-0022 |
| Report renderer | `retroagent.reports` | Markers, blocks, charts and PDF. | ADR-0018, ADR-0019 |
| Configuration | `retroagent.config` | Levels, restricted keys, validation and approvals. | ADR-0014, ADR-0024 |
| Resources | `retroagent.resources` | Steering, skills, templates and examples shipped in the package. | ADR-0025 |

## Processes

| Process | Started by | Lifetime |
|---|---|---|
| `retro` | The user | One session. Holds the runtime, the context builder, the provider adapter and the MCP client. |
| One process per MCP server | The runtime, at session start | One session, for one project. Talks to the runtime over standard input and output. |
| Setup, test and service commands | The `test_runner` server | One run. In their own process group, inside a worktree outside the project. |
| The model | Outside RetroAgent | A hosted service, or a local server such as Ollama. |

The runtime and the servers share nothing in memory. They share the database, through the data layer, and the `session` record is how the servers know the versions and the model of the session (ADR-0026).

## Who owns what

| Data | Written by | From |
|---|---|---|
| Session, tool calls | Runtime | Its own state. |
| Requirements, analysis impact, risks, test cases, suites, triage, defects | `memory` server | Proposals of the model, validated by the data layer. |
| Change set of an analysis | `git` server | `git diff` between two commits. |
| Runs, executions, attempts, test identity, closing of defects | `test_runner` server | Run evidence only: JUnit XML, exit codes, logs. |
| Generated test code | `test_runner` server | Code proposed by the model, shown to the user before it is written. |
| Evaluations, reports | `reports` server | Stored records, through the metrics component. |

Two rules follow from this table and hold whoever calls the tools. No tool has an input for a test result, so a result can only come from a run. And metrics, exit criteria and the release decision are computed from stored records, never written by the model.

## Trust boundaries

| Boundary | What crosses it | Protection |
|---|---|---|
| Target project to the model | Diffs, files, logs, `RETRO.md` | Presented as data, never as rules. Project steering, skills and MCP servers need approval (ADR-0021). |
| Target project to the machine | Setup, test and service commands; tests | Approval of the exact commands; no model credentials in their environment; worktrees outside the project. Not a sandbox (ADR-0024). |
| The model to project memory | Tool calls | Modes and permissions before dispatch; invariants and evidence checks in the data layer (ADR-0016, ADR-0022). |
| The machine to a hosted model | The whole context of each call | Stated at session start; a local model keeps everything on the machine. |

## A tool call

1. The turn loop builds the context: stable system context, tool definitions of the current tool set, the conversation, and the state message with the digest of project memory.
2. The provider adapter calls the model and returns text, tool calls and token usage. The runtime uses the usage to calibrate its estimates and to detect a truncated context.
3. Each tool call is recorded, checked against the mode, the permissions and the approvals, and dispatched to its server.
4. The server acts on the project or on memory through the data layer, which enforces the invariants in the same transaction.
5. The result goes back to the conversation as data, and the loop continues until the model answers without tool calls.

## A regression cycle

`/cycle` is the same loop driven by code. The runtime decides the order of the steps; each model step is a turn with an empty conversation and the tools of that step; direct steps call the `test_runner` server without the model. After each step, code checks its outcome in project memory before the next one starts. What a step needs from the previous ones is in memory, not in the conversation.
