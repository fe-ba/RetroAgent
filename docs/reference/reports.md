# Reports reference

Single catalog of everything that connects report templates to data: report types, values, blocks, items, agent sections and charts. Template syntax is defined in ADR-0018 and ADR-0019. Metric definitions are in `metrics.md`.

## Report types

| `/report` type | Template | Data it describes |
|---|---|---|
| `test-plan` | `test-plan.md` | The latest impact analysis and the current suite. No run is needed. |
| `test-cases` | `test-case-specification.md` | The test cases of the current suite. No run is needed. |
| `status` | `test-status-report.md` | One run, against either version. Default: the latest run. |
| `defects` | `defect-report.md` | Defects found in the evaluated run, plus every open defect. |
| `completion` | `test-completion-report.md` | The evaluated run and its comparisons, as defined in `metrics.md`. |

The **current suite** is the suite selected for the latest impact analysis of the session versions. The **evaluated run** and the other evaluation inputs are defined in `metrics.md`.

In a `status` report about a run against the baseline, `decision.value` and `criteria.*` are `not evaluable`: exit criteria are only evaluated for runs against the candidate.

## Output

- Each generation creates a new report with the next identifier (`RPT-0001`, `RPT-0002`, ...). Reports are never overwritten, so a delivered report never changes.
- Files are written to `.retro/reports/<report-id>-<type>/`: `report.md`, `report.pdf` when PDF is requested, and `charts/*.svg` when the template references charts.
- The model that wrote the agent sections and the generation time are part of the report header.

## Template resolution

1. The template is looked up in `templates/<language>/` and then in `templates/`.
2. Item templates are looked up in `templates/<language>/items/` and then in `templates/items/`.
3. Every marker is resolved. An unknown marker stops generation with an error that names the marker and the template.

## Formatting

| Kind | Format | Example |
|---|---|---|
| Ratio | Percentage with one decimal | `88.9%` |
| Count | Integer | `12` |
| Duration | Seconds with one decimal | `42.3 s` |
| Timestamp | ISO 8601 with UTC offset, to the minute | `2026-11-15T10:00-05:00` |
| Commit | First 7 characters | `a1b2c3d` |
| List | Items joined with commas | `TC-004, TC-007` |
| Enumeration | Value as defined in the glossary | `do_not_release` |
| Text | As stored | — |
| Missing metric | `not evaluable` | — |
| Any other missing value | `none` | — |

Every value is rendered on a single line: line breaks become spaces and `|` is escaped, so a value never breaks the table it is placed in.

## Values

Values outside items. `metrics.*` and `suite.*` are listed after this table.

| Value | Kind | Content |
|---|---|---|
| `project.name` | Text | `project.name` from the configuration, or the directory name. |
| `report.id` | Identifier | Identifier of this report. |
| `report.generated_at` | Timestamp | Generation time. |
| `report.tool_version` | Text | RetroAgent version. |
| `model` | Text | Model that wrote the agent sections, as `<provider>/<model name>`. |
| `versions.base.ref` | Text | Baseline ref. |
| `versions.base.commit` | Commit | Baseline commit. |
| `versions.candidate.ref` | Text | Candidate ref. |
| `versions.candidate.commit` | Commit | Candidate commit. |
| `run.id` | Identifier | Evaluated run, or the run of a `status` report. |
| `run.version` | Text | Ref the run was executed against. |
| `run.started_at` | Timestamp | Start of the run. |
| `run.ended_at` | Timestamp | End of the run. |
| `baseline_run.id` | Identifier | Baseline run used for comparison. |
| `decision.value` | Enumeration | Release decision. `not evaluable` when the criteria cannot be evaluated. |
| `criteria.met` | Count | Exit criteria in state `met`. `not evaluable` when the criteria cannot be evaluated. |
| `criteria.not_met` | Count | Exit criteria in state `not_met`. Same rule. |
| `criteria.not_evaluable` | Count | Exit criteria in state `not_evaluable`. Same rule. |

**`metrics.<name>`**: every metric of `metrics.md`, by its name, computed for the evaluated run. `metrics.open_defects.<severity>` takes one of the four severities.

**`suite.<name>`**: `planned`, `implemented`, `designed_only` and `high_priority_planned`, with the definitions of the metrics of the same name, computed on the current suite instead of the suite of a run.

## Blocks

A block is replaced by a table or a list, or by its empty message when there is no data. Lists use bullets unless stated otherwise.

| Block | Columns or items | Rows | Empty message |
|---|---|---|---|
| `table:change_set` | File, Change, Lines added, Lines removed | Each changed file. Change is `added`, `modified`, `deleted` or `renamed`. | No changes between the baseline and the candidate. |
| `table:impacted_modules` | Module, Files changed, Risk level, Requirements | Each impacted module, highest risk level first. | No impacted modules. |
| `table:impacted_requirements` | Requirement, Title, Priority, Reason | Each impacted requirement, with the reason recorded by the impact analysis. | No impacted requirements. |
| `table:risks` | ID, Risk, Level, Requirements | Each registered risk, highest level first. | No risks registered. |
| `table:planned_suite` | Test case, Title, Priority, Status, Requirements, Selection reason | Each test case of the current suite, with the justification recorded at selection (FR-14). | The suite is empty. |
| `table:environment` | Item, Value | Baseline ref, candidate ref, setup command, test command, selection command, service start command, JUnit location, reruns, timeout and model. | — |
| `table:criteria_thresholds` | ID, Criterion, Threshold, Blocking | Each exit criterion with its effective threshold. | — |
| `table:criteria` | ID, Criterion, Threshold, Value, State, Blocking | Each exit criterion with its evaluation. | — |
| `table:deviations` | Test case, Deviation, Reason | Test cases of the suite that were `designed` only, and executions that were `blocked` or `skipped`, with their recorded reason. | No deviations: every planned test case was implemented and executed. |
| `table:review_items` | Test case, Reason for review, Detail | Excused executions (classification and justification), flaky executions (attempt results) pre-existing failures (baseline run and result), and executions triaged more than once (previous and current classification). | Nothing requires review. |
| `table:open_defects` | ID, Severity, Title, Test cases | Each open defect, highest severity first. | No open defects. |
| `table:defects` | ID, Title, Severity, Status, Detected in, Test cases | Each defect in the scope of the defect report. | No defects. |
| `table:deliverables` | Deliverable, Location | Evidence of every run used, generated tests and the folder of this report. | — |
| `table:test_cases` | Test case, Title, Priority, Status, Requirements | Each test case of the current suite. | The suite is empty. |
| `table:traceability` | Requirement, Test cases | Each documented requirement, including those with no test case (`none`). | No documented requirements. |
| `list:decision_reasons` | — | See below. | — |
| `list:limitations` | — | Each metric or criterion that is not evaluable, with the reason; then the fixed limitations: the flaky count is a lower bound, and code coverage is not measured. | — |
| `table:input_data` | Name, Value | Inside a test case: each input of the test case. | No input data. |
| `list:preconditions` | — | Inside a test case: each precondition. | No preconditions. |
| `list:steps` | — | Inside a test case or a defect: each step, as a **numbered** list. | No steps recorded. |
| `table:evidence` | Run, Test case, Attempt, Result, Failure message, Log | Inside a defect: each attempt of the linked executions. Failure messages are cut to 200 characters. | No evidence recorded. |
| `table:history` | Run, Version, Test case, Status, Result | Inside a defect: every execution of the linked test cases, oldest first. | No history. |

### Decision reasons

`list:decision_reasons` depends on the release decision:

| Decision | Items |
|---|---|
| `do_not_release` | Each blocking criterion that is `not_met` or `not_evaluable`, with its threshold and value. |
| `release_with_conditions` | Each condition listed in `metrics.md`. |
| `release` | A single item: all exit criteria are met. |
| `not evaluable` | A single item: exit criteria are only evaluated for runs against the candidate. |

## Items

| Items | Item template | Elements | Order |
|---|---|---|---|
| `items:test_case` | `items/test-case.md` | Test cases of the current suite. | Priority (high first), then ID. |
| `items:defect` | `items/defect.md` | Defects in the scope of the defect report. | Severity (critical first), then ID. |

### Test case values

| Value | Kind | Content |
|---|---|---|
| `test_case.id` | Identifier | Test case ID. |
| `test_case.title` | Text | Short title. |
| `test_case.objective` | Text | What the test case verifies. |
| `test_case.priority` | Enumeration | Test case priority. |
| `test_case.status` | Enumeration | `designed` or `implemented`. |
| `test_case.requirements` | List | Traced requirement IDs. |
| `test_case.origin` | Text | `project suite`, or `designed by <model>`. |
| `test_case.implementation` | Text | `<file>::<test name>`, or `none` when only designed. |
| `test_case.last_execution` | Text | `<run> against <ref>: <status or result>`, or `none`. |
| `test_case.expected_result` | Text | Expected result. |

### Defect values

| Value | Kind | Content |
|---|---|---|
| `defect.id` | Identifier | Defect ID. |
| `defect.title` | Text | Short title. |
| `defect.status` | Enumeration | Defect status. |
| `defect.severity` | Enumeration | Defect severity. |
| `defect.run_id` | Identifier | Run in which the defect was detected. |
| `defect.version` | Text | Ref of that run. |
| `defect.detected_at` | Timestamp | Registration time. |
| `defect.test_cases` | List | Linked test case IDs. |
| `defect.requirements` | List | Requirements traced to the linked test cases. |
| `defect.classification` | Enumeration | Triage classification of the linked execution. |
| `defect.expected` | Text | Expected result of the linked test case. |
| `defect.actual` | Text | First line of the failure message from the JUnit XML. |
| `defect.triaged_by` | Text | Model that classified the execution. |
| `defect.justification` | Text | Justification recorded at triage. |

## Agent sections

The model writes each agent section from the computed data of the same report. It must not state figures, statuses or decisions that are not in that data, and it never changes a computed value. Sections are rendered as:

```markdown
> **Agent analysis** · written by `<model>`, not computed.
>
> <text>
```

If the model is not available or returns nothing, the text is `Not provided.` and the report is still generated.

| Section | Report | Content |
|---|---|---|
| `agent:conclusions` | Completion | Interpretation of the release decision and the recommended actions. |
| `agent:summary` | Completion | What was tested and what the results mean. |
| `agent:deviations` | Completion | Why planned testing deviated, and its effect on the conclusions. |
| `agent:residual_risks` | Completion | Risks that remain after testing, and their potential impact. |
| `agent:limitations` | Completion | What the results cannot show, beyond the computed limitations. |
| `agent:context` | Test plan | Purpose of the change and of this regression cycle. |
| `agent:scope` | Test plan | Why the scope is what it is, and what is deliberately excluded. |
| `agent:risks` | Test plan, status | Plan: risks that guide prioritization. Status: risks that are new or changed since the plan. |
| `agent:strategy` | Test plan | How selection and design address the impacted areas. |
| `agent:status` | Status | Current state of testing in a few sentences. |
| `agent:next_steps` | Status | Testing planned next, and what it depends on. |
| `agent:analysis` | Defect item | Impact of the defect and its probable cause, stated as a hypothesis. |

Agent sections are named without the `agent:` prefix, for example `conclusions`. Inside items, the name ends with the element: `analysis.DEF-001`. `reports.prepare_report` lists every section to write by that name.

## Charts

| Chart | File | Data | Used in |
|---|---|---|---|
| Execution outcomes | `charts/outcomes.svg` | Bars for `passed`, `failed`, `error`, `blocked` and `skipped`. | Completion, status |
| Comparison with the baseline | `charts/comparison.svg` | Bars for `new_failures`, `fixed`, `persistent_failures` and `stable_passes`. | Completion, status |
| Exit criteria | `charts/criteria.svg` | One horizontal bar per criterion with a threshold: its value, with the threshold marked. | Completion |

When the data of a chart is not evaluable, the chart shows a message instead of bars.
