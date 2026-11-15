<!--
Item template: one test case. Used by test-case-specification.md.
Values refer to the current test case.
-->

### {{ test_case.id }}: {{ test_case.title }}

| Field | Value |
|---|---|
| Objective | {{ test_case.objective }} |
| Priority | `{{ test_case.priority }}` |
| Status | `{{ test_case.status }}` |
| Requirements | {{ test_case.requirements }} |
| Origin | {{ test_case.origin }} |
| Implementation | {{ test_case.implementation }} |
| Last execution | {{ test_case.last_execution }} |

#### Preconditions

{{ list:preconditions }}

#### Input data

{{ table:input_data }}

#### Steps

{{ list:steps }}

#### Expected result

{{ test_case.expected_result }}
