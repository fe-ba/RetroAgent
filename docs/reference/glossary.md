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
| Plan mode | Mode in which the agent analyzes and designs but cannot execute tests. |
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
| Regression suite | Test cases that protect existing behavior. |
| Traceability | Links between requirements and test cases. |
| Run | One execution of a test suite against one version, with stored evidence. |
| Full run | Run of every implemented test case against one version (`/run all`). |
| Revealing test case | Test case whose verdict differs between full runs of the baseline and the candidate. |
| Test execution | Outcome of one test case in one run: an execution status and, when executed, a result. |
| Attempt | One try of a test execution. Failed executions are retried to detect flaky tests; the result is the one of the last attempt. |
| Evidence | Artifacts proving a run happened: exit code, JUnit XML, logs and timestamps. |
| Worktree | Temporary git checkout of a version under `.retro/worktrees/`. The user's working copy is never modified. |
| Triage | Classification of a failed test execution. |
| Defect | Confirmed deviation from expected behavior, registered with a severity. |
| Risk | Possible negative outcome for the product that testing did not fully rule out. |
| Exit criteria | Conditions that must hold to finish testing. Evaluated by code. |
| Release decision | Recommendation computed from the exit criteria. Explained, never decided, by the model. |

## Identifiers

| Entity | Format | Scope |
|---|---|---|
| Requirement | `REQ-001` | Target project |
| Test case | `TC-001` | Target project |
| Run | `RUN-0001` | Target project |
| Defect | `DEF-001` | Target project |
| Risk | `RSK-001` | Target project |
| Functional requirement | `FR-01` | RetroAgent |
| Non-functional requirement | `NFR-01` | RetroAgent |
| Acceptance scenario | `SC-01` | RetroAgent |
| Exit criterion | `EC-01` | RetroAgent |
| Architecture decision record | `ADR-0001` | RetroAgent |

## Enumerations

### Test case `status`

Life cycle of a test case, independent of any run.

| Value | Meaning |
|---|---|
| `designed` | Specified; no executable code yet. |
| `implemented` | Executable test code exists. |

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

### Triage `classification`

| Value | Meaning |
|---|---|
| `regression` | Previously working behavior broken by the change. |
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

### Release `decision`

| Value | Meaning |
|---|---|
| `release` | All exit criteria met. |
| `release_with_conditions` | Only non-blocking criteria failed; conditions are listed. |
| `do_not_release` | At least one blocking criterion failed. |

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
