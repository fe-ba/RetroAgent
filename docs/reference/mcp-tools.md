# MCP tools reference

Every tool the model can call: the tools of the four bundled MCP servers (ADR-0004) and the tools provided by the runtime. For each tool: inputs, output, the tables it writes (`spec/data-model.md`), the permission it needs and whether it is allowed in plan mode.

## Conventions

| Topic | Rule |
|---|---|
| Naming | Documented as `<server>.<tool>`. Exposed to the model as `<server>__<tool>`, because some providers do not accept dots in tool names. |
| Session context | The project path, the session, the session versions and the model name are passed by the runtime with every call. The model never provides them. |
| Identifiers | Tools that create records return their new identifiers. No tool accepts an identifier for a record it creates. |
| References | Every identifier, path or ref given by the model must exist; otherwise the call fails with `not_found` and nothing is written (INV-13). |
| Execution results | No tool accepts an execution status or result as input (INV-03). |
| Large output | Tools that return file content, diffs or evidence return at most 20,000 characters and set `truncated` to `true` when they cut. |
| Models | No MCP tool calls a model (ADR-0020). Text written by the model reaches the servers only as tool arguments. |
| Mode and permissions | Enforced by the runtime before dispatch. A refused call is recorded with outcome `denied`. |

### Errors

Every error returns a code and a message.

| Code | Meaning |
|---|---|
| `invalid_argument` | An argument has the wrong type or value. |
| `not_found` | A referenced record, file or ref does not exist. |
| `invalid_state` | The operation is not possible in the current state, for example designing before a suite exists. |
| `denied` | The mode or a permission does not allow the call. Returned by the runtime. |
| `execution_failed` | An external process failed: git, the setup, the test command or the service. |
| `unavailable` | A dependency is missing, for example the PDF libraries. |

## Summary

| Tool | Access | Permission | Plan mode | Writes |
|---|---|---|---|---|
| `runtime.load_skill` | read | — | allowed | — |
| `runtime.set_versions` | write | — | allowed | — |
| `git.resolve_ref` | read | — | allowed | — |
| `git.analyze_changes` | write | — | allowed | `analysis`, `analysis_file` |
| `git.get_diff` | read | — | allowed | — |
| `git.read_file` | read | — | allowed | — |
| `git.list_files` | read | — | allowed | — |
| `memory.sync_requirements` | write | — | allowed | `requirement`, `requirement_change` |
| `memory.get_requirements` | read | — | allowed | — |
| `memory.get_analysis` | read | — | allowed | — |
| `memory.save_impact` | write | — | allowed | `analysis_module`, `analysis_requirement` |
| `memory.add_risk` | write | — | allowed | `risk`, `risk_requirement` |
| `memory.get_risks` | read | — | allowed | — |
| `memory.save_suite` | write | — | allowed | `suite`, `suite_test_case` |
| `memory.get_suite` | read | — | allowed | — |
| `memory.design_test_case` | write | — | allowed | `test_case`, `test_case_requirement`, `suite_test_case` |
| `memory.update_test_case` | write | — | allowed | `test_case`, `test_case_requirement` |
| `memory.get_test_cases` | read | — | allowed | — |
| `memory.get_runs` | read | — | allowed | — |
| `memory.get_executions` | read | — | allowed | — |
| `memory.get_test_case_history` | read | — | allowed | — |
| `memory.save_triage` | write | — | allowed | `triage` |
| `memory.register_defect` | write | — | allowed | `defect`, `defect_execution` |
| `memory.link_defect` | write | — | allowed | `defect_execution` |
| `memory.close_defect` | write | — | allowed | `defect` |
| `memory.get_defects` | read | — | allowed | — |
| `test_runner.write_test` | write | `write_tests` | refused | `test_case` |
| `test_runner.run_tests` | write | `run_tests`, and `start_service` when a service is configured | refused | `run`, `test_execution`, `attempt`, `test_case`, `test_case_requirement` |
| `test_runner.get_evidence` | read | — | allowed | — |
| `reports.evaluate` | write | — | allowed | `evaluation` |
| `reports.prepare_report` | write | — | allowed | `evaluation`, `report` |
| `reports.render_report` | write | — | allowed | `report` |
| `reports.get_report` | read | — | allowed | — |

`schema_info`, `session` and `tool_call` are written by the runtime and the data layer, never through a tool.

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

Returns the unified diff of the file. Errors: `not_found` when the file is not in the change set.

### `git.read_file`

| Input | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | Path in the repository. |
| `version` | string | yes | `base` or `candidate`. |

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

No inputs. Returns the number of requirements read, added and changed, and the files that could not be parsed. Errors: `invalid_state` when `project.requirements` is not configured.

### `memory.get_requirements`

| Input | Type | Required | Description |
|---|---|---|---|
| `ids` | list of strings | no | Requirement IDs. Default: all. |

Returns each requirement with its fields and its changes.

### `memory.get_analysis`

| Input | Type | Required | Description |
|---|---|---|---|
| `analysis_id` | integer | no | Default: the latest analysis of the session versions. |

Returns the change set, the impacted modules and the impacted requirements. Errors: `not_found`.

### `memory.save_impact`

Records the impact analysis proposed by the model for an analysis.

| Input | Type | Required | Description |
|---|---|---|---|
| `analysis_id` | integer | yes | — |
| `modules` | list | yes | Each: `module`, `files` (from the change set), `risk_level`, `reason`. |
| `requirements` | list | yes | Each: `requirement_id`, `reason`. May be empty. |

Returns the number of modules and requirements recorded. Replaces a previous impact of the same analysis. Errors: `not_found` for an unknown file or requirement.

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

Returns the suite ID. Errors: `not_found` for an unknown test case; `invalid_argument` for duplicated test cases or positions.

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

Updates the design of a test case that is still `designed`.

| Input | Type | Required | Description |
|---|---|---|---|
| `test_case_id` | string | yes | — |
| `fields` | object | yes | Any of the design fields of `design_test_case`, except `selection_reason`. |

Errors: `invalid_state` when the test case is `implemented`.

### `memory.get_test_cases`

| Input | Type | Required | Description |
|---|---|---|---|
| `ids` | list of strings | no | Default: all. |
| `status` | string | no | `designed` or `implemented`. |
| `requirement_id` | string | no | Only test cases traced to it. |

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
| `classification` | string | yes | `regression`, `expected_change`, `flaky`, `environment` or `test_defect`. |
| `justification` | string | yes | — |

Errors: `invalid_state` when the execution did not fail or is already triaged.

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

| Input | Type | Required | Description |
|---|---|---|---|
| `defect_id` | string | yes | An open defect. |
| `reason` | string | yes | — |

Errors: `invalid_state` when the defect is already closed.

### `memory.get_defects`

| Input | Type | Required | Description |
|---|---|---|---|
| `status` | string | no | `open` or `closed`. Default: both. |

Returns each defect with its linked executions.

## Server `test_runner`

Writes test code and executes tests (ADR-0009, ADR-0010, ADR-0015).

### `test_runner.write_test`

Writes the test code of a `designed` test case to `.retro/tests/` and sets it to `implemented`.

| Input | Type | Required | Description |
|---|---|---|---|
| `test_case_id` | string | yes | A `designed` test case. |
| `file` | string | yes | Path relative to `.retro/tests/`. |
| `test_name` | string | yes | Name of the test function; must follow `test_req_<NNN>_<description>` when the test case traces a requirement. |
| `code` | string | yes | Full content of the file. |

Returns the implementation reference `<file>::<test name>`. The `test_id` is set when a run first reports the test. Errors: `invalid_state` when the test case is not `designed`; `invalid_argument` when the path leaves `.retro/tests/`.

### `test_runner.run_tests`

Creates a run against one session version and executes it, following `project-contract.md`.

| Input | Type | Required | Description |
|---|---|---|---|
| `version` | string | yes | `base` or `candidate`. |
| `scope` | string | yes | `suite`, `all` or `selected`. |
| `test_case_ids` | list of strings | when `selected` | Implemented test cases. |

Returns the run ID, its status and the counts of execution statuses and results. Tests of the project unknown to memory are registered as `project_suite` test cases, with requirement links from their names. Errors: `invalid_state` when the scope has no implemented test cases; a failed setup or service produces a run with status `error`, not a tool error.

### `test_runner.get_evidence`

| Input | Type | Required | Description |
|---|---|---|---|
| `run_id` | string | yes | — |
| `test_case_id` | string | no | Only the evidence of this test case. |

Returns the failure messages of each attempt and the relevant part of the run log.

## Server `reports`

Computes metrics and renders reports (ADR-0006, ADR-0018, ADR-0020).

### `reports.evaluate`

Computes metrics, exit criteria and the release decision, following `metrics.md`, and stores the evaluation.

| Input | Type | Required | Description |
|---|---|---|---|
| `run_id` | string | no | Evaluated run. Default: the latest completed run against the candidate. |

Returns the metrics, the state of each criterion and the decision. Errors: `invalid_state` when the run is not a completed run against the candidate.

### `reports.prepare_report`

First step of report generation: computes everything and creates a `draft` report.

| Input | Type | Required | Description |
|---|---|---|---|
| `type` | string | yes | `test-plan`, `test-cases`, `status`, `defects` or `completion`. |
| `run_id` | string | no | For `status`, `defects` and `completion`. Defaults as in `reports.md`. |
| `formats` | list of strings | no | `md`, `pdf`. Default: `reports.default_format`. |

Returns the report ID, the computed data of the report and the agent sections to write, each with its purpose from `reports.md`.

### `reports.render_report`

Second step: writes the report files and sets the report to `rendered`.

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
