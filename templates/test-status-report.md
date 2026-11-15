<!--
Test status report template.
Structure follows the test status report of ISO/IEC/IEEE 29119-3.
Placeholders, blocks, items and agent sections are described in docs/reference/reports.md.
-->

# Test status report: {{ project.name }}

| Field | Value |
|---|---|
| Report | {{ report.id }} |
| Generated | {{ report.generated_at }} |
| Run | {{ run.id }} against `{{ run.version }}` |
| Reporting period | {{ run.started_at }} to {{ run.ended_at }} |
| Baseline run | {{ baseline_run.id }} |
| Model | `{{ model }}` |
| RetroAgent | {{ report.tool_version }} |

## 1. Test status

**Release decision if testing stopped now: `{{ decision.value }}`**

| Exit criteria | Count |
|---|---|
| Met | {{ criteria.met }} |
| Not met | {{ criteria.not_met }} |
| Not evaluable | {{ criteria.not_evaluable }} |

Reasons for the decision:

{{ list:decision_reasons }}

<!-- agent:status -->

## 2. Progress against the test plan

| Measure | Value |
|---|---|
| Planned | {{ metrics.planned }} |
| Implemented | {{ metrics.implemented }} |
| Implementation rate | {{ metrics.implementation_rate }} |
| Executed | {{ metrics.executed }} |
| Execution rate | {{ metrics.execution_rate }} |
| Passed | {{ metrics.passed }} |
| Failed | {{ metrics.failed }} |
| Error | {{ metrics.error }} |
| Blocked | {{ metrics.blocked }} |
| Skipped | {{ metrics.skipped }} |

![Execution outcomes](charts/outcomes.svg)

## 3. Factors blocking progress

{{ table:deviations }}

## 4. Test measures

| Metric | Value |
|---|---|
| Pass rate | {{ metrics.pass_rate }} |
| Product pass rate | {{ metrics.product_pass_rate }} |
| Flaky rate | {{ metrics.flaky_rate }} |
| Requirement coverage | {{ metrics.requirement_coverage }} |
| High-priority execution rate | {{ metrics.high_priority_executed_rate }} |
| New failures | {{ metrics.new_failures }} |
| Fixed | {{ metrics.fixed }} |

![Comparison with the baseline](charts/comparison.svg)

{{ table:criteria }}

## 5. Items requiring review

{{ table:review_items }}

Excused failures are excluded from the product pass rate, and flaky failures can reveal real faults. Both are listed so that they can be reviewed.

## 6. New and changed risks

Registered risks. New and changed risks are discussed below.

{{ table:risks }}

<!-- agent:risks -->

## 7. Planned testing

<!-- agent:next_steps -->
