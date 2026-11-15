# Glossary

Single vocabulary for code, database, CLI, steering, skills, templates and documentation. Use these terms exactly; do not introduce synonyms.

## Product

| Term | Definition |
|---|---|
| RetroAgent | The product. Repository and Python package `retroagent`. |
| `retro` | The CLI command. |
| `RETRO.md` | Project context file at the root of a target project. Created by `/init`. |
| `.retro/` | Project-level folder: configuration, extensions, generated tests, memory, runs, reports, worktrees. |
| `~/.retro/` | User-level folder: model configuration and global extensions. |

## Agent architecture

| Term | Definition |
|---|---|
| Runtime | The agent loop: builds the context, calls the model, dispatches tools and repeats until the task is done. |
| LLM provider | Adapter that connects the runtime to one model vendor through the common `LLMProvider` interface. |
| Model profile | Named model configuration at user level: provider, model name, endpoint and API key variable. |
| Steering | Markdown rules always injected into the context, in file-name order. |
| Skill | Markdown procedure (`SKILL.md`) loaded on demand. Only its name and description are always visible. |
| MCP server | Process that exposes tools through the Model Context Protocol. |
| Tool | A single callable operation exposed by an MCP server or by the runtime. |
| Session | One interactive or non-interactive execution of `retro`. |
| System context | Instructions and information sent to the model on every call: steering, session block, project context and skills index. |
| Turn | One user message and every model call and tool call that follows, until the model answers without tool calls. |
| Slash command | Command typed in a session, such as `/run`. Direct commands run without the model; model commands become a message to the model. |
| Plan mode | Mode in which the agent analyzes and designs but cannot execute tests. |
| JSON fallback mode | Mode for models without tool calling: tools are described in the system context and the model answers with JSON that the runtime validates. |
| Permission | User approval required before running tests, starting a service or writing test code. |

## Testing domain

| Term | Definition |
|---|---|
| Target project | The project RetroAgent analyzes. Also called system under test (SUT). |
| Baseline | Reference version (e.g. `v1.0`) whose behavior is considered correct. |
| Candidate | Version under evaluation (e.g. `v1.1`). |
| Change set | Differences between baseline and candidate: files and hunks. |
| Impact analysis | Mapping the change set to modules, requirements and risk. |
| Requirement | Documented, testable statement of expected behavior of the target project. |
| Test case | Specification of one test: objective, preconditions, input data, steps, expected result, priority and traceability. |
| Generated test | Test code written by RetroAgent, stored in `.retro/tests/` and copied into each worktree before a run. |
| Test suite | Set of test cases selected for a run. |
| Current suite | The test suite selected for the latest impact analysis of the session versions. |
| Regression suite | Test cases that protect existing behavior. |
| Traceability | Links between requirements and test cases. |
| Run | One execution of a test suite against one version, with stored evidence. |
| Full run | Run of every implemented test case against one version (`/run all`). |
| Revealing test case | Test case whose verdict differs between full runs of the baseline and the candidate. |
| Evaluated run | Run against the candidate for which metrics, exit criteria and the release decision are computed. |
| Evaluation | Stored computation of the metrics, exit criteria and release decision of an evaluated run, with its inputs. |
| Test execution | Outcome of one test case in one run: an execution status and, when executed, a result. |
| Attempt | One try of a test execution. Failed executions are retried to detect flaky tests; the result is the one of the last attempt. |
| Evidence | Artifacts proving a run happened: exit code, JUnit XML, logs and timestamps. |
| Worktree | Temporary git checkout of a version under `.retro/worktrees/`. The user's working copy is never modified. |
| Triage | Classification of a failed test execution. |
| Defect | Confirmed deviation from expected behavior, registered with a severity. |
| Risk | Possible negative outcome for the product that testing did not fully rule out. |
| Exit criteria | Conditions that must hold to finish testing. Evaluated by code. |
| Release decision | Recommendation computed from the exit criteria. Explained, never decided, by the model. |
| Agent section | Part of a report written by the model, always marked with the model that wrote it. |
| Item template | Template rendered once per element of a report, such as a test case or a defect. |

## Identifiers

| Entity | Format | Scope |
|---|---|---|
| Requirement | `REQ-001` | Target project |
| Test case | `TC-001` | Target project |
| Run | `RUN-0001` | Target project |
| Defect | `DEF-001` | Target project |
| Risk | `RSK-001` | Target project |
| Report | `RPT-0001` | Target project |
| Functional requirement | `FR-01` | RetroAgent |
| Non-functional requirement | `NFR-01` | RetroAgent |
| Acceptance scenario | `SC-01` | RetroAgent |
| Exit criterion | `EC-01` | RetroAgent |
| Data invariant | `INV-01` | RetroAgent |
| Architecture decision record | `ADR-0001` | RetroAgent |

## Enumerations

### Test case `status`

Life cycle of a test case, independent of any run.

| Value | Meaning |
|---|---|
| `designed` | Specified; no executable code yet. |
| `implemented` | Executable test code exists. |

### Test case `origin`

| Value | Meaning |
|---|---|
| `designed` | Designed by the agent. |
| `project_suite` | Found in the test suite of the target project. |

### Version `role`

| Value | Meaning |
|---|---|
| `base` | The baseline version. |
| `candidate` | The candidate version. |

### Test execution `status`

Outcome of a test case in one run.

| Value | Meaning |
|---|---|
| `executed` | Ran, with its outcome in the run evidence. |
| `blocked` | Could not run because of the environment or a missing dependency. |
| `skipped` | Reported as skipped by the test framework, or deliberately excluded. |

### Test execution `result`

Only exists when the execution `status` is `executed`.

| Value | Meaning |
|---|---|
| `passed` | All assertions held. |
| `failed` | At least one assertion did not hold. |
| `error` | The test could not complete (exception, setup failure). |

### Run `status`

| Value | Meaning |
|---|---|
| `running` | The run has started and has not finished. |
| `completed` | The test command finished and its results were recorded. |
| `error` | A step failed before results could be recorded; its executions are `blocked`. |
| `interrupted` | The run was stopped by the user or by a timeout. |

### Run `scope`

| Value | Meaning |
|---|---|
| `suite` | The test cases of a suite. |
| `all` | Every implemented test case: a full run. |
| `selected` | Test cases chosen by ID. |

### Triage `classification`

| Value | Meaning |
|---|---|
| `regression` | The product does not behave as required. Usually behavior broken by the change; a failure already present in the baseline is also classified here and shows as a persistent failure in the comparison. |
| `expected_change` | Behavior changed because a requirement changed; the test must be updated. |
| `flaky` | Non-deterministic result across reruns. |
| `environment` | Failure caused by infrastructure, not by the product. |
| `test_defect` | The test itself is wrong. |

### Defect `severity`

`critical`, `high`, `medium`, `low`.

### Defect `status`

| Value | Meaning |
|---|---|
| `open` | The defect is present and counts against the exit criteria. |
| `closed` | The defect is fixed or no longer applies. |

### Test case `priority`

`high`, `medium`, `low`.

### Risk `level`

`high`, `medium`, `low`. Assigned to impacted areas and to registered risks.

### Release `decision`

Computed by the rule in `metrics.md`.

| Value | Meaning |
|---|---|
| `release` | All exit criteria are met, no failure is excused and no planned test case is left designed only. |
| `release_with_conditions` | No blocking criterion fails, but there are conditions: a non-blocking criterion not met or not evaluable, excused failures, or test cases designed only. |
| `do_not_release` | At least one blocking criterion is not met or not evaluable. |

### Exit criterion `state`

| Value | Meaning |
|---|---|
| `met` | The condition holds. |
| `not_met` | The condition does not hold. |
| `not_evaluable` | A metric the criterion depends on cannot be computed. |

### Permission `mode`

| Value | Meaning |
|---|---|
| `default` | Ask before running tests, starting services or writing test code. |
| `plan` | Analyze and design only; no execution. |
| `auto` | Perform allowed actions without asking; refuse the rest. |

## Reports

Names follow ISO/IEC/IEEE 29119-3.

| Report | Template |
|---|---|
| Test plan | `templates/test-plan.md` |
| Test case specification | `templates/test-case-specification.md` |
| Test status report | `templates/test-status-report.md` |
| Defect report | `templates/defect-report.md` |
| Test completion report | `templates/test-completion-report.md` |
