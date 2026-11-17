# Data model

Long-term memory of a target project, stored in `.retro/retro.db` (SQLite, ADR-0008). This document defines every table, every column, which component writes it, and the invariants the data layer enforces. Vocabulary and enumerations come from `docs/reference/glossary.md`.

## Principles

- **One writer per fact.** Each table lists the only component allowed to write it. MCP tools are the only way the model reaches the data, and no tool lets the model write what another component owns.
- **Code assigns identifiers.** `REQ`, `TC`, `RUN`, `DEF`, `RSK` and `RPT` identifiers are assigned by the data layer in sequence and never reused. The model never provides an identifier for a new record.
- **Code reads requirements.** Requirements are parsed from the documents listed in `project.requirements`, in the format of `project-contract.md`, from the candidate version.
- **History is kept.** Records are never deleted. Runs, test executions, evaluations and reports are immutable once complete.
- **Model input is marked.** Columns whose content comes from the model are marked *model* in the Source column, and text typed by the user is marked *user*; everything else is *code*.

## Conventions

| Item | Rule |
|---|---|
| Timestamps | Text in ISO 8601, UTC, with milliseconds. Converted to local time with offset only when displayed. |
| Lists | JSON arrays stored as text, in the order given. |
| Booleans | Integer `0` or `1`. |
| Identifiers | Text primary keys in the glossary format (`TC-001`). Internal tables without a glossary identifier use an integer key named `id`. |
| Foreign keys | Enforced (`PRAGMA foreign_keys = ON`). |
| Enumerations | Enforced with `CHECK` constraints using the exact glossary values. |

## Overview

| Area | Tables |
|---|---|
| Sessions and audit | `schema_info`, `session`, `tool_call` |
| Requirements | `requirement`, `requirement_change` |
| Impact analysis | `analysis`, `analysis_file`, `analysis_module`, `analysis_requirement`, `analysis_requirement_not_impacted`, `risk`, `risk_requirement` |
| Test design and selection | `test_case`, `test_case_requirement`, `suite`, `suite_test_case` |
| Execution | `run`, `test_execution`, `attempt` |
| Interpretation | `triage`, `defect`, `defect_execution` |
| Reporting | `evaluation`, `report` |

## Sessions and audit

### `schema_info`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `key` | text | primary key | code | `schema_version` or `created_by`. |
| `value` | text | not null | code | Schema version number, or the RetroAgent version that created the database. |

Writer: data layer, on creation and migration.

### `session`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | integer | primary key | code | — |
| `started_at` | text | not null | code | — |
| `ended_at` | text | | code | Null while the session is running. |
| `model` | text | not null | code | `<provider>/<model name>` in use. Updated by `/model`. |
| `interactive` | integer | not null | code | `1` for an interactive session, `0` for non-interactive mode. |
| `base_ref` | text | | code | Baseline of the session versions. Null while not set. |
| `base_commit` | text | | code | Full commit hash. |
| `candidate_ref` | text | | code | Candidate of the session versions. Null while not set. |
| `candidate_commit` | text | | code | Full commit hash. |
| `result_char_limit` | integer | not null | code | Largest tool result of the session, in characters (`context-loading.md`). |

Writer: runtime. This record is the session context of the bundled servers: each server is started for one project and one session, and reads the versions and the model from here when a tool needs them (ADR-0026). Records such as `designed_by` and `triaged_by` copy the model at the time they are written.

### `tool_call`

Audit trail of every tool call (NFR-04).

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | integer | primary key | code | — |
| `session_id` | integer | not null, references `session` | code | — |
| `server` | text | not null | code | MCP server name, or `runtime` for runtime tools. |
| `tool` | text | not null | code | Tool name. |
| `arguments` | text | not null | model | JSON arguments as received. Values of known secret variables are replaced by `***`. |
| `outcome` | text | not null, `ok`, `error` or `denied` | code | `denied` when the runtime refused the call: mode, permission, user-only tool, tool outside the step, or missing approval. `error` for every other call without a result, including `deferred`, invalid arguments, an unknown tool and an interrupted call. The row is written before dispatch as `error` with the message that the session ended during the call, and updated when the call is answered. |
| `error` | text | | code | Error message when `outcome` is `error` or `denied`. |
| `started_at` | text | not null | code | — |
| `ended_at` | text | | code | — |

Writer: runtime, for every call, before and after dispatch.

## Requirements

### `requirement`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | text | primary key, `REQ-NNN` | code | Taken from the requirement heading. |
| `title` | text | not null | code | — |
| `description` | text | not null | code | — |
| `priority` | text | `high`, `medium` or `low` | code | Null when not documented. |
| `since` | text | | code | Version that introduced it. |
| `removed` | text | | code | Version that removed it. |
| `source_file` | text | not null | code | Document it was read from. |
| `synced_at` | text | not null | code | Last time it was read. |

### `requirement_change`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `requirement_id` | text | references `requirement` | code | — |
| `version` | text | not null | code | Version in which it changed. |
| `description` | text | not null | code | Description of the change. |

Writer of both tables: memory server, by parsing the requirement documents. A requirement that disappears from the documents keeps its record; its `synced_at` is not updated.

## Impact analysis

### `analysis`

One impact analysis of a version pair.

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | integer | primary key | code | — |
| `base_ref` | text | not null | code | — |
| `base_commit` | text | not null | code | Full commit hash. |
| `candidate_ref` | text | not null | code | — |
| `candidate_commit` | text | not null | code | Full commit hash. |
| `session_id` | integer | not null, references `session` | code | — |
| `created_at` | text | not null | code | — |

Writer: git server, when the change set is computed.

### `analysis_file`

The change set.

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `analysis_id` | integer | references `analysis` | code | — |
| `path` | text | not null | code | Path in the candidate, or in the baseline when deleted. |
| `old_path` | text | | code | Previous path when renamed. |
| `change` | text | `added`, `modified`, `deleted` or `renamed` | code | — |
| `lines_added` | integer | not null | code | — |
| `lines_removed` | integer | not null | code | — |

Writer: git server.

### `analysis_module`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `analysis_id` | integer | references `analysis` | code | — |
| `module` | text | not null | model | Module name. |
| `files` | text | not null | model | List of changed files that belong to the module. Every file must exist in `analysis_file`. |
| `risk_level` | text | `high`, `medium` or `low` | model | — |
| `reason` | text | not null | model | Why the module has that risk level. |

Writer: memory server, from the impact analysis proposed by the model. The impact of an analysis is written once; a corrected impact needs a new analysis (INV-10, INV-11).

### `analysis_requirement`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `analysis_id` | integer | references `analysis` | code | — |
| `requirement_id` | text | references `requirement` | model | Must exist. |
| `reason` | text | not null | model | Why the requirement is impacted. |

Writer: memory server.

### `analysis_requirement_not_impacted`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `analysis_id` | integer | references `analysis` | code | — |
| `requirement_id` | text | references `requirement` | model | Must exist. |
| `reason` | text | not null | model | Why the requirement is not impacted. |

Writer: memory server, in the same transaction as `analysis_requirement`. A requirement appears in at most one of the two tables for an analysis. Metrics read only `analysis_requirement`; this table makes the decisions on the other requirements reviewable.

### `risk`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | text | primary key, `RSK-NNN` | code | — |
| `description` | text | not null | model | — |
| `level` | text | `high`, `medium` or `low` | model | — |
| `analysis_id` | integer | references `analysis` | code | Analysis during which it was registered. |
| `created_at` | text | not null | code | — |

### `risk_requirement`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `risk_id` | text | references `risk` | code | — |
| `requirement_id` | text | references `requirement` | model | Must exist. |

Writer of both tables: memory server.

## Test design and selection

### `test_case`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | text | primary key, `TC-NNN` | code | — |
| `title` | text | not null | model, or code for discovered tests | Discovered tests use their test name. |
| `objective` | text | | model | Null for discovered tests until described. |
| `priority` | text | `high`, `medium` or `low` | model | A discovered test starts with the highest priority of the requirements its name links it to, or `medium` when it has none. When a synchronization of requirements gives a discovered test its first name links, its priority is set again by the same rule. The model may change it afterwards. |
| `status` | text | `designed` or `implemented` | code | — |
| `origin` | text | `designed` or `project_suite` | code | `designed` when created by the agent; `project_suite` when discovered in the project's tests. |
| `designed_by` | text | | code | Model that designed it. Null for `project_suite`. |
| `preconditions` | text | not null, default `[]` | model | List of preconditions. |
| `input_data` | text | not null, default `[]` | model | List of `{"name", "value"}` objects. |
| `steps` | text | not null, default `[]` | model | Ordered list of steps. |
| `expected_result` | text | | model | — |
| `test_id` | text | unique | code | Identity in JUnit XML: `<classname>::<name>`. Set the first time a run reports the test, or at discovery. Null while `designed`. |
| `implementation` | text | | code | For generated tests, `<file>::<test name>`. For `project_suite` tests, the `file` attribute of the JUnit XML when it has one, otherwise the `classname`, followed by `::<name>`. Null while `designed`. |
| `revision` | integer | | code | Version of the generated test code: `1` when first written, incremented by each rewrite. Null while `designed` and for `project_suite`. |
| `retired_at` | text | | code | Null while the test case is active. |
| `retire_reason` | text | | model | Why it was retired. |
| `retired_by` | text | | code | Model in use when it was retired. |
| `created_at` | text | not null | code | — |
| `updated_at` | text | not null | code | — |

Writers:

- Memory server: creates `designed` test cases, updates design fields within the limits of `memory.update_test_case`, and retires test cases.
- Test runner server: sets `implemented`, `implementation` and `revision` when it writes test code, increments `revision` and updates the design fields given with a rewrite, sets `test_id` the first time a run reports the test, and creates `project_suite` test cases when a run finds a test it does not know.

A retired test case keeps every record. It cannot be added to a suite, and its generated test is no longer copied into worktrees. Retiring is permanent: a replacement is a new test case.

### `test_case_requirement`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `test_case_id` | text | references `test_case` | code | — |
| `requirement_id` | text | references `requirement` | model or code | Must exist. |
| `link` | text | `design` or `name` | code | `design` when declared in the design; `name` when found in the test name (`project-contract.md`). |

Writers: memory server (`design`) and test runner server (`name`).

### `suite`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | integer | primary key | code | — |
| `analysis_id` | integer | not null, references `analysis` | code | — |
| `session_id` | integer | not null, references `session` | code | — |
| `created_at` | text | not null | code | — |

The **current suite** is the latest suite of the latest analysis of the session versions. An analysis belongs to the session versions when its `base_commit` and `candidate_commit` equal their commits. A new analysis starts a new cycle: there is no current suite until a suite is saved for it.

### `suite_test_case`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `suite_id` | integer | references `suite` | code | — |
| `test_case_id` | text | references `test_case` | model | Must exist. |
| `position` | integer | not null | model | Priority order of the selection, from highest priority. Used for presentation; the test framework decides the execution order (ADR-0017). |
| `selection_reason` | text | not null | model | Justification of the inclusion (FR-14). |

Writer of both tables: memory server. Test cases designed for the change are added to the current suite when they are designed.

## Execution

### `run`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | text | primary key, `RUN-NNNN` | code | — |
| `version_role` | text | `base` or `candidate` | code | — |
| `ref` | text | not null | code | — |
| `commit` | text | not null | code | Full commit hash. |
| `scope` | text | `suite`, `all` or `selected` | code | What was run. `all` makes it a full run. |
| `suite_id` | integer | references `suite` | code | Required when `scope` is `suite`. |
| `status` | text | `running`, `completed`, `error` or `interrupted` | code | — |
| `command` | text | not null | code | Test command of the first attempt, after placeholder substitution. Recorded when the run starts, also when an earlier step fails. Commands of reruns are in the run log. |
| `exit_code` | integer | | code | Exit code of the test command of the first attempt. Null when it did not run. |
| `junit_path` | text | | code | JUnit XML of the first attempt in the run directory, relative to the project. Null when none was produced. |
| `evidence_dir` | text | not null | code | `.retro/runs/<run_id>/`. |
| `error` | text | | code | Failed step and message when `status` is `error` or `interrupted`. On a `completed` run, the test files of the project that could not be loaded (`project-contract.md`, Generated tests). |
| `session_id` | integer | not null, references `session` | code | — |
| `started_at` | text | not null | code | — |
| `ended_at` | text | | code | — |

Writer: test runner server.

### `test_execution`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | integer | primary key | code | — |
| `run_id` | text | not null, references `run` | code | — |
| `test_case_id` | text | not null, references `test_case` | code | Unique together with `run_id`. |
| `status` | text | `executed`, `blocked` or `skipped` | code | — |
| `result` | text | `passed`, `failed` or `error` | code | Only when `status` is `executed`. |
| `reason` | text | | code | Why it was `blocked` or `skipped`. See the reasons below. |
| `duration` | real | | code | Seconds, from the first attempt. |
| `test_revision` | integer | | code | `revision` of the generated test code used by the run, for every execution of a generated test, blocked ones included. Null for `project_suite`. |

Writer: test runner server, only from parsed run evidence.

| Status | `reason` | When |
|---|---|---|
| `blocked` | `setup_failed` | `tests.setup` failed. |
| `blocked` | `service_not_ready` | The service did not answer within `service.ready_timeout`. |
| `blocked` | `no_junit` | The test command produced no valid JUnit XML. |
| `blocked` | `not_reported` | The run was asked to execute the test case and the JUnit XML has no result for it: the test does not exist in that version, or its file could not be loaded. |
| `blocked` | `timeout` | `tests.timeout` stopped the test command. |
| `blocked` | `interrupted` | The user interrupted the run. |
| `skipped` | Message of the test framework | The JUnit XML reports the test as skipped. |

Which test cases get an execution in a run depends on its scope (`mcp-tools.md`, `test_runner.run_tests`).

### `attempt`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `execution_id` | integer | references `test_execution` | code | — |
| `number` | integer | not null, from `1` | code | Unique together with `execution_id`. It is the round of the run: `1` for the test command, `2` and later for the reruns, and it names the JUnit XML of that round. A round without a result for the test case leaves a gap. |
| `result` | text | `passed`, `failed` or `error` | code | — |
| `duration` | real | | code | Seconds. |
| `failure_message` | text | | code | From the JUnit XML. |

Writer: test runner server. Attempt `1` is the original execution and gives the result; attempts `2` and later are reruns, created only when attempt `1` did not pass. A test execution is **flaky** when at least one of its reruns passed (`metrics.md`); this is computed, not stored. Attempts are added only while the run is `running`.

## Interpretation

### `triage`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | integer | primary key | code | — |
| `execution_id` | integer | not null, references `test_execution` | code | An execution can be triaged again; every triage is kept. |
| `classification` | text | `regression`, `expected_change`, `flaky`, `environment`, `test_defect` or `pre_existing` | model | `expected_change`, `flaky` and `pre_existing` are accepted only with the evidence that `mcp-tools.md` requires. |
| `justification` | text | not null | model | — |
| `triaged_by` | text | not null | code | Model that classified it. |
| `created_at` | text | not null | code | — |

Writer: memory server.

The **current triage** of an execution is its latest row. Metrics, exit criteria and reports use the current triage; an execution with more than one row is listed for review (`reports.md`).

### `defect`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | text | primary key, `DEF-NNN` | code | — |
| `title` | text | not null | model | — |
| `severity` | text | `critical`, `high`, `medium` or `low` | model | — |
| `status` | text | `open` or `closed` | code | Created `open`. |
| `detected_run_id` | text | not null, references `run` | code | Run of the first linked execution. |
| `detected_at` | text | not null | code | — |
| `expected` | text | | code | Expected result of the linked test case. Null when the test case has none. |
| `actual` | text | not null | code | First line of the failure message of the first linked execution. When it has no message, its result followed by `without a message`. |
| `steps` | text | not null, default `[]` | model | Steps to reproduce. |
| `closed_at` | text | | code | — |
| `closed_by` | text | `run` or `user` | code | Null while `open`. |
| `closed_run_id` | text | references `run` | code | Run that verified the fix, when `closed_by` is `run`. |
| `close_reason` | text | | code or user | Generated when closed by a run; typed by the user otherwise. |

### `defect_execution`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `defect_id` | text | references `defect` | code | — |
| `execution_id` | integer | references `test_execution` | model | Must have result `failed` or `error`. |

Writers of `defect` and `defect_execution`: memory server, for registration and links proposed by the model and for closing by the user; test runner server, for closing by a run, which writes `defect` only. The model cannot close a defect (INV-14).

## Reporting

### `evaluation`

A stored computation of metrics, exit criteria and the release decision, so that a report can be reproduced (`metrics.md`).

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | integer | primary key | code | — |
| `run_id` | text | not null, references `run` | code | Evaluated run. |
| `baseline_run_id` | text | references `run` | code | — |
| `full_base_run_id` | text | references `run` | code | `F0` in `metrics.md`. |
| `full_candidate_run_id` | text | references `run` | code | `F` in `metrics.md`. |
| `analysis_id` | integer | references `analysis` | code | — |
| `thresholds` | text | not null | code | Effective `exit_criteria.*` as JSON. |
| `metrics` | text | not null | code | Every metric as JSON; not evaluable metrics are `null`. Ratios are stored as numerator and denominator. |
| `criteria` | text | not null | code | Every criterion as JSON: identifier, name, state, value, threshold, whether it is blocking, and the reason when it is not evaluable. |
| `decision` | text | not null; `release`, `release_with_conditions` or `do_not_release` | code | Always set: a blocking criterion that cannot be evaluated gives `do_not_release` (`metrics.md`). |
| `decision_details` | text | not null | code | The reasons and the conditions of the decision as JSON, with the test cases and classifications they name, as they were when the evaluation was computed. |
| `tool_version` | text | not null | code | RetroAgent version that computed it. |
| `created_at` | text | not null | code | — |

Writer: reports server.

### `report`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | text | primary key, `RPT-NNNN` | code | — |
| `type` | text | `test-plan`, `test-cases`, `status`, `defects` or `completion` | code | — |
| `status` | text | `draft` or `rendered` | code | `draft` while agent sections are pending. |
| `evaluation_id` | integer | references `evaluation` | code | Null for `test-plan` and `test-cases`. |
| `model` | text | not null | code | Model that writes the agent sections. |
| `path` | text | not null | code | `.retro/reports/<report-id>-<type>/`. |
| `formats` | text | not null | code | List of produced formats: `md`, `pdf`. |
| `created_at` | text | not null | code | — |

Writer: reports server.

## Invariants

Enforced by the data layer, not by prompts. Each one must have a unit test.

| ID | Invariant | Enforced by |
|---|---|---|
| INV-01 | A test execution has a `result` if and only if its `status` is `executed`. | `CHECK` constraint |
| INV-02 | A test execution with status `executed` belongs to a run whose `junit_path` is not null. | Trigger |
| INV-03 | Test executions and attempts are created only by the test runner server; no MCP tool that writes accepts an execution status or result as input. Read tools may filter by them. | Tool contracts |
| INV-04 | The `result` of a test execution equals the result of its first attempt. Later attempts exist only when that result is not `passed`. | Trigger |
| INV-05 | A test case with status `implemented` has an `implementation`; a `designed` one has neither an `implementation`, a `test_id` nor a `revision`. | `CHECK` constraint |
| INV-06 | A test case with status `designed` has no test executions. | Trigger |
| INV-07 | Identifiers are assigned by the data layer in sequence and never reused. | Data layer API |
| INV-08 | A triage, and a link from a defect, refer only to executions with result `failed` or `error`. | Trigger |
| INV-09 | A run with `scope` `suite` has a `suite_id`, and its executions are only for test cases of that suite. | `CHECK` constraint and trigger |
| INV-10 | Runs that are not `running`, their executions and attempts, triage rows, the impact of an analysis, evaluations and rendered reports are never updated. No execution or attempt is added to a run that is not `running`. | Triggers |
| INV-11 | Records are never deleted. One exception: the `design` links of a test case in `test_case_requirement` are replaced when its `requirement_ids` change, because they are part of its design, like its other design fields. Links with `link` `name` are never deleted. | Triggers |
| INV-12 | A defect with status `closed` has a `closed_at`, a `closed_by` and a `close_reason`; an `open` one has none. A defect closed by a run has a `closed_run_id`. | `CHECK` constraint |
| INV-13 | Every reference made by the model (requirement, test case, file, execution) must exist; otherwise the tool call fails and nothing is written. | Data layer API |
| INV-14 | A defect is closed only by a run that verifies the fix or by the user. No tool exposed to the model closes a defect. | Tool contracts |
| INV-15 | A triage with classification `expected_change`, `flaky`, `pre_existing` or `regression` is stored only when the data layer finds the evidence that `mcp-tools.md` requires. | Data layer API |
| INV-16 | A retired test case is never added to a suite. | Data layer API |
| INV-17 | The function name and the file of a generated test are unique among generated tests, and a rewrite keeps both. | Data layer API |

## Migrations

- `schema_info.schema_version` records the version of the schema.
- On start, RetroAgent migrates an older database automatically, after copying it to `.retro/retro.db.bak-<version>`.
- A database with a newer schema than the installed RetroAgent is not opened; the user is asked to update RetroAgent.
