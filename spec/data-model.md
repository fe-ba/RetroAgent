# Data model

Long-term memory of a target project, stored in `.retro/retro.db` (SQLite, ADR-0008). This document defines every table, every column, which component writes it, and the invariants the data layer enforces. Vocabulary and enumerations come from `docs/reference/glossary.md`.

## Principles

- **One writer per fact.** Each table lists the only component allowed to write it. MCP tools are the only way the model reaches the data, and no tool lets the model write what another component owns.
- **Code assigns identifiers.** `REQ`, `TC`, `RUN`, `DEF`, `RSK` and `RPT` identifiers are assigned by the data layer in sequence and never reused. The model never provides an identifier for a new record.
- **Code reads requirements.** Requirements are parsed from the documents listed in `project.requirements`, in the format of `project-contract.md`, from the candidate version.
- **History is kept.** Records are never deleted. Runs, test executions, evaluations and reports are immutable once complete.
- **Model input is marked.** Columns whose content comes from the model are marked *model* in the Source column; everything else is *code*.

## Conventions

| Item | Rule |
|---|---|
| Timestamps | Text in ISO 8601, UTC. Converted to local time with offset only when displayed. |
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
| Impact analysis | `analysis`, `analysis_file`, `analysis_module`, `analysis_requirement`, `risk`, `risk_requirement` |
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
| `model` | text | not null | code | `<provider>/<model name>`. |
| `interactive` | integer | not null | code | `1` for an interactive session, `0` for non-interactive mode. |

Writer: runtime.

### `tool_call`

Audit trail of every tool call (NFR-04).

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | integer | primary key | code | — |
| `session_id` | integer | not null, references `session` | code | — |
| `server` | text | not null | code | MCP server name, or `runtime` for runtime tools. |
| `tool` | text | not null | code | Tool name. |
| `arguments` | text | not null | model | JSON arguments as received. Values of known secret variables are replaced by `***`. |
| `outcome` | text | not null, `ok`, `error` or `denied` | code | `denied` when a permission was refused or the mode forbids the tool. |
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

Writer: memory server, from the impact analysis proposed by the model.

### `analysis_requirement`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `analysis_id` | integer | references `analysis` | code | — |
| `requirement_id` | text | references `requirement` | model | Must exist. |
| `reason` | text | not null | model | Why the requirement is impacted. |

Writer: memory server.

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
| `priority` | text | `high`, `medium` or `low` | model | Discovered tests start as `medium`. |
| `status` | text | `designed` or `implemented` | code | — |
| `origin` | text | `designed` or `project_suite` | code | `designed` when created by the agent; `project_suite` when discovered in the project's tests. |
| `designed_by` | text | | code | Model that designed it. Null for `project_suite`. |
| `preconditions` | text | not null, default `[]` | model | List of preconditions. |
| `input_data` | text | not null, default `[]` | model | List of `{"name", "value"}` objects. |
| `steps` | text | not null, default `[]` | model | Ordered list of steps. |
| `expected_result` | text | | model | — |
| `test_id` | text | unique | code | Identity in JUnit XML: `<classname>::<name>`. Set the first time a run reports the test, or at discovery. Null while `designed`. |
| `implementation` | text | | code | `<file>::<test name>`. Null while `designed`. |
| `created_at` | text | not null | code | — |
| `updated_at` | text | not null | code | — |

Writers:

- Memory server: creates `designed` test cases and updates their design fields while they are `designed`.
- Test runner server: sets `implemented` and `implementation` when it writes test code, sets `test_id` the first time a run reports the test, and creates `project_suite` test cases when a run finds a test it does not know.

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

The **current suite** is the latest suite of the latest analysis of the session versions.

### `suite_test_case`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `suite_id` | integer | references `suite` | code | — |
| `test_case_id` | text | references `test_case` | model | Must exist. |
| `position` | integer | not null | model | Execution and presentation order, from highest priority. |
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
| `command` | text | not null | code | Command actually executed, after placeholder substitution. |
| `exit_code` | integer | | code | Exit code of the test command. |
| `junit_path` | text | | code | Stored JUnit XML. Null when none was produced. |
| `evidence_dir` | text | not null | code | `.retro/runs/<run_id>/`. |
| `error` | text | | code | Failed step and message when `status` is `error`. |
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
| `reason` | text | | code | Why it was `blocked` or `skipped`. |
| `duration` | real | | code | Seconds, from the last attempt. |

Writer: test runner server, only from parsed run evidence.

### `attempt`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `execution_id` | integer | references `test_execution` | code | — |
| `number` | integer | not null, from `1` | code | Unique together with `execution_id`. |
| `result` | text | `passed`, `failed` or `error` | code | — |
| `duration` | real | | code | Seconds. |
| `failure_message` | text | | code | From the JUnit XML. |

Writer: test runner server. A test execution is **flaky** when its attempts have different results; this is computed, not stored.

## Interpretation

### `triage`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `execution_id` | integer | primary key, references `test_execution` | code | One classification per execution. |
| `classification` | text | `regression`, `expected_change`, `flaky`, `environment` or `test_defect` | model | — |
| `justification` | text | not null | model | — |
| `triaged_by` | text | not null | code | Model that classified it. |
| `created_at` | text | not null | code | — |

Writer: memory server.

### `defect`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `id` | text | primary key, `DEF-NNN` | code | — |
| `title` | text | not null | model | — |
| `severity` | text | `critical`, `high`, `medium` or `low` | model | — |
| `status` | text | `open` or `closed` | code | Created `open`. |
| `detected_run_id` | text | not null, references `run` | code | Run of the first linked execution. |
| `detected_at` | text | not null | code | — |
| `expected` | text | not null | code | Expected result of the linked test case. |
| `actual` | text | not null | code | First line of the failure message of the linked execution. |
| `steps` | text | not null, default `[]` | model | Steps to reproduce. |
| `closed_at` | text | | code | — |
| `close_reason` | text | | model | — |

### `defect_execution`

| Column | Type | Constraints | Source | Description |
|---|---|---|---|---|
| `defect_id` | text | references `defect` | code | — |
| `execution_id` | integer | references `test_execution` | model | Must have result `failed` or `error`. |

Writer of both tables: memory server.

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
| `criteria` | text | not null | code | Every criterion with its state, as JSON. |
| `decision` | text | `release`, `release_with_conditions` or `do_not_release` | code | Null when the criteria cannot be evaluated. |
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
| INV-03 | Test executions and attempts are created only by the test runner server; no MCP tool accepts an execution status or result as input. | Tool contracts |
| INV-04 | The `result` of a test execution equals the result of its last attempt. | Trigger |
| INV-05 | A test case with status `implemented` has an `implementation`; a `designed` one has neither an `implementation` nor a `test_id`. | `CHECK` constraint |
| INV-06 | A test case with status `designed` has no test executions. | Trigger |
| INV-07 | Identifiers are assigned by the data layer in sequence and never reused. | Data layer API |
| INV-08 | A triage, and a link from a defect, refer only to executions with result `failed` or `error`. | Trigger |
| INV-09 | A run with `scope` `suite` has a `suite_id`, and its executions are only for test cases of that suite. | `CHECK` constraint and trigger |
| INV-10 | Runs that are not `running`, their executions and attempts, evaluations and rendered reports are never updated. | Triggers |
| INV-11 | Records are never deleted. | Triggers |
| INV-12 | A defect with status `closed` has a `closed_at`; an `open` one has none. | `CHECK` constraint |
| INV-13 | Every reference made by the model (requirement, test case, file, execution) must exist; otherwise the tool call fails and nothing is written. | Data layer API |

## Migrations

- `schema_info.schema_version` records the version of the schema.
- On start, RetroAgent migrates an older database automatically, after copying it to `.retro/retro.db.bak-<version>`.
- A database with a newer schema than the installed RetroAgent is not opened; the user is asked to update RetroAgent.
