<!--
Item template: one defect. Used by defect-report.md.
Values refer to the current defect.
-->

### {{ defect.id }}: {{ defect.title }}

| Field | Value |
|---|---|
| Status | `{{ defect.status }}` |
| Severity | `{{ defect.severity }}` |
| Detected in | {{ defect.run_id }} against `{{ defect.version }}` |
| Detected at | {{ defect.detected_at }} |
| Test cases | {{ defect.test_cases }} |
| Requirements | {{ defect.requirements }} |
| Triage | `{{ defect.classification }}` |

#### Expected and actual result

**Expected:** {{ defect.expected }}

**Actual:** {{ defect.actual }}

#### Steps to reproduce

{{ list:steps }}

#### Evidence

{{ table:evidence }}

#### History of the related test cases

{{ table:history }}

#### Triage justification

Written by `{{ defect.triaged_by }}` during triage:

{{ defect.justification }}

<!-- agent:analysis -->
