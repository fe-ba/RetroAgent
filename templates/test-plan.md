<!--
Test plan template.
Structure follows the test plan of ISO/IEC/IEEE 29119-3, adapted to automated regression testing.
Placeholders, blocks, items and agent sections are described in docs/reference/reports.md.
-->

# Test plan: {{ project.name }}

| Field | Value |
|---|---|
| Report | {{ report.id }} |
| Generated | {{ report.generated_at }} |
| Baseline | `{{ versions.base.ref }}` (`{{ versions.base.commit }}`) |
| Candidate | `{{ versions.candidate.ref }}` (`{{ versions.candidate.commit }}`) |
| Model | `{{ model }}` |
| RetroAgent | {{ report.tool_version }} |

## 1. Context of testing

Regression testing of the candidate version against the baseline version: existing behavior must be preserved, and changed behavior must match its requirements.

<!-- agent:context -->

### Change set

{{ table:change_set }}

### Impacted modules

{{ table:impacted_modules }}

## 2. Scope

### In scope

{{ table:impacted_requirements }}

### Out of scope

Non-functional testing (performance, load, security, usability) and user interface testing are outside the scope of RetroAgent.

<!-- agent:scope -->

## 3. Risks

{{ table:risks }}

<!-- agent:risks -->

## 4. Test strategy

### Approach

1. Impact analysis maps the change set to modules and requirements.
2. Existing test cases related to the impacted areas are selected and prioritized.
3. New test cases are designed for new or changed behavior, added to the suite and implemented.
4. The suite runs against the baseline and the candidate, each in an isolated worktree.
5. Failed tests are retried to detect flaky tests, and every failure is triaged.

<!-- agent:strategy -->

### Planned suite

| Measure | Value |
|---|---|
| Planned test cases | {{ suite.planned }} |
| Implemented | {{ suite.implemented }} |
| Designed only | {{ suite.designed_only }} |
| High priority | {{ suite.high_priority_planned }} |

{{ table:planned_suite }}

### Test environment

{{ table:environment }}

### Completion criteria

{{ table:criteria_thresholds }}

Metric definitions and the release decision rule are described in the RetroAgent metrics reference.

### Suspension and resumption

Testing of a version is suspended when its setup fails, when its service does not become ready in time, or when no JUnit XML is produced. The affected test executions are recorded as `blocked`. Testing resumes with a new run once the cause is removed.

## 5. Activities

| Step | Activity | Command |
|---|---|---|
| 1 | Impact analysis | `/analyze` |
| 2 | Test selection and prioritization | `/select` |
| 3 | Test design | `/design` |
| 4 | Test implementation | `/implement` |
| 5 | Execution against baseline and candidate | `/run --on both` |
| 6 | Triage of failures | `/triage` |
| 7 | Test completion report | `/report completion` |
