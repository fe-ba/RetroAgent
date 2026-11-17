# MCP tools reference

Every tool the model can call: the tools of the four bundled MCP servers (ADR-0004) and the tools provided by the runtime. For each tool: inputs, output, the tables it writes (`spec/data-model.md`), the permission it needs and whether it is allowed in plan mode.

## Conventions

| Topic | Rule |
|---|---|
| Naming | Documented as `<server>.<tool>`. Exposed to the model as `<server>__<tool>`, because some providers do not accept dots in tool names. |
| Session context | Each bundled server is started by the runtime for one project and one session. The session versions and the model name are read from the `session` record, which only the runtime writes. The model never provides them. |
| Internal servers | The bundled servers are components of RetroAgent, not a public integration: they need a session created by the runtime, which also enforces modes, permissions and approvals. Using them from another MCP client is not supported (ADR-0026). |
| Identifiers | Tools that create records return their new identifiers. No tool accepts an identifier for a record it creates. |
| References | Every identifier, path or ref given by the model must exist; otherwise the call fails with `not_found` and nothing is written (INV-13). |
| Execution results | No tool that writes accepts an execution status or result as input (INV-03); read tools may filter by them. Arguments are validated against the schema of the tool, which accepts no other property: an unknown argument is an `invalid_argument`. |
| Large output | Tools that return file content, diffs or evidence return at most the result limit of the session, cut at a line boundary. The limit is 20,000 characters, or less with a small context window (`context-loading.md`); tools read it from the `session` record. When they cut, they set `truncated` to `true` and return `next_line`; calling the tool again with `start_line` set to that value returns what follows. |
| Models | No MCP tool calls a model (ADR-0020). Text written by the model reaches the servers only as tool arguments. |
| Mode, permissions and approvals | Enforced by the runtime before dispatch, including the approval of the project commands before `test_runner.run_tests` (`configuration.md`). A refused call is recorded with outcome `denied`. |
| Descriptions | A tool description has at most 300 characters and a parameter description at most 150. Every definition is sent with every call, so their size is part of the fixed context. |
| User-only tools | A tool marked user only is called only by the runtime, for a direct command of the user. It is not in the tool definitions, and a call from the model is refused with `denied`. |

### Errors

Every error returns a code and a message.

| Code | Meaning |
|---|---|
| `invalid_argument` | An argument has the wrong type or value. |
| `not_found` | A referenced record, file or ref does not exist. |
| `invalid_state` | The operation is not possible in the current state, for example designing before a suite exists. |
| `denied` | The mode, a permission or a missing approval of the project commands does not allow the call. Returned by the runtime. |
| `deferred` | The results of the same model message already fill their share of the context. The call was not executed: call it again in the next step. Returned by the runtime. |
| `execution_failed` | An external process failed: git, the setup, the test command or the service. |
| `unavailable` | A dependency is missing, for example the PDF libraries, or a server stopped or did not answer in time. |

## Summary

| Tool | Access | Permission | Plan mode | Writes |
|---|---|---|---|---|
| `runtime.load_skill` | read | — | allowed | — |
| `runtime.set_versions` | write | — | allowed | `session` |
| `git.resolve_ref` | read | — | allowed | — |
| `git.analyze_changes` | write | — | allowed | `analysis`, `analysis_file` |
| `git.get_diff` | read | — | allowed | — |
| `git.read_file` | read | — | allowed | — |
| `git.list_files` | read | — | allowed | — |
| `memory.sync_requirements` | write | — | allowed | `requirement`, `requirement_change`, `test_case_requirement` |
| `memory.get_requirements` | read | — | allowed | — |
| `memory.get_analysis` | read | — | allowed | — |
| `memory.save_impact` | write | — | allowed | `analysis_module`, `analysis_requirement`, `analysis_requirement_not_impacted` |
| `memory.add_risk` | write | — | allowed | `risk`, `risk_requirement` |
| `memory.get_risks` | read | — | allowed | — |
| `memory.save_suite` | write | — | allowed | `suite`, `suite_test_case` |
| `memory.get_suite` | read | — | allowed | — |
| `memory.design_test_case` | write | — | allowed | `test_case`, `test_case_requirement`, `suite_test_case` |
| `memory.update_test_case` | write | — | allowed | `test_case`, `test_case_requirement` |
| `memory.retire_test_case` | write | — | allowed | `test_case` |
| `memory.get_test_cases` | read | — | allowed | — |
| `memory.get_runs` | read | — | allowed | — |
| `memory.get_executions` | read | — | allowed | — |
| `memory.get_test_case_history` | read | — | allowed | — |
| `memory.save_triage` | write | — | allowed | `triage` |
| `memory.register_defect` | write | — | allowed | `defect`, `defect_execution` |
| `memory.link_defect` | write | — | allowed | `defect_execution` |
| `memory.close_defect` | write, user only | — | allowed | `defect` |
| `memory.get_defects` | read | — | allowed | — |
| `test_runner.write_test` | write | `write_tests` | refused | `test_case`, `test_case_requirement` |
| `test_runner.run_tests` | write | `run_tests`, and `start_service` when a service is configured | refused | `run`, `test_execution`, `attempt`, `test_case`, `test_case_requirement`, `defect` |
| `test_runner.get_evidence` | read | — | allowed | — |
| `reports.evaluate` | write | — | allowed | `evaluation` |
| `reports.prepare_report` | write | — | allowed | `evaluation`, `report` |
| `reports.render_report` | write | — | allowed | `report` |
| `reports.get_report` | read | — | allowed | — |

`schema_info` and `tool_call` are written by the runtime and the data layer, never through a tool. `session` is written only by the runtime, which includes its own tool `runtime.set_versions`.

## Runtime tools

Provided by the runtime itself, not by an MCP server.

### `runtime.load_skill`

Loads the full instructions of a skill into the context (ADR-0005).

| Input | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Skill name, as listed in the context. |

Returns the content of the `SKILL.md`, without its frontmatter. Errors: `not_found`.

### `runtime.set_versions`

Sets the session versions used by every other tool.

| Input | Type | Required | Description |
|---|---|---|---|
| `base` | string | yes | Baseline ref. |
| `candidate` | string | yes | Candidate ref. |

Returns both refs with their commits. Errors: `not_found` when a ref does not resolve.

## Server `git`

Reads the repository of the target project. It never modifies the working copy (ADR-0009).

### `git.resolve_ref`

| Input | Type | Required | Description |
|---|---|---|---|
| `ref` | string | yes | Tag, branch or commit. |

Returns the full commit hash and the kind of ref. Errors: `not_found`.

### `git.analyze_changes`

Computes the change set between the session versions and creates an analysis.

No inputs. Returns the analysis ID and every changed file with its change and line counts. Errors: `invalid_state` when the session has no versions.

### `git.get_diff`

| Input | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | A file of the change set. |
| `analysis_id` | integer | no | Default: the latest analysis of the session versions. |
| `start_line` | integer | no | First line to return. Default: 1. See Large output. |

Returns the unified diff of the file. Errors: `not_found` when the file is not in the change set.

### `git.read_file`

| Input | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | Path in the repository. |
| `version` | string | yes | `base` or `candidate`. |
| `start_line` | integer | no | First line to return. Default: 1. See Large output. |

Returns the content of the file at that version. Errors: `not_found`.

### `git.list_files`

| Input | Type | Required | Description |
|---|---|---|---|
| `version` | string | yes | `base` or `candidate`. |
| `path` | string | no | Directory to list. Default: the repository root. |

Returns the files and directories under `path`. Errors: `not_found`.

## Server `memory`

Long-term memory of the target project (ADR-0008).

### `memory.sync_requirements`

Reads the requirement documents of the candidate version, in the format of `project-contract.md`.

No inputs. Returns the number of requirements read, added and changed, the files that could not be parsed, and the `Changed` or `Removed` entries whose version does not resolve to a git ref. Errors: `invalid_state` when `project.requirements` is not configured.

### `memory.get_requirements`

| Input | Type | Required | Description |
|---|---|---|---|
| `ids` | list of strings | no | Requirement IDs. Default: all. |

Returns each requirement with its fields and its changes.

### `memory.get_analysis`

| Input | Type | Required | Description |
|---|---|---|---|
| `analysis_id` | integer | no | Default: the latest analysis of the session versions. |

Returns the change set, the impacted modules, the impacted requirements and the requirements judged not impacted, each with its reason. Errors: `not_found`.

### `memory.save_impact`

Records the impact analysis proposed by the model for an analysis.

| Input | Type | Required | Description |
|---|---|---|---|
| `analysis_id` | integer | yes | — |
| `modules` | list | yes | Each: `module`, `files` (from the change set), `risk_level`, `reason`. |
| `requirements` | list | yes | Impacted requirements. Each: `requirement_id`, `reason`. May be empty. |
| `not_impacted` | list | yes | Requirements judged not impacted. Each: `requirement_id`, `reason`. May be empty. |

Every requirement in effect at the candidate must be decided: it appears exactly once, in `requirements` or in `not_impacted`. A requirement is in effect when it has no `removed` version, or when its removal applies to the change of the analysis, by the same rule as a `Changed` entry (`project-contract.md`). A project without requirements sends two empty lists. The decision is checked by code, so that a requirement is never left out in silence.

Returns the number of modules, impacted requirements and requirements judged not impacted. The impact of an analysis is recorded once. Errors: `not_found` for an unknown file or requirement; `invalid_argument` when a requirement in effect is missing, naming every one, or appears more than once; `invalid_state` when the analysis already has an impact: a corrected impact needs a new analysis from `git.analyze_changes`.

### `memory.add_risk`

| Input | Type | Required | Description |
|---|---|---|---|
| `description` | string | yes | — |
| `level` | string | yes | `high`, `medium` or `low`. |
| `requirement_ids` | list of strings | no | Related requirements. |

Returns the new `RSK` ID, linked to the latest analysis of the session versions.

### `memory.get_risks`

No inputs. Returns every registered risk with its level and requirements.

### `memory.save_suite`

Creates a new suite for an analysis. It becomes the current suite.

| Input | Type | Required | Description |
|---|---|---|---|
| `analysis_id` | integer | yes | — |
| `items` | list | yes | Each: `test_case_id`, `position`, `selection_reason`. May be empty when no existing test case relates to the change; test cases designed later are added to it. |

Returns the suite ID. `position` orders the presentation of the suite; the test framework decides the execution order. Errors: `not_found` for an unknown test case; `invalid_argument` for duplicated test cases or positions, or for a retired test case.

### `memory.get_suite`

| Input | Type | Required | Description |
|---|---|---|---|
| `suite_id` | integer | no | Default: the current suite. |

Returns the suite with each test case, its position and its selection reason.

### `memory.design_test_case`

Creates a test case with status `designed` and adds it to the current suite.

| Input | Type | Required | Description |
|---|---|---|---|
| `title` | string | yes | — |
| `objective` | string | yes | — |
| `priority` | string | yes | `high`, `medium` or `low`. |
| `preconditions` | list of strings | yes | May be empty. |
| `input_data` | list | yes | Each: `name`, `value`. May be empty. |
| `steps` | list of strings | yes | At least one step. |
| `expected_result` | string | yes | — |
| `requirement_ids` | list of strings | yes | Traced requirements. May be empty when the project has none. |
| `selection_reason` | string | yes | Why it belongs to the suite. |

Returns the new `TC` ID. Errors: `invalid_state` when there is no current suite.

### `memory.update_test_case`

Updates the description of a test case.

| Input | Type | Required | Description |
|---|---|---|---|
| `test_case_id` | string | yes | — |
| `fields` | object | yes | Any of the design fields of `design_test_case`, except `selection_reason`, within the limits below. `requirement_ids` replaces the `design` links of the test case; links found in the test name are kept. |

| Test case | Fields that can change |
|---|---|
| `designed` | Every design field. |
| `implemented`, origin `designed` | `title`, `objective` and `priority`. The other fields describe what the code does; they change only together with the code, through `test_runner.write_test`. |
| Origin `project_suite` | Every design field. The code belongs to the project; the description documents it. |

Errors: `invalid_state` for a field that cannot change, or for a retired test case.

### `memory.retire_test_case`

Takes a test case out of use: an obsolete test, a generated test that cannot be repaired, or one whose requirement was removed. Its records and history are kept (INV-11).

| Input | Type | Required | Description |
|---|---|---|---|
| `test_case_id` | string | yes | An active test case. |
| `reason` | string | yes | — |

A retired test case cannot be added to a suite, and its generated test is no longer copied into worktrees. A project test that the test command still runs keeps producing executions. Retiring is permanent. Errors: `invalid_state` when it is already retired.

### `memory.get_test_cases`

| Input | Type | Required | Description |
|---|---|---|---|
| `ids` | list of strings | no | Default: all. |
| `status` | string | no | `designed` or `implemented`. |
| `requirement_id` | string | no | Only test cases traced to it. |
| `include_code` | boolean | no | Also return the code of generated tests, from `.retro/tests/`. Default: false. |
| `include_retired` | boolean | no | Also return retired test cases. Default: false. |

Returns each test case with its fields and requirements.

### `memory.get_runs`

| Input | Type | Required | Description |
|---|---|---|---|
| `limit` | integer | no | Default: 10. |
| `version_role` | string | no | `base` or `candidate`. |

Returns the latest runs with their status, scope, version and counts of execution statuses and results.

### `memory.get_executions`

| Input | Type | Required | Description |
|---|---|---|---|
| `run_id` | string | yes | — |
| `result` | string | no | Only executions with this result. |
| `untriaged` | boolean | no | Only failed or error executions without triage. |

Returns each execution with its test case, status, result, attempts and triage.

### `memory.get_test_case_history`

| Input | Type | Required | Description |
|---|---|---|---|
| `test_case_id` | string | yes | — |

Returns every execution of the test case, oldest first, with run, version, status, result and whether it was flaky.

### `memory.save_triage`

| Input | Type | Required | Description |
|---|---|---|---|
| `execution_id` | integer | yes | An execution with result `failed` or `error`. |
| `classification` | string | yes | `regression`, `expected_change`, `flaky`, `environment`, `test_defect` or `pre_existing`. |
| `justification` | string | yes | — |
| `replace` | boolean | no | Triage again an execution that already has a triage. Default: false. |

With `replace`, a new triage is added and becomes the current one; the earlier ones are kept and the execution is listed for review.

Three classifications are accepted only when code finds their evidence (INV-15):

| Classification | Evidence required |
|---|---|
| `expected_change` | The execution belongs to a run against the candidate, and a requirement traced to the test case has a `Changed` or `Removed` entry that applies to the change between the session versions (`project-contract.md`). |
| `flaky` | At least one rerun of the execution passed, or an earlier execution of the same test case against the same commit has a different verdict (`passed` against `failed` or `error`; see `metrics.md`). |
| `pre_existing` | The execution belongs to a run against the candidate, and the latest completed run on the baseline commit of the session versions that executed the test case has it with result `failed` or `error`. |

`regression`, `environment` and `test_defect` are judgments of the model and are not validated.

Errors: `invalid_state` when the execution did not fail, is already triaged and `replace` is not `true`, or lacks the evidence its classification requires; the message names the missing evidence.

### `memory.register_defect`

| Input | Type | Required | Description |
|---|---|---|---|
| `title` | string | yes | — |
| `severity` | string | yes | `critical`, `high`, `medium` or `low`. |
| `execution_ids` | list of integers | yes | Failed or error executions; at least one. |
| `steps` | list of strings | yes | Steps to reproduce. |

Returns the new `DEF` ID. The expected and actual results are taken by code from the first execution.

### `memory.link_defect`

Links more executions to an open defect, when the same failure appears in a later run.

| Input | Type | Required | Description |
|---|---|---|---|
| `defect_id` | string | yes | An open defect. |
| `execution_ids` | list of integers | yes | Failed or error executions; at least one. |

Errors: `invalid_state` when the defect is closed or an execution is already linked to it.

### `memory.close_defect`

User only. Closes a defect by decision of the user: `/defects close` and `retro defects close` (`cli.md`). The model cannot call it (INV-14); defects are otherwise closed by `test_runner.run_tests`.

| Input | Type | Required | Description |
|---|---|---|---|
| `defect_id` | string | yes | An open defect. |
| `reason` | string | yes | Typed by the user. |

Records `closed_by` `user`. Errors: `invalid_state` when the defect is already closed.

### `memory.get_defects`

| Input | Type | Required | Description |
|---|---|---|---|
| `status` | string | no | `open` or `closed`. Default: both. |

Returns each defect with its linked executions.

## Server `test_runner`

Writes test code and executes tests (ADR-0009, ADR-0010, ADR-0015).

### `test_runner.write_test`

Writes the code of a generated test to `.retro/tests/`. For a `designed` test case, it sets it to `implemented` with revision `1`. For a test case of origin `designed` that is already `implemented`, it rewrites the code and increments the revision.

| Input | Type | Required | Description |
|---|---|---|---|
| `test_case_id` | string | yes | An active test case of origin `designed`. |
| `file` | string | yes | Path relative to `.retro/tests/`. |
| `test_name` | string | yes | Name of the test function; must follow `test_req_<NNN>_<description>` when the test case traces a requirement. |
| `code` | string | yes | Full content of the file. |
| `fields` | object | no | Only in a rewrite: design fields that change with the code (`preconditions`, `input_data`, `steps`, `expected_result`, `requirement_ids`). |

Returns the implementation reference `<file>::<test name>` and the revision. The `test_id` is set when a run first reports the test. A rewrite keeps `file` and `test_name`, and writes the code and the design fields in one transaction. Errors: `invalid_state` for a `project_suite` or retired test case; `invalid_argument` when the path leaves `.retro/tests/`, when the file or the test name is used by another generated test, or when a rewrite changes them (INV-17).

### `test_runner.run_tests`

Creates a run against one session version and executes it, following `project-contract.md`.

| Input | Type | Required | Description |
|---|---|---|---|
| `version` | string | yes | `base` or `candidate`. |
| `scope` | string | yes | `suite`, `all` or `selected`. |
| `test_case_ids` | list of strings | when `selected` | Implemented, active test cases. |

| Scope | What runs | Executions created |
|---|---|---|
| `all` | `tests.command` as configured: every test of the project and every generated test of an active test case. It needs no known test case, so it is also how the project suite is discovered. | One for each test the JUnit XML reports. A generated test it does not report gets `blocked` with reason `not_reported`. When the run ends before any valid JUnit XML exists (failed setup, service not ready, no JUnit XML, timeout or interruption), every active implemented test case known to memory gets one `blocked` execution with that reason; on a project whose tests were never discovered there is none, and the status and the error of the run tell what happened. |
| `suite`, `selected` | The implemented, active test cases of the scope, through `tests.select` when it is configured. | One for each of them, `blocked` with reason `not_reported` when the JUnit XML has no result for it. Results of tests outside the scope are ignored. |

Returns the run ID, its status, the counts of execution statuses and results, and the defects closed by the run. In a run with scope `all`, tests of the project unknown to memory are registered as `project_suite` test cases, with requirement links from their names. Runs with other scopes register nothing.

**Attempts.** Each test case whose first attempt did not pass is rerun `tests.reruns` times. The reruns do not stop when one of them passes; they stop only when a rerun round itself fails (`project-contract.md`). The result of the execution is the result of the first attempt (INV-04). Reruns use `tests.select` with the test cases to rerun when it is configured; otherwise the test command runs again in full. Each attempt keeps its own JUnit XML in the run directory.

**Identity.** Tests are matched to test cases as described in `project-contract.md`, under Test identity.

**Closing defects.** When a run against the candidate completes, each open defect is closed if every test case linked to it has an execution in this run with result `passed`. The defect records `closed_by` `run`, the run and a generated reason. A flaky execution never closes a defect, because its result is not `passed`. Errors: `invalid_state` when the scope is `suite` or `selected` and has no implemented test cases, or when `tests.command` is not configured; `execution_failed` when the worktree of the version cannot be created, in which case no run is stored; a failed setup or service produces a run with status `error`, not a tool error.

### `test_runner.get_evidence`

| Input | Type | Required | Description |
|---|---|---|---|
| `run_id` | string | yes | — |
| `test_case_id` | string | no | Only the evidence of this test case. |
| `start_line` | integer | no | First line to return. Default: 1. See Large output. |

Returns the failure messages of each attempt and the relevant part of the run log.

## Server `reports`

Computes metrics and renders reports (ADR-0006, ADR-0018, ADR-0020).

### `reports.evaluate`

Computes metrics, exit criteria and the release decision, following `metrics.md`, and stores the evaluation.

| Input | Type | Required | Description |
|---|---|---|---|
| `run_id` | string | no | Evaluated run. Default: as defined in `metrics.md`. |

Returns the metrics, the state of each criterion and the decision. Errors: `invalid_state` when the run is not a completed run with scope `suite` against the candidate.

### `reports.prepare_report`

First step of report generation: computes everything, writes the computed sections and the charts to the folder of the report, and creates a `draft` report.

| Input | Type | Required | Description |
|---|---|---|---|
| `type` | string | yes | `test-plan`, `test-cases`, `status`, `defects` or `completion`. |
| `run_id` | string | no | For `status`, `defects` and `completion`. Defaults as in `reports.md`. |
| `formats` | list of strings | no | `md`, `pdf`. Default: `reports.default_format`. |

Returns the report ID, the computed data of the report and the agent sections to write, each with its purpose from `reports.md`. The computed data is the Markdown of the draft, with the markers of the agent sections still in place. Errors: `invalid_argument` when `run_id` is given for a type that does not use it.

### `reports.render_report`

Second step: adds the agent sections to the draft, writes the report files and sets the report to `rendered`. It computes nothing again. When PDF was requested and its libraries are missing, the report is still `rendered`, with `md` as its only format.

| Input | Type | Required | Description |
|---|---|---|---|
| `report_id` | string | yes | A `draft` report. |
| `sections` | object | yes | Text of each agent section, by the names listed by `reports.prepare_report`. Missing sections are rendered as `Not provided.`. |

Returns the paths of the produced files. Errors: `invalid_argument` for a section the report does not have; `invalid_state` when the report is already rendered; `unavailable` when PDF was requested and its libraries are missing (the Markdown is still produced).

### `reports.get_report`

| Input | Type | Required | Description |
|---|---|---|---|
| `report_id` | string | yes | — |

Returns the report status, type, files and evaluation.
