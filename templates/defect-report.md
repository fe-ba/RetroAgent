<!--
Defect report template.
Each defect follows the incident report of ISO/IEC/IEEE 29119-3 and is rendered with templates/items/defect.md.
Placeholders, blocks, items and agent sections are described in docs/reference/reports.md.
-->

# Defect report: {{ project.name }}

| Field | Value |
|---|---|
| Report | {{ report.id }} |
| Generated | {{ report.generated_at }} |
| Candidate | `{{ versions.candidate.ref }}` (`{{ versions.candidate.commit }}`) |
| Evaluated run | {{ run.id }} |
| Model | `{{ model }}` |
| RetroAgent | {{ report.tool_version }} |

## 1. Summary

| Metric | Value |
|---|---|
| Found in this run | {{ metrics.defects_found }} |
| Closed | {{ metrics.defects_closed }} |
| Open, critical | {{ metrics.open_defects.critical }} |
| Open, high | {{ metrics.open_defects.high }} |
| Open, medium | {{ metrics.open_defects.medium }} |
| Open, low | {{ metrics.open_defects.low }} |

{{ table:defects }}

## 2. Defects

{{ items:defect }}
