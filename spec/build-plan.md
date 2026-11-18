# Build plan

The order in which RetroAgent is built, what each stage contains, and when a stage is done. It is written for the coding agent that writes the code and for the person who reviews it. The specification is complete before the code starts; this plan adds no behavior.

## Rules of work

1. **The specification decides.** Code implements `spec/` and `docs/reference/`. When two documents disagree, or a document cannot be implemented as written, stop and report it; do not choose. The fix goes into the document first, with an ADR when it changes a decision.
2. **One slice at a time.** A slice is finished, with its tests passing, before the next one starts. Nothing of a later slice is built early.
3. **Tests first where the result is exact:** invariants, metrics, exit criteria, the decision rule, parsing of JUnit XML and context assembly.
4. **`Must` only.** Requirements with priority `Should` or `Could` are not built before slice 5, even when they look easy.
5. **Small surface.** No abstraction for a second case that does not exist. One loop, one permission table, one cycle (ADR-0026).
6. **Libraries are read, not remembered.** The MCP SDK and LiteLLM change often. Use the installed version and its documentation, not memory of an older API.
7. **Everything in English:** code, comments, messages, commits. Commits use the form `<area>: <summary>`.

## Slices

Each slice cuts through several components and ends with something that runs. The scenarios are those of `acceptance-scenarios.md`.

| Slice | Result | Done when |
|---|---|---|
| 0. Skeleton | An installable package with a `retro` command. | `pip install -e ".[dev]"` works; `retro --version` prints the version; `retro example shop-api <dir>` passes SC-01; `pytest` runs. |
| 1. Evidence without a model | Tests run against both versions and their results are stored and evaluated. No model is involved. | SC-05, SC-06, SC-07 and SC-08 pass. Every invariant enforced by the data layer has a unit test; INV-03 and INV-14 are tool contracts, and the `expected_change` evidence of INV-15 needs git, so they are tested in slice 4. Metrics and the decision rule have full unit coverage (NFR-12). |
| 2. Report | The completion report in Markdown and PDF, with charts. Agent sections say `Not provided.` | Given the records of the reference scenario, loaded by a fixture, the computed sections equal `expected/test-completion-report.md` (SC-10 and SC-11 without the model). |
| 3. First turn of the agent | A session with a model that analyzes the impact of a change. | SC-02 passes. The turn, the permissions and the context pass their tests with `FakeProvider`. `/analyze v1.0 v1.1` works with a real model. The fixed part of the context is measured (see below). |
| 4. The whole cycle | Every skill, the approval of commands, and `/cycle`. | SC-03, SC-04 and SC-09 to SC-20 pass. SC-21 to SC-28 were run with one local and one hosted model and recorded. |
| 5. Extensions | `Should` requirements, in the order of the table at the end. | The extended scenario of each one passes. |

Slices 1 and 2 need no model on purpose. They prove first what the brief asks most (a designed test is not an executed test, and an executed test is not a passed test), and they leave a result that can be shown even if the rest is late.

### Slice 0: skeleton

| Build | In | Read |
|---|---|---|
| Package metadata and entry point | `pyproject.toml`, `src/retroagent/__init__.py`, `cli/main.py` | `cli.md` (options, exit codes) |
| Resource access through the package | `resources/__init__.py` or a small `resources.py` | ADR-0025 |
| `retro example` | `cli/`, reusing the logic of `resources/examples/materialize.py` as a function of the package | `resources/examples/README.md` |
| Pinned versions | `constraints.txt`, from `pip freeze` after the first installation | — |

### Slice 1: evidence without a model

| Build | In | Read |
|---|---|---|
| Schema, migrations, identifiers, invariants | `memory/` | `data-model.md`, ADR-0008, ADR-0016 |
| Configuration: levels, validation, the keys this slice uses | `config/` | `configuration.md` |
| Worktrees, setup, service, test command, process groups, clean environment | `servers/test_runner/` | `project-contract.md`, ADR-0009, ADR-0015, ADR-0024 |
| JUnit XML parsing, attempts, test identity, discovery, `not_reported` | `servers/test_runner/` | `project-contract.md`, ADR-0010, ADR-0023 |
| Metrics, exit criteria, decision | `metrics/` | `metrics.md`, ADR-0017, ADR-0022 |
| Session record, lock, recovery | `runtime/session` | `runtime.md` (Start, End) |
| Direct commands `/run`, `/status`, `/history`, as functions and as a minimal prompt | `runtime/commands`, `cli/` | `cli.md`, `runtime.md` |

The servers are written as plain functions over the data layer first, and exposed through MCP in slice 3. The approval of project commands is in slice 4; until then the runner refuses to run unless `--trust-commands` is given.

### Slice 2: report

| Build | In | Read |
|---|---|---|
| Markers, values, blocks and items | `reports/` | `reports.md`, ADR-0018, ADR-0019 |
| Charts as SVG | `reports/charts` | `reports.md` (Charts) |
| Markdown to PDF | `reports/pdf`, `resources/templates/styles/` | ADR-0018 |
| `prepare_report` and `render_report` as functions | `servers/reports/` | `mcp-tools.md` |
| A fixture that loads the records of the reference scenario | `tests/fixtures/` | `ORACLE.md` (Reference scenario) |

### Slice 3: first turn of the agent

| Build | In | Read |
|---|---|---|
| Provider interface, LiteLLM adapter, `FakeProvider` | `llm/` | `llm-providers.md`, ADR-0003 |
| System context, skills index, tool sets, state message, budget, truncation guard | `context/` | `context-loading.md`, ADR-0021, ADR-0028 |
| Turn loop, modes, permissions, tool call audit | `runtime/` | `runtime.md`, ADR-0011 |
| MCP client; `git`, `memory` and `test_runner` exposed as MCP servers | `mcp_client/`, `servers/` | `mcp-tools.md`, ADR-0004, ADR-0020, ADR-0026 |
| Tools of the `git` server and of impact analysis | `servers/git/`, `servers/memory/` | `mcp-tools.md` |
| `retro init`, the interactive session, `/analyze`, `/clear`, `/mode`, `/model`, `/skills` | `cli/`, `runtime/commands` | `cli.md`, `project-contract.md` |

**Measuring the context.** As soon as the tool definitions exist, run the test that prints the fixed part of every tool set, and write the figures here. If the largest one exceeds half of a window of 32,768 tokens minus the output reserve, shorten tool descriptions before going on. This replaces the estimate of 9,000 to 11,000 tokens in `limitations-and-risks.md`.

Measured at the end of slice 4, on shop-api: system context (14,117 characters), tool definitions of the step, and the state message of the reference scenario (891 characters). Tokens at the starting ratio of 1.3 characters per token over 4; budget 28,672 tokens (window 32,768 minus reserve 4,096).

| Tool set | Tools | Fixed part (characters) | Estimated tokens | Share of budget | With the skill of the step |
|---|---|---|---|---|---|
| analyze | 19 | 25,030 | 8,135 | 28.4% | 33.7% |
| select | 17 | 23,518 | 7,644 | 26.7% | 30.7% |
| design | 18 | 25,788 | 8,382 | 29.2% | 36.8% |
| implement | 19 | 26,628 | 8,655 | 30.2% | 37.7% |
| triage | 19 | 24,498 | 7,962 | 27.8% | 34.5% |
| report | 19 | 23,658 | 7,689 | 26.8% | 31.0% |
| free message | 33 | 37,734 | 12,264 | 42.8% | — |

Every tool set stays under half of the budget, and every one is above the 25% warning, so a window of 32,768 tokens always shows that warning at start. Reported by the provider for the first call of a step with Gemini: 5,892 to 6,123 input tokens, below the estimate.

### Slice 4: the whole cycle

| Build | In | Read |
|---|---|---|
| Remaining tools of `memory`, `test_runner.write_test`, `get_evidence`, `reports` as an MCP server | `servers/` | `mcp-tools.md`, ADR-0022, ADR-0023 |
| Triage validation, closing of defects by a run | `memory/`, `servers/test_runner/` | `data-model.md` (INV-14, INV-15) |
| Approval of project commands, `--trust-commands` | `config/approvals`, `runtime/permissions` | `configuration.md`, ADR-0024 |
| Model commands and `/cycle` | `runtime/commands`, `runtime/cycle` | `runtime.md`, ADR-0027 |
| Non-interactive mode and exit codes | `cli/` | `cli.md` |
| The reference script for `FakeProvider` | `tests/fixtures/` | `ORACLE.md` |

### Slice 5: extensions

In this order, each one only if the time allows: PDF styles and the criteria chart (FR-38); the test plan, status and defect reports (FR-37); rewrite and retire (FR-36); `retro config` and `retro defects close` (FR-39); JSON fallback mode and the other providers (NFR-17); user and project steering, skills and MCP servers (FR-31, FR-32); translated templates (NFR-18).

## Modules

| Package | Modules |
|---|---|
| `cli` | `main` (options, commands, exit codes), `interactive` (prompt, keys), `tables` |
| `config` | `loader` (levels, environment), `schema` (keys, validation), `approvals` |
| `memory` | `schema.sql`, `migrations`, `db` (connection, transactions), `ids`, one module per group of tables |
| `metrics` | `compute`, `criteria`, `decision` |
| `servers.git` | `server`, `changes` |
| `servers.memory` | `server`, `requirements` (parsing), `triage` (evidence checks) |
| `servers.test_runner` | `server`, `worktree`, `process`, `junit`, `runner`, `generated` |
| `servers.reports` | `server` |
| `reports` | `render` (markers), `blocks`, `charts`, `pdf` |
| `llm` | `provider` (interface), `litellm_provider`, `fake` |
| `context` | `system`, `skills`, `tools`, `state`, `budget` |
| `runtime` | `session`, `turn`, `permissions`, `commands`, `cycle`, `tools` (the `runtime` tools) |
| `mcp_client` | `client` |

A module is created when its slice needs it. This table is a map, not a list of files to create in advance.

## Tests

| Folder | Content |
|---|---|
| `tests/unit/` | One test per invariant; metrics, criteria and decision; JUnit parsing; requirement parsing; configuration levels; context snapshots; budget and guard. |
| `tests/integration/` | The direct and scripted scenarios, on a project created with `retro example` in a temporary directory. |
| `tests/fixtures/` | The records of the reference scenario and the reference script. |

Integration tests create their own example project and never touch a directory of the user. Tests that need a real model are not part of `pytest`; model scenarios are run by hand.

## Models for development

| Use | Profile |
|---|---|
| Development and the model scenarios | `google` with `gemini-3.1-flash-lite` on the free tier, `requests_per_minute: 12`. Measured: every check of the model test passed, about 2 seconds per call. Its limits on the development account are 15 requests per minute and 500 per day, so a cycle of about 60 calls can run a few times a day; `gemini-3.5-flash-lite` has a separate quota of the same size. Stronger models of that tier allow 20 requests per day, which is less than one cycle. |
| The local model of the presentation | `ollama` with `qwen3.5:4b`, `thinking: off`, and a `context_window` of 32,768 if the machine allows it. Measured on the development machine: all the checks of the model test passed three times out of three; short calls take 2 to 30 seconds on CPU, and a context read for the first time takes minutes. |

The local model is used on a short scenario (SC-22 or SC-25) or on a recorded run of SC-28, not for development.

## Schedule

Delivery is on Wednesday, November 25, with Monday 23 as the date by which the core must work.

| Day | Slice | Checkpoint |
|---|---|---|
| Mon 16 | 0, and the data layer of 1 | `retro example` works; invariants pass. |
| Tue 17 | 1 | SC-05 to SC-08 pass. |
| Wed 18 | 2 | The generated report equals the expected one. |
| Thu 19 | 3: provider, context, turn | Turn and context tests pass with `FakeProvider`. |
| Fri 20 | 3: MCP, tools, session | `/analyze` works with a real model. Context measured. |
| Sat 21 | 4: tools, approvals, model commands | Each model command works alone. |
| Sun 22 | 4: `/cycle`, scripted scenarios | SC-09 to SC-20 pass. |
| Mon 23 | Model scenarios | SC-21 to SC-28 recorded for both models. |
| Tue 24 | `README.md`, tutorials, course deliverables | A clean installation follows the README. |
| Wed 25 | Delivery | — |

**When a day slips.** Slices 0 to 2 are not negotiable: they are the evidence the brief asks for. If slice 3 is not done on Friday 20, nothing of slice 5 is built. If `/cycle` is not done on Sunday 22, the presentation uses the model commands one by one, which need the same tools. If no local model completes SC-28, the local model is shown on a shorter scenario and the limitation is stated.
