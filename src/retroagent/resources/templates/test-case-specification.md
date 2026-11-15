<!--
Test case specification template.
Structure follows the test case specification of ISO/IEC/IEEE 29119-3.
Each test case is rendered with templates/items/test-case.md.
Placeholders, blocks, items and agent sections are described in docs/reference/reports.md.
-->

# Test case specification: {{ project.name }}

| Field | Value |
|---|---|
| Report | {{ report.id }} |
| Generated | {{ report.generated_at }} |
| Baseline | `{{ versions.base.ref }}` (`{{ versions.base.commit }}`) |
| Candidate | `{{ versions.candidate.ref }}` (`{{ versions.candidate.commit }}`) |
| Model | `{{ model }}` |
| RetroAgent | {{ report.tool_version }} |

## 1. Summary

| Measure | Value |
|---|---|
| Test cases in the suite | {{ suite.planned }} |
| Implemented | {{ suite.implemented }} |
| Designed only | {{ suite.designed_only }} |

{{ table:test_cases }}

## 2. Traceability

{{ table:traceability }}

## 3. Test cases

{{ items:test_case }}
