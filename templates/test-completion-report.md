<!--
Test completion report template.
Structure follows the test completion report of ISO/IEC/IEEE 29119-3.
Placeholders, blocks and agent sections are described in docs/reference/reports.md.
Metric and exit criterion definitions are in docs/reference/metrics.md.
-->

# Test completion report: {{ project.name }}

| Field | Value |
|---|---|
| Report | {{ report.id }} |
| Generated | {{ report.generated_at }} |
| Baseline | `{{ versions.base.ref }}` (`{{ versions.base.commit }}`) |
| Candidate | `{{ versions.candidate.ref }}` (`{{ versions.candidate.commit }}`) |
| Evaluated run | {{ run.id }} |
| Baseline run | {{ baseline_run.id }} |
| Model | `{{ model }}` |
| RetroAgent | {{ report.tool_version }} |

## 1. Executive summary

**Release decision: `{{ decision.value }}`**

| Exit criteria | Count |
|---|---|
| Met | {{ criteria.met }} |
| Not met | {{ criteria.not_met }} |
| Not evaluable | {{ criteria.not_evaluable }} |

Reasons for the decision:

{{ list:decision_reasons }}

<!-- agent:conclusions -->

## 2. Summary of testing performed

| Measure | Value |
|---|---|
| Planned test cases | {{ metrics.planned }} |
| Executed | {{ metrics.executed }} |
| Passed | {{ metrics.passed }} |
| Failed | {{ metrics.failed }} |
| Error | {{ metrics.error }} |
| Blocked | {{ metrics.blocked }} |
| Skipped | {{ metrics.skipped }} |
| Run duration | {{ metrics.run_duration }} |
| Test time | {{ metrics.test_time }} |

![Execution outcomes](charts/outcomes.svg)

<!-- agent:summary -->

## 3. Scope: planned versus actual

| Metric | Value |
|---|---|
| Planned | {{ metrics.planned }} |
| Implemented | {{ metrics.implemented }} |
| Implementation rate | {{ metrics.implementation_rate }} |
| Designed only | {{ metrics.designed_only }} |
| Executed | {{ metrics.executed }} |
| Execution rate | {{ metrics.execution_rate }} |

## 4. Deviations from planned testing

{{ table:deviations }}

<!-- agent:deviations -->

## 5. Test completion evaluation

{{ table:criteria }}

![Exit criteria](charts/criteria.svg)

## 6. Test measures

### Results

| Metric | Value |
|---|---|
| Pass rate | {{ metrics.pass_rate }} |
| Excused failures | {{ metrics.excused }} |
| Product pass rate | {{ metrics.product_pass_rate }} |
| Flaky executions | {{ metrics.flaky }} |
| Flaky rate | {{ metrics.flaky_rate }} |

### Coverage

| Metric | Value |
|---|---|
| Impacted requirements | {{ metrics.impacted_requirements }} |
| Covered requirements | {{ metrics.covered_requirements }} |
| Requirement coverage | {{ metrics.requirement_coverage }} |
| High-priority test cases planned | {{ metrics.high_priority_planned }} |
| High-priority execution rate | {{ metrics.high_priority_executed_rate }} |

### Comparison with the baseline

| Metric | Value |
|---|---|
| New failures | {{ metrics.new_failures }} |
| Fixed | {{ metrics.fixed }} |
| Persistent failures | {{ metrics.persistent_failures }} |
| Stable passes | {{ metrics.stable_passes }} |
| Not comparable | {{ metrics.not_comparable }} |

![Comparison with the baseline](charts/comparison.svg)

### Selection quality

Informative only; not part of the exit criteria.

| Metric | Value |
|---|---|
| Revealing test cases | {{ metrics.revealing }} |
| Selection inclusiveness | {{ metrics.selection_inclusiveness }} |
| Selection precision | {{ metrics.selection_precision }} |

## 7. Defects

| Metric | Value |
|---|---|
| Found in this run | {{ metrics.defects_found }} |
| Closed | {{ metrics.defects_closed }} |
| Open, critical | {{ metrics.open_defects.critical }} |
| Open, high | {{ metrics.open_defects.high }} |
| Open, medium | {{ metrics.open_defects.medium }} |
| Open, low | {{ metrics.open_defects.low }} |

{{ table:open_defects }}

## 8. Items requiring review

{{ table:review_items }}

Excused failures are excluded from the product pass rate, and flaky failures can reveal real faults. Both are listed so that they can be reviewed.

## 9. Residual risks

{{ table:risks }}

<!-- agent:residual_risks -->

## 10. Limitations

{{ list:limitations }}

<!-- agent:limitations -->

## 11. Test deliverables

{{ table:deliverables }}

---

Metric definitions, exit criteria and the release decision rule are described in the RetroAgent metrics reference. Computed sections are reproducible from the project memory at the generation time above.
