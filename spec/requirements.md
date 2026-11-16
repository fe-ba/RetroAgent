# Requirements

Functional (FR) and non-functional (NFR) requirements of RetroAgent.

- **Priority** follows MoSCoW: `Must` is required for the project to be valid, `Should` is expected, `Could` is optional if time allows.
- **Source** links each requirement to the project brief or to an ADR.

The `Must` requirements are the core: what has to work end to end, on the example project, for the project to be presented. They are built first, as a thin path through every component. `Should` requirements are built after the core works, in the order that the remaining time allows, and `Could` requirements only after them. Lowering a priority does not remove the specification of the feature.

## Brief references

| ID | Brief item |
|---|---|
| B1 | Analyze: receive source code, API, requirements or documentation; identify what can be tested and what information is missing. |
| B2 | Design: generate test cases with objective, preconditions, input data, steps, expected result, priority and traceability. |
| B3 | Execute: use real tools through MCP; record results, times, errors and evidence. |
| B4 | Visualize and interpret: tables, charts and reports; explain findings, limitations and recommended actions. |
| B5 | Distinguish a designed test, an executed test and a passed test. |

## Functional requirements

### Session and interaction

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-01 | The agent shall start an interactive session on the current directory or on a directory given as an argument. | Must | ADR-0001, ADR-0011 |
| FR-02 | The agent shall run a single task non-interactively and exit with a code that reflects the outcome. | Should | ADR-0011 |
| FR-03 | The agent shall initialize a project: detect its type, create `RETRO.md`, `.retro/config.yaml` and `.retro/.gitignore`. | Must | ADR-0011 |
| FR-04 | The agent shall let the user select the model for a session and set a default model at user level. | Must | ADR-0026 |
| FR-05 | The agent shall provide a plan mode in which it analyzes and designs but cannot execute tests. | Must | B5, ADR-0011 |
| FR-06 | The agent shall ask for permission before running tests, starting services or writing test code, unless the configuration allows the action. The prompt shall show the test code or the commands it asks about. | Must | ADR-0011, ADR-0024 |
| FR-40 | The agent shall run the whole regression cycle with one command, one step at a time, each step in a fresh conversation, and check the outcome of each step against stored data before the next. | Must | NFR-01, ADR-0027 |
| FR-39 | The CLI shall provide `retro config` and `retro defects close`. | Should | ADR-0011 |

### Analysis

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-07 | The agent shall resolve the baseline and the candidate from tags, branches or commits. | Must | B1 |
| FR-08 | The agent shall compute the change set between baseline and candidate. | Must | B1 |
| FR-09 | The agent shall map the change set to modules, requirements and existing test cases, and assign a risk level to each impacted area. | Must | B1 |
| FR-10 | The agent shall read the requirements of the target project when they are documented, report which information is missing and ask for it. | Must | B1 |

### Design

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-11 | The agent shall design test cases with objective, preconditions, input data, steps, expected result, priority and traceability. | Must | B2 |
| FR-12 | The agent shall implement designed test cases as executable code stored in `.retro/tests/` and copied into each worktree before a run. | Must | B2, ADR-0015 |
| FR-13 | The agent shall maintain traceability between requirements and test cases. | Must | B2 |
| FR-36 | The agent shall rewrite the code of a generated test and retire a test case, keeping their history. | Should | ADR-0023 |

### Selection

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-14 | The agent shall select and prioritize the regression suite for a change and justify the inclusion of each test case. | Must | B1, B2 |

### Execution

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-15 | The agent shall execute test suites against the baseline and the candidate in isolated worktrees. | Must | B3, ADR-0009 |
| FR-16 | The agent shall record for each run: `run_id`, version, commit, command, start and end time, duration, exit code, JUnit XML and logs. | Must | B3 |
| FR-17 | The agent shall record test executions, with their status and result, only from parsed run evidence. | Must | B5, ADR-0006, ADR-0010, ADR-0016 |
| FR-18 | The agent shall rerun failed test cases a configurable number of times to detect flaky tests. Reruns shall never change the result of the execution. | Should | B3, ADR-0022 |
| FR-19 | The agent shall record test executions as `blocked` when the environment prevents them from running. | Must | B5, ADR-0016 |

### Interpretation

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-20 | The agent shall compare a candidate run with the baseline run and identify new failures, fixed tests and persistent failures. | Must | B4 |
| FR-21 | The agent shall classify each failed test execution as `regression`, `expected_change`, `flaky`, `environment`, `test_defect` or `pre_existing`, with a justification. Classifications that depend on recorded facts shall be validated by code. | Must | B4, ADR-0022 |
| FR-22 | The agent shall register defects with severity and link them to test cases and runs. Defects shall be closed only by a run that verifies the fix or by the user. | Must | B4, ADR-0022 |
| FR-34 | The agent shall measure the quality of its test selection (inclusiveness and precision) when full runs of both versions exist. | Should | B4, ADR-0017 |

### Memory

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-23 | The agent shall persist requirements, test cases, runs, test executions, triage, defects and risks across sessions. | Must | ADR-0008 |
| FR-24 | The agent shall answer queries about project history: previous runs, flaky history and open defects. | Should | ADR-0008 |

### Reporting

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-25 | The agent shall generate the test completion report and the test case specification. | Must | B2, B4 |
| FR-37 | The agent shall generate the test plan, the test status report and the defect report. | Should | B4 |
| FR-26 | The agent shall compute metrics, evaluate exit criteria and produce the release decision deterministically. | Must | B4, ADR-0006 |
| FR-35 | The release decision shall be `do_not_release` when test cases that passed against the baseline fail against the candidate without a documented reason, or when no baseline run exists to compare with. | Must | B4, ADR-0022 |
| FR-27 | Reports shall separate computed sections from sections written by the model, and mark the latter. | Must | B5, ADR-0006 |
| FR-28 | Reports shall include charts of results: outcome distribution and comparison against the baseline. | Must | B4 |
| FR-38 | Reports shall include a chart of the exit criteria against their thresholds. | Should | B4 |
| FR-29 | The agent shall export reports to Markdown and to PDF. The PDF libraries are part of the default installation; when the system library they need is missing, the Markdown is still produced and the error says what to install. | Must | B4, ADR-0018 |
| FR-30 | The agent shall display summaries of runs and results as tables in the terminal. | Must | B4 |

### Extensibility

| ID | Requirement | Priority | Source |
|---|---|---|---|
| FR-31 | The agent shall load project-level and user-level steering and skills in addition to the bundled ones. | Could | ADR-0005 |
| FR-32 | The agent shall connect to additional MCP servers declared in `.retro/mcp.json`. | Could | ADR-0004 |
| FR-33 | The agent shall create bundled example projects in a given directory, with their git history and version tags. | Must | ADR-0001 |

## Non-functional requirements

| ID | Category | Requirement | Priority | Source |
|---|---|---|---|---|
| NFR-01 | Model independence | The agent shall work with at least one local provider (`ollama`) and one hosted provider, using native tool calling; switching between them shall require only configuration. | Must | ADR-0003, ADR-0026 |
| NFR-17 | Model coverage | The agent shall support the remaining providers of `llm-providers.md`, and the JSON fallback mode for models without tool calling. | Should | ADR-0003 |
| NFR-02 | Result integrity | A test execution result shall be impossible to store unless the execution status is `executed` and it belongs to a run with stored evidence. Enforced in the data layer. | Must | B5, ADR-0016 |
| NFR-03 | Determinism | The same stored data shall always produce the same metrics, exit criteria evaluation and release decision. | Must | ADR-0006 |
| NFR-04 | Auditability | Every figure in a report shall be traceable to stored runs and evidence. Every tool call shall be recorded with its inputs, outcome and timestamp. | Must | B3, ADR-0006 |
| NFR-05 | Safety | The agent shall never modify the user's working copy. Inside the project, the agent writes only under `.retro/`, `RETRO.md` when the user runs `retro init`, and the worktree metadata git keeps in `.git/worktrees/`, which is removed after each run. Tests run only inside worktrees, which are created outside the project tree. | Must | ADR-0009, ADR-0015, ADR-0024 |
| NFR-06 | Secrets | API keys shall be read only from environment variables and never written to files, logs or reports. | Must | — |
| NFR-07 | Robustness | Model errors, tool failures and interruptions shall not corrupt stored data. The agent loop shall stop after a configurable maximum number of iterations. The context of a call shall stay within the context window of the model without dropping steering, and a server that drops part of it shall be detected. | Must | ADR-0026, ADR-0027, ADR-0028 |
| NFR-08 | Usability | The CLI shall follow the conventions of terminal agents and provide help for every command. | Must | ADR-0011 |
| NFR-09 | Extensibility | New providers, MCP servers, steering files and skills shall be addable without modifying the runtime core. | Should | ADR-0003, ADR-0004, ADR-0005 |
| NFR-10 | Offline operation | The agent shall run without internet access when using a local model. | Should | ADR-0026 |
| NFR-11 | Portability | The agent shall run on Linux, macOS and Windows with Python 3.11 or later. | Should | — |
| NFR-12 | Testability | Metrics, exit criteria evaluation and the release decision shall be fully covered by unit tests. | Must | ADR-0006 |
| NFR-13 | Language | All project content shall be in English. The language of responses and of the agent sections of reports shall be configurable. | Must | ADR-0012 |
| NFR-18 | Translated templates | Report templates shall be available in languages other than English. | Should | ADR-0018 |
| NFR-14 | Untrusted configuration | The configuration of a target project shall not define model providers, loosen permissions, or enable MCP servers, steering or skills without user approval. | Must | ADR-0014, ADR-0021 |
| NFR-15 | Command approval | Commands defined by the target project shall run only after the user approved their exact content. | Must | ADR-0024 |
| NFR-16 | Credential isolation | Processes started by the agent (setup, tests, services and MCP servers) shall not receive model credentials. | Must | ADR-0024 |

## Out of scope

- User interface and browser testing.
- Performance, load and security testing.
- Projects that are not git repositories or cannot produce JUnit XML.
- Modifying or fixing the code of the target project.
- Concurrent sessions on the same target project.
- Graphical user interface for RetroAgent.
